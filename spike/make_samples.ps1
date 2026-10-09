# 用 Windows 內置 SAPI 聲音合成 ASR 測試樣本（16 kHz／16-bit／mono WAV）。
# 合成聲比真人清晰，只用作初步測試，不能代替真人錄音。
param([string]$SamplesJson = "$PSScriptRoot\samples.json", [string]$OutDir = "$PSScriptRoot\out\samples")

Add-Type -AssemblyName System.Speech
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
$format = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo 16000, ([System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen), ([System.Speech.AudioFormat.AudioChannel]::Mono)
$samples = Get-Content -Raw -Encoding UTF8 $SamplesJson | ConvertFrom-Json

foreach ($s in $samples) {
    $synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
    $synth.SelectVoice($s.voice)
    $path = Join-Path $OutDir "$($s.id).wav"
    $synth.SetOutputToWaveFile($path, $format)
    $synth.Speak($s.text)
    $synth.Dispose()
    Write-Output "$($s.id) -> $path"
}
