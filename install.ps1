$ErrorActionPreference = "Stop"

$AgyDir = Join-Path $HOME ".gemini\antigravity-cli"
$TargetScript = Join-Path $AgyDir "statushow.py"
$SettingsFile = Join-Path $AgyDir "settings.json"
$LocalSource = if ($PSScriptRoot) { Join-Path $PSScriptRoot "statushow.py" } else { Join-Path (Get-Location) "statushow.py" }

if (-not (Test-Path $LocalSource)) {
    throw "Cannot find statushow.py at '$LocalSource'. Please run install.ps1 from the project root directory."
}

$PyCmd = $null
foreach ($cand in @("python", "python3", "py")) {
    if (Get-Command $cand -ErrorAction SilentlyContinue) {
        $PyCmd = $cand
        break
    }
}
if (-not $PyCmd) {
    throw "Python 3 is required but not found in PATH."
}

Write-Host "==> Installing agycli_statushow for Windows..."
New-Item -ItemType Directory -Force -Path $AgyDir | Out-Null
Copy-Item $LocalSource $TargetScript -Force

if (Test-Path $SettingsFile) {
    Copy-Item $SettingsFile "$SettingsFile.bak_statusline" -Force
}

$PyArgs = @("-c", @"
import json, os, sys
settings_path, target_path, py_cmd = sys.argv[1], sys.argv[2], sys.argv[3]
cfg = {}
if os.path.isfile(settings_path):
    with open(settings_path, 'r', encoding='utf-8') as f:
        s = f.read().strip()
        if s:
            cfg = json.loads(s)
cfg['statusLine'] = {
    'type': 'command',
    'command': f'{py_cmd} {os.path.abspath(target_path)}',
    'enabled': True,
    'stack_with_default': True,
}
with open(settings_path, 'w', encoding='utf-8') as f:
    json.dump(cfg, f, ensure_ascii=False, indent=2)
    f.write('\n')
"@, $SettingsFile, $TargetScript, $PyCmd)

if ($PyCmd -eq "py") {
    & py -3 @PyArgs
} else {
    & $PyCmd @PyArgs
}

Write-Host "==> Installed successfully!"
Write-Host "    Script:   $TargetScript"
Write-Host "    Settings: $SettingsFile"
Write-Host ""
Write-Host "Tip: In an already-open 'agy' session, run:"
Write-Host "     /statusline $PyCmd $TargetScript"
