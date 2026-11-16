#!/usr/bin/env bash
set -euo pipefail

AGY_DIR="${HOME}/.gemini/antigravity-cli"
TARGET_SCRIPT="${AGY_DIR}/statushow.py"
SETTINGS_FILE="${AGY_DIR}/settings.json"

echo "==> Uninstalling agycli_statushow..."

rm -f "${TARGET_SCRIPT}"
rm -f "/tmp/agy_ctx_status_$(id -u).json" 2>/dev/null || true

if [ -f "${SETTINGS_FILE}" ] && command -v python3 >/dev/null 2>&1; then
  python3 - "${SETTINGS_FILE}" <<'PY'
import json, sys

path = sys.argv[1]
with open(path, "r", encoding="utf-8") as f:
    content = f.read().strip()
    if not content:
        sys.exit(0)
    cfg = json.loads(content)

sl = cfg.get("statusLine")
if isinstance(sl, dict) and "statushow.py" in str(sl.get("command", "")):
    cfg.pop("statusLine", None)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
        f.write("\n")
PY
fi

echo "==> Uninstalled cleanly. In open 'agy' sessions, run: /statusline delete"
