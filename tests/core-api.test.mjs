import { test, afterEach } from 'node:test';
import { strict as assert } from 'node:assert';
process.env.NEXT_PUBLIC_CORE_API_URL = 'http://127.0.0.1:9876/api/v1/';
const { api, ApiError, CORE_API_BASE, contentUrl } = await import('../lib/core-api.ts');
const originalFetch = globalThis.fetch;
afterEach(() => { globalThis.fetch = originalFetch; });
test('configured API base normalizes trailing slash and covers downloads', () => {
  assert.equal(CORE_API_BASE,'http://127.0.0.1:9876/api/v1');
  assert.equal(contentUrl('asset'),CORE_API_BASE+'/assets/asset/content');
});
test('health uses the same base as project APIs', async () => {
  globalThis.fetch = async (url) => { assert.equal(url,CORE_API_BASE+'/health'); return Response.json({status:'ok',version:'1.0.1'}); };
  assert.equal((await api.health()).status,'ok');
});
test('ZIP uploads use multipart with browser-generated boundary', async () => {
  globalThis.fetch = async (url, init) => {
    assert.equal(url,CORE_API_BASE+'/projects/p/imports/archive');
    assert.equal(init.method,'POST'); assert(init.body instanceof FormData);
    assert.equal(init.headers['Content-Type'],undefined);
    assert.equal(init.body.get('file').name,'a.ZIP');
    return Response.json({imported_count:2});
  };
  assert.equal((await api.upload('p',new File(['zip'],'a.ZIP'))).imported_count,2);
});
test('single media upload uses assets endpoint', async () => {
  globalThis.fetch = async (url) => { assert.equal(url,CORE_API_BASE+'/projects/p/assets'); return Response.json({asset:{id:'a'}}); };
  assert.equal((await api.upload('p',new File(['png'],'image.png'))).asset.id,'a');
});
test('invalid uploads retain server error code and HTTP status', async () => {
  globalThis.fetch = async () => Response.json({detail:{code:'UNSUPPORTED_ASSET',message:'Unsupported file'}},{status:422});
  await assert.rejects(api.upload('p',new File(['exe'],'file.exe')),error => error instanceof ApiError && error.code==='UNSUPPORTED_ASSET' && error.status===422);
});
test('network failures have a distinct error category', async () => {
  globalThis.fetch = async () => { throw new TypeError('fetch failed'); };
  await assert.rejects(api.projects(),error => error.code==='NETWORK_ERROR' && error.status===0);
});
test('non-JSON API success is a protocol error', async () => {
  globalThis.fetch = async () => new Response('<html>wrong server</html>');
  await assert.rejects(api.projects(),error => error.code==='INVALID_RESPONSE');
});
test('request timeout is classified separately', async () => {
  const realSetTimeout=globalThis.setTimeout;
  globalThis.setTimeout=(callback) => realSetTimeout(callback,1);
  globalThis.fetch=async (_url,init) => new Promise((_,reject) => init.signal.addEventListener('abort',()=>reject(new DOMException('Aborted','AbortError'))));
  try { await assert.rejects(api.projects(),error => error.code==='TIMEOUT'); }
  finally { globalThis.setTimeout=realSetTimeout; }
});
