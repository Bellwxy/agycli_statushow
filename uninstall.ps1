$ErrorActionPreference = "Stop"

$AgyDir = Join-Path $HOME ".gemini\antigravity-cli"
$TargetScript = Join-Path $AgyDir "statushow.py"
$SettingsFile = Join-Path $AgyDir "settings.json"

Write-Host "==> Uninstalling agycli_statushow..."

if (Test-Path $TargetScript) {
    Remove-Item $TargetScript -Force
}

$TempDir = [System.IO.Path]::GetTempPath()
Get-ChildItem -Path $TempDir -Filter "agy_ctx_status_*.json*" -ErrorAction SilentlyContinue | Remove-Item -Force -ErrorAction SilentlyContinue

if (Test-Path $SettingsFile) {
    $PyCmd = $null
    foreach ($cand in @("python", "python3", "py")) {
        if (Get-Command $cand -ErrorAction SilentlyContinue) {
            $PyCmd = $cand
            break
        }
    }
    if ($PyCmd) {
        $PyArgs = @("-c", @"
import json, os, sys
p = sys.argv[1]
with open(p, 'r', encoding='utf-8') as f:
    s = f.read().strip()
    if not s:
        sys.exit(0)
    cfg = json.loads(s)
sl = cfg.get('statusLine')
if isinstance(sl, dict) and 'statushow.py' in str(sl.get('command', '')):
    cfg.pop('statusLine', None)
    with open(p, 'w', encoding='utf-8') as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
        f.write('\n')
"@, $SettingsFile)
        if ($PyCmd -eq "py") {
            & py -3 @PyArgs
        } else {
            & $PyCmd @PyArgs
        }
    }
}

Write-Host "==> Uninstalled cleanly. In open 'agy' sessions, run: /statusline delete"
