param([switch]$NoBrowser, [switch]$SkipOptionalTools)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
function Refresh-ProcessPath {
    $env:Path = [Environment]::GetEnvironmentVariable('Path','Machine') + ';' + [Environment]::GetEnvironmentVariable('Path','User')
}
function Install-Prerequisite($Package) {
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) { throw 'Windows App Installer (winget) is required for automatic prerequisite installation. Install Python 3.13 and Node.js LTS, then double-click this launcher again.' }
    & winget install --id $Package --exact --source winget --accept-package-agreements --accept-source-agreements --disable-interactivity
    if ($LASTEXITCODE -ne 0) { throw "Could not install $Package. Check your internet connection and the installer message above." }
    Refresh-ProcessPath
}
try {
    $FreeBytes = ([System.IO.DriveInfo]([System.IO.Path]::GetPathRoot($PSScriptRoot))).AvailableFreeSpace
    if (-not (Test-Path -LiteralPath (Join-Path $PSScriptRoot '.mediasensei-launcher/dependencies.json')) -and $FreeBytes -lt 5GB) {
        throw 'First setup needs at least 5 GiB free disk space for installers, dependencies and processing headroom. Free space and run this BAT again.'
    }
    if ($FreeBytes -lt 3GB) { $SkipOptionalTools = $true; Write-Warning 'Optional media installation deferred until at least 3 GiB is free. Processing pauses below 2 GiB.' }
    Write-Host 'MediaSensei: checking Python and Node.js. First launch requires internet.'
    $Python = $null
    foreach ($Candidate in @((Join-Path $PSScriptRoot '.venv\Scripts\python.exe'),'py','python')) {
        if (Get-Command $Candidate -ErrorAction SilentlyContinue) {
            [string[]]$PythonPrefix = @()
            if ($Candidate -eq 'py') { $PythonPrefix = @('-3.13') }
            $ErrorActionPreference = 'Continue'
            & $Candidate @PythonPrefix -c 'import sys; sys.exit(0 if (3,12) <= sys.version_info < (3,15) else 1)' 2>$null
            $ProbeExit = $LASTEXITCODE
            $ErrorActionPreference = 'Stop'
            if ($ProbeExit -eq 0) { $Python = $Candidate; break }
        }
    }
    if (-not $Python) {
        Install-Prerequisite 'Python.Python.3.13'
        $Python = 'py'; $PythonPrefix = @('-3.13')
    }
    $NodeReady = $false
    if (Get-Command node -ErrorAction SilentlyContinue) {
        $NodeVersion = (& node --version).Trim().TrimStart('v')
        $NodeReady = [version]$NodeVersion -ge [version]'22.13.0' 
    }
    if (-not $NodeReady) { Install-Prerequisite 'OpenJS.NodeJS.LTS' }
    $MediaStamp = Join-Path $PSScriptRoot '.mediasensei-media-setup'
    if (-not $SkipOptionalTools -and -not (Test-Path -LiteralPath $MediaStamp)) {
        foreach ($Tool in @(@{Name='ffmpeg';Package='Gyan.FFmpeg'}, @{Name='tesseract';Package='UB-Mannheim.TesseractOCR'})) {
            if (-not (Get-Command $Tool.Name -ErrorAction SilentlyContinue)) {
                try { Install-Prerequisite $Tool.Package }
                catch { Write-Warning "Optional media tool setup: $($_.Exception.Message). Data/table workflows can still run. Delete .mediasensei-media-setup to retry on next launch." }
            }
        }
        Set-Content -LiteralPath $MediaStamp -Value 'Attempted native media setup'
    }
    if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue)) {
        $Packages = Join-Path $env:LOCALAPPDATA 'Microsoft\WinGet\Packages'
        $InstalledFfmpeg = Get-ChildItem -LiteralPath $Packages -Filter ffmpeg.exe -Recurse -ErrorAction SilentlyContinue | Where-Object { $_.FullName -like '*Gyan.FFmpeg*' } | Select-Object -First 1
        if ($InstalledFfmpeg) { $env:MEDIASENSEI_FFMPEG=$InstalledFfmpeg.FullName; $env:MEDIASENSEI_FFPROBE=Join-Path $InstalledFfmpeg.DirectoryName 'ffprobe.exe' }
    }
    $Tesseract = Join-Path $env:ProgramFiles 'Tesseract-OCR\tesseract.exe'
    if (Test-Path -LiteralPath $Tesseract) { $env:MEDIASENSEI_TESSERACT=$Tesseract }
    $LauncherArguments = @('scripts/mediasensei_launcher.py','start')
    if ($NoBrowser) { $LauncherArguments += '--no-browser' }
    & $Python @PythonPrefix @LauncherArguments
    if ($LASTEXITCODE -ne 0) { throw 'Startup failed. See .mediasensei-launcher/logs for details.' }
} catch {
    Write-Host $_.Exception.Message -ForegroundColor Red
    Read-Host 'Press Enter to close'
    exit 1
}
