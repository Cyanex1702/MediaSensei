from __future__ import annotations

import io
import subprocess
import sys
import zipfile

import pytest
from test_real_app_flow import _client, _drain_worker, _png_bytes

import apps.api.main as api_module
from scripts.mediasensei_launcher import _alive


@pytest.fixture
def project(tmp_path):
    client = _client(tmp_path)
    project_id = client.post('/api/v1/projects', json={'name':'Audit'}).json()['id']
    return client, project_id

def upload(project, name, data, endpoint='assets'):
    client, project_id = project
    return client.post(f'/api/v1/projects/{project_id}/{endpoint}', files={'file':(name,data)})

def archive(entries):
    result = io.BytesIO()
    with zipfile.ZipFile(result,'w',zipfile.ZIP_DEFLATED) as bundle:
        for name,data in entries:
            bundle.writestr(name,data)
    return result.getvalue()

def test_windows_process_health_does_not_kill_child():
    child = subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)'], creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    try:
        for _ in range(5):
            assert _alive(child.pid)
        assert child.poll() is None
    finally:
        child.terminate(); child.wait(timeout=5)
    assert not _alive(child.pid)

def test_health_openapi_and_cors(project):
    client,_ = project
    with client:
        assert client.get('/health').json()['status'] == 'ok'
        assert client.get('/api/v1/health').json()['version'] == api_module.__version__
        assert '/api/v1/projects/{project_id}/assets' in client.get('/openapi.json').json()['paths']
        headers={'Origin':'http://localhost:3000','Access-Control-Request-Method':'POST'}
        assert client.options('/api/v1/projects',headers=headers).status_code == 200
        headers['Origin']='https://untrusted.example'
        assert client.options('/api/v1/projects',headers=headers).status_code == 400

@pytest.mark.parametrize('name,data,code',[('empty.png',b'','EMPTY_FILE'),('x.exe',b'123','UNSUPPORTED_ASSET'),('noextension',b'123','UNSUPPORTED_ASSET')])
def test_invalid_uploads(project,name,data,code):
    response=upload(project,name,data)
    assert response.status_code == 422
    assert response.json()['detail']['code'] == code
    assert not list((api_module.WORKSPACE/'temp'/'uploads').glob('*'))

@pytest.mark.parametrize('endpoint,name',[('documents','x.txt'),('media','x.wav'),('tabular','x.csv')])
def test_all_upload_endpoints_reject_empty(project,endpoint,name):
    response=upload(project,name,b'',endpoint)
    assert response.status_code==422
    assert response.json()['detail']['code']=='EMPTY_FILE'

def test_large_file_limit_and_recovery(project,monkeypatch):
    monkeypatch.setattr(api_module.settings,'max_upload_bytes',8)
    assert upload(project,'x.txt',b'123456789').status_code==413
    assert upload(project,'x.txt',b'good').status_code==202
    assert not list((api_module.WORKSPACE/'temp'/'uploads').glob('*'))

def test_unicode_spaces_duplicates_and_nested_zip(project):
    data=archive([('nested/日本語 photo.png',_png_bytes()),('other/same.txt',b'first'),('deep/nested/same.txt',b'second'),('bad.exe',b'123'),('empty.txt',b'')])
    response=upload(project,'dataset.zip',data,'imports/archive')
    assert response.status_code==202,response.text
    result=response.json()
    assert result['imported_count']==3 and result['skipped_count']==2
    _drain_worker()
    client,pid=project
    assert len(client.get(f'/api/v1/projects/{pid}/assets').json()['items'])==3

@pytest.mark.parametrize('name',['../escape.png','C:/outside.png','a:stream.png','/absolute.png','a/../../bad.png'])
def test_zip_unsafe_names(project,name):
    response=upload(project,'x.zip',archive([(name,_png_bytes()),('safe.png',_png_bytes())]),'imports/archive')
    assert response.status_code==202
    assert response.json()['imported_count']==1
    assert response.json()['skipped'][0]['reason']=='unsafe path'

def test_corrupt_zip_and_no_supported_files(project):
    assert upload(project,'broken.zip',b'not a zip','imports/archive').json()['detail']['code']=='INVALID_ZIP'
    assert upload(project,'x.zip',archive([('nested.zip',b'x')]),'imports/archive').json()['detail']['code']=='ZIP_NO_SUPPORTED_FILES'

def test_crc_failure_does_not_partially_import(project):
    data=bytearray(archive([('first.txt',b'hello'),('second.txt',b'world')]))
    # Damage second member's central-directory CRC, while first remains valid.
    first=data.index(b'PK\x01\x02'); second=data.index(b'PK\x01\x02',first+4)
    data[second+16] ^= 1
    response=upload(project,'bad.zip',bytes(data),'imports/archive')
    assert response.status_code==422
    client,pid=project
    assert client.get(f'/api/v1/projects/{pid}/assets').json()['items']==[]
    assert not list((api_module.WORKSPACE/'temp').glob('archive-*'))

def test_zip_limits(project,monkeypatch):
    monkeypatch.setattr(api_module.settings,'zip_max_files',1)
    response=upload(project,'x.zip',archive([('a.txt',b'a'),('b.txt',b'b')]),'imports/archive')
    assert response.status_code==413
    monkeypatch.setattr(api_module.settings,'zip_max_files',20)
    monkeypatch.setattr(api_module.settings,'zip_max_total_bytes',1)
    assert upload(project,'x.zip',archive([('a.txt',b'aa')]),'imports/archive').status_code==413

def test_malformed_image_produces_visible_job_failure(project):
    response=upload(project,'bad.png',b'not an image')
    assert response.status_code==202
    _drain_worker()
    client,_=project
    job=client.get('/api/v1/jobs/'+response.json()['jobs'][0]['id']).json()
    assert job['counts']['failed']>0 or job['state']=='completed_with_errors'

def test_missing_multipart_validation_is_json(project):
    client,pid=project
    response=client.post(f'/api/v1/projects/{pid}/assets',json={})
    assert response.status_code==422
    assert response.json()['detail']['code']=='VALIDATION_ERROR'

def test_tabular_query_export_and_validation(project):
    response=upload(project,'observations.csv',b'species,count\nfox,2\nowl,3\n')
    assert response.status_code==202
    _drain_worker()
    client,pid=project
    dataset=client.get(f'/api/v1/projects/{pid}/tabular').json()['items'][0]
    result=client.post(f"/api/v1/tabular/{dataset['id']}/query",json={'search':'fox'})
    assert result.status_code==200,result.text
    assert 'fox' in result.text and 'owl' not in result.text
    bad=client.post(f"/api/v1/tabular/{dataset['id']}/query",json={'visible_columns':['not_a_column']})
    assert bad.status_code==422
    export=client.post(f"/api/v1/tabular/{dataset['id']}/export",json={'name':'audit','format':'csv'})
    assert export.status_code==201,export.text
    assert client.get(f"/api/v1/tabular/exports/{export.json()['id']}/download").status_code==200

def test_dataset_split_duplicates_leakage_export(project):
    upload(project,'a.png',_png_bytes()); upload(project,'b.png',_png_bytes())
    _drain_worker()
    client,pid=project
    for endpoint,body in [('images/duplicates',None),('dataset/split',{'strategy':'random','seed':42}),('dataset/leakage',None)]:
        response=client.post(f'/api/v1/projects/{pid}/{endpoint}',json=body)
        assert response.status_code==200,response.text
    response=client.post(f'/api/v1/projects/{pid}/dataset/export',json={'name':'audit'})
    assert response.status_code==201,response.text
    assert client.get(f"/api/v1/dataset/exports/{response.json()['id']}/download").status_code==200

@pytest.mark.parametrize('name,data', [('page.htm',b'<p>Foxes live near rivers</p>'),('notes.markdown',b'# Foxes\nFoxes live near rivers'),('rows.ndjson',b'{"a":1}\n{"a":2}\n')])
def test_advertised_format_aliases(project,name,data):
    response=upload(project,name,data)
    assert response.status_code==202,response.text
    _drain_worker()
    client,_=project
    for job in response.json()['jobs']:
        result=client.get('/api/v1/jobs/'+job['id']).json()
        assert result['state']=='completed',result

def test_request_body_and_cross_origin_boundaries(project,monkeypatch):
    client,pid=project
    monkeypatch.setattr(api_module.settings,'max_upload_bytes',8)
    result=client.post(f'/api/v1/projects/{pid}/assets',content=b'x',headers={'Content-Length':str(2*1024*1024)})
    assert result.status_code==413
    result=client.post('/api/v1/projects',json={'name':'bad'},headers={'Origin':'https://attacker.example'})
    assert result.status_code==403

def test_untrusted_plugin_is_not_imported(tmp_path):
    from mediasensei.infrastructure.plugins import (
        PluginExecutionError,
        PluginSubprocessExecutor,
        PluginTrustStore,
    )
    marker=tmp_path/'executed'
    plugin=tmp_path/'evil.py'
    plugin.write_text(f'from pathlib import Path\nPath({str(marker)!r}).touch()\n')
    executor=PluginSubprocessExecutor(PluginTrustStore(tmp_path/'trust.json'))
    with pytest.raises(PluginExecutionError):
        executor.analyze(plugin,'unused')
    assert not marker.exists()

def test_stale_launcher_pid_is_ignored(tmp_path,monkeypatch):
    import json
    import os

    import scripts.mediasensei_launcher as launcher
    state=tmp_path/'processes.json'
    state.write_text(json.dumps({'api':{'pid':os.getpid(),'identity':'stale'}}))
    monkeypatch.setattr(launcher,'PIDS',state)
    assert launcher.process_status()=={}

def test_long_processor_renews_lease(tmp_path):
    import time
    from concurrent.futures import ThreadPoolExecutor

    from mediasensei.domain.jobs import ProcessorSpec, WorkItem
    from mediasensei.infrastructure.catalog import Catalog
    from mediasensei.infrastructure.jobs import JobQueue
    from mediasensei.infrastructure.scheduler import HardwareProfile
    from mediasensei.infrastructure.worker import LocalWorker, ProcessorRegistry
    queue=JobQueue(Catalog(tmp_path))
    pid=str(queue.catalog.create_project('Lease').id)
    registry=ProcessorRegistry()
    registry.register('slow',lambda item,params: (time.sleep(6),{'ok':True})[1])
    queue.enqueue(project_id=pid,kind='slow',processor=ProcessorSpec(id='slow',version='1'),items=[WorkItem('a'*64,'unused',0)])
    worker=LocalWorker(queue,registry=registry,lease_seconds=5,hardware=HardwareProfile(2,None,None,20*1024**3))
    with ThreadPoolExecutor() as executor:
        pending=executor.submit(worker.run_once)
        time.sleep(5.5)
        assert queue.claim_next('other',lease_seconds=5) is None
        assert pending.result(timeout=10).state.value=='completed'

