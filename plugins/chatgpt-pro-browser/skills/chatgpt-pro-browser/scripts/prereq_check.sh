#!/usr/bin/env bash
# prereq_check.sh — verify the environment can run the chatgpt-pro-browser skill.
# Run:  bash skills/chatgpt-pro-browser/scripts/prereq_check.sh
set -u

PASS=0; FAIL=0
ok()   { echo "  [PASS] $1"; PASS=$((PASS+1)); }
bad()  { echo "  [FAIL] $1"; FAIL=$((FAIL+1)); }
info() { echo "  [INFO] $1"; }

echo "chatgpt-pro-browser prerequisite check"
echo "--------------------------------------"

# 1. macOS
if [[ "$(uname -s)" == "Darwin" ]]; then
  ok "macOS ($(sw_vers -productVersion))"
else
  bad "Not macOS ($(uname -s)) — this skill requires macOS (Keychain + Chrome paths)"
fi

# 2. Google Chrome installed
CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
if [[ -x "$CHROME" ]]; then
  ok "Google Chrome installed ($("$CHROME" --version 2>/dev/null))"
else
  bad "Google Chrome not found at /Applications/Google Chrome.app — install from https://google.com/chrome"
fi

# 3. Python 3.10+
if command -v python3 >/dev/null 2>&1; then
  PY_VER=$(python3 -c 'import sys;print("%d.%d"%sys.version_info[:2])' 2>/dev/null)
  PY_OK=$(python3 -c 'import sys;print(1 if sys.version_info>=(3,10) else 0)' 2>/dev/null)
  if [[ "$PY_OK" == "1" ]]; then
    ok "Python $PY_VER"
  else
    bad "Python $PY_VER — need 3.10+"
  fi
else
  bad "python3 not found"
  PY_VER=""
fi

# 4. Python dependencies
if [[ -n "$PY_VER" ]]; then
  for mod in playwright cryptography; do
    if python3 -c "import $mod" 2>/dev/null; then
      ok "Python module: $mod"
    else
      bad "Python module: $mod (pip3 install $mod)"
    fi
  done
  # 5. Playwright Chromium downloaded
  if python3 -c "from playwright.sync_api import sync_playwright" 2>/dev/null; then
    if python3 -c "
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    b = p.chromium.launch(headless=True)
    b.close()
" 2>/dev/null; then
      ok "Playwright Chromium browser ready"
    else
      bad "Playwright Chromium not downloaded (run: python3 -m playwright install chromium)"
    fi
  fi
fi

# 6. Chrome has logged into chatgpt.com (cookies exist)
COOKIES_DB="$HOME/Library/Application Support/Google/Chrome/Default/Cookies"
if [[ -f "$COOKIES_DB" ]]; then
  COUNT=$(python3 -c "
import sqlite3, sys
try:
    con = sqlite3.connect('file:$COOKIES_DB?mode=ro', uri=True)
    cur = con.cursor()
    cur.execute(\"SELECT COUNT(*) FROM cookies WHERE host_key LIKE '%chatgpt%'\")
    print(cur.fetchone()[0])
    con.close()
except Exception:
    print(0)
" 2>/dev/null)
  if [[ "${COUNT:-0}" -gt 0 ]]; then
    ok "Chrome has $COUNT chatgpt.com cookies (logged in at least once)"
  else
    bad "No chatgpt.com cookies in Chrome — open Chrome, go to chatgpt.com, and log in"
  fi
else
  bad "Chrome Cookies DB not found ($COOKIES_DB) — have you used Chrome?"
fi

# 7. Keychain has Chrome Safe Storage (decryption key)
if security find-generic-password -s "Chrome Safe Storage" -a Chrome >/dev/null 2>&1; then
  ok "macOS Keychain has 'Chrome Safe Storage' (decryption key available)"
  info "First run will pop a Keychain dialog — click 'Allow' (or 'Always Allow')"
else
  bad "Keychain missing 'Chrome Safe Storage' — Chrome may need a restart to create it"
fi

echo "--------------------------------------"
echo "Result: $PASS passed, $FAIL failed"
if [[ "$FAIL" -gt 0 ]]; then
  echo "Fix the failing items above, then re-run this check."
  exit 1
else
  echo "All checks passed — ready to use chatgpt-pro-browser."
  exit 0
fi
