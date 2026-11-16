#!/usr/bin/env bash
set -euo pipefail

AGY_DIR="${HOME}/.gemini/antigravity-cli"
TARGET_SCRIPT="${AGY_DIR}/statushow.py"
SETTINGS_FILE="${AGY_DIR}/settings.json"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOCAL_SOURCE="${SCRIPT_DIR}/statushow.py"

if [ ! -f "${LOCAL_SOURCE}" ]; then
  echo "Error: cannot find statushow.py at ${LOCAL_SOURCE}" >&2
  exit 1
fi

if ! command -v python3 >/dev/null 2>&1; then
  echo "Error: python3 is required but not found in PATH." >&2
  exit 1
fi

echo "==> Installing agycli_statushow..."
mkdir -p "${AGY_DIR}"
cp "${LOCAL_SOURCE}" "${TARGET_SCRIPT}"
chmod +x "${TARGET_SCRIPT}"

if [ -f "${SETTINGS_FILE}" ]; then
  cp "${SETTINGS_FILE}" "${SETTINGS_FILE}.bak_statusline"
fi

python3 - "${SETTINGS_FILE}" "${TARGET_SCRIPT}" <<'PY'
import json, os, sys

path, target = sys.argv[1], sys.argv[2]
cfg = {}
if os.path.isfile(path):
    with open(path, "r", encoding="utf-8") as f:
        content = f.read().strip()
        if content:
            cfg = json.loads(content)

cfg["statusLine"] = {
    "type": "command",
    "command": f"python3 {os.path.abspath(target)}",
    "enabled": True,
    "stack_with_default": True,
}

with open(path, "w", encoding="utf-8") as f:
    json.dump(cfg, f, ensure_ascii=False, indent=2)
    f.write("\n")
os.chmod(path, 0o600)
PY

echo "==> Installed successfully!"
echo "    Script:   ${TARGET_SCRIPT}"
echo "    Settings: ${SETTINGS_FILE}"
echo ""
echo "Tip: New 'agy' sessions enable it automatically."
echo "     In an already-open 'agy' session, run:"
echo "       /statusline python3 ${TARGET_SCRIPT}"
