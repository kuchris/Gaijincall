# 用 Windows 內置 SAPI 唔同聲音合成講者辨識測試樣本（16 kHz／16-bit／mono）。
param([string]$Json = "$PSScriptRoot\speaker_samples.json", [string]$OutDir = "$PSScriptRoot\out\spk")

Add-Type -AssemblyName System.Speech
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
$format = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo 16000, ([System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen), ([System.Speech.AudioFormat.AudioChannel]::Mono)
$data = Get-Content -Raw -Encoding UTF8 $Json | ConvertFrom-Json
$sid = 0
foreach ($voice in $data.PSObject.Properties) {
    $i = 0
    foreach ($text in $voice.Value) {
        $s = New-Object System.Speech.Synthesis.SpeechSynthesizer
        $s.SelectVoice($voice.Name)
        $s.SetOutputToWaveFile((Join-Path $OutDir "s$sid-$i.wav"), $format)
        $s.Speak($text)
        $s.Dispose()
        $i++
    }
    $sid++
}
Write-Output "done: $sid speakers"
