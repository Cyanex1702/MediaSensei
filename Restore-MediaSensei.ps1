$ErrorActionPreference='Stop'
Set-Location -LiteralPath $PSScriptRoot
Add-Type -AssemblyName System.Windows.Forms
try {
 $archive=New-Object System.Windows.Forms.OpenFileDialog
 $archive.Filter='MediaSensei backup (*.zip)|*.zip';$archive.Title='Choose a MediaSensei workspace backup'
 if($archive.ShowDialog() -ne 'OK'){exit 0}
 $folder=New-Object System.Windows.Forms.FolderBrowserDialog
 $folder.Description='Choose a parent folder. A NEW restored workspace will be created inside it.'
 if($folder.ShowDialog() -ne 'OK'){exit 0}
 $destination=Join-Path $folder.SelectedPath ('MediaSensei-restored-'+(Get-Date -Format 'yyyyMMdd-HHmmss'))
 $python=Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
 if(-not(Test-Path -LiteralPath $python)){throw 'Run MediaSensei-Windows.bat first to prepare the app.'}
 & $python scripts/workspace_backup.py restore --archive $archive.FileName --destination $destination --activate
 if($LASTEXITCODE -ne 0){throw 'Restore failed. The existing workspace was not overwritten.'}
 [System.Windows.Forms.MessageBox]::Show("Restored to $destination. Start MediaSensei-Windows.bat to use it. Re-save provider credentials for the new location.",'Restore complete') > $null
} catch { [System.Windows.Forms.MessageBox]::Show($_.Exception.Message,'Restore failed') > $null;exit 1 }
