param([Parameter(Mandatory=$true)][string]$RequestFile)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
Add-Type -AssemblyName System.Speech
$request = Get-Content -LiteralPath $RequestFile -Raw -Encoding UTF8 | ConvertFrom-Json
$speaker = [System.Speech.Synthesis.SpeechSynthesizer]::new()
try {
    if ($request.action -eq 'voices') {
        $names = @($speaker.GetInstalledVoices() | Where-Object Enabled | ForEach-Object { $_.VoiceInfo.Name })
        ConvertTo-Json -InputObject $names -Compress
    } elseif ($request.action -eq 'speak') {
        $speaker.SelectVoice([string]$request.voice)
        $speaker.Rate = [int]$request.rate
        $speaker.SetOutputToWaveFile([string]$request.output)
        $speaker.Speak([string]$request.text)
        ConvertTo-Json -InputObject @{provider='Windows.System.Speech'; version=[System.Speech.Synthesis.SpeechSynthesizer].Assembly.FullName; voice=$request.voice} -Compress
    } else { throw 'Unsupported speech action' }
} finally { $speaker.Dispose() }
