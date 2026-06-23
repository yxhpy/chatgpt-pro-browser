#!/usr/bin/env bash
# install.sh — install the chatgpt-pro-browser skill for ZCode/Codex.
#
# What it does:
#   1. Verifies prerequisites (delegates to prereq_check.sh, non-fatal).
#   2. Installs Python deps (playwright, cryptography).
#   3. Installs Playwright's Chromium browser.
#   4. Symlinks (or copies) the skill into ~/.agents/skills/ so ZCode discovers it.
#
# Usage:
#   bash install.sh            # symlink install (recommended; live-updates on git pull)
#   bash install.sh --copy     # copy install (frozen snapshot)
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_NAME="chatgpt-pro-browser"
SRC_SKILL="$REPO_ROOT/skills/$SKILL_NAME"
DEST_ROOT="${HOME}/.agents/skills"
DEST_SKILL="$DEST_ROOT/$SKILL_NAME"
MODE="symlink"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --copy) MODE="copy"; shift ;;
    --symlink) MODE="symlink"; shift ;;
    -h|--help)
      echo "Usage: bash install.sh [--copy|--symlink]"
      echo "  --symlink (default): symlink skill into ~/.agents/skills/ (live-updates)"
      echo "  --copy: copy skill into ~/.agents/skills/ (frozen snapshot)"
      exit 0 ;;
    *) echo "Unknown option: $1"; exit 1 ;;
  esac
done

echo "=== chatgpt-pro-browser installer ==="
echo "repo:   $REPO_ROOT"
echo "mode:   $MODE"
echo "target: $DEST_SKILL"
echo

# 1. Prerequisite check (informational; don't abort so --copy still works)
echo "--- [1/4] prerequisites ---"
if bash "$SRC_SKILL/scripts/prereq_check.sh"; then
  :
else
  echo "[warn] prerequisite check reported failures — see above."
  echo "       The skill will be installed anyway, but it won't run until fixed."
fi
echo

# 2. Python dependencies
echo "--- [2/4] python dependencies ---"
if [[ -f "$REPO_ROOT/requirements.txt" ]]; then
  pip3 install --quiet --user -r "$REPO_ROOT/requirements.txt" || {
    echo "[warn] pip install --user failed; trying without --user"
    pip3 install --quiet -r "$REPO_ROOT/requirements.txt" || {
      echo "[error] could not install python deps"; exit 1; }
  }
  echo "installed: $(python3 -c 'import playwright, cryptography; print("playwright + cryptography")' 2>/dev/null || echo 'verify failed')"
fi
echo

# 3. Playwright Chromium
echo "--- [3/4] playwright chromium browser ---"
python3 -m playwright install chromium 2>/dev/null || {
  echo "[warn] playwright install chromium failed — run it manually later"
}
echo

# 4. Install the skill
echo "--- [4/4] install skill ---"
mkdir -p "$DEST_ROOT"
if [[ -e "$DEST_SKILL" || -L "$DEST_SKILL" ]]; then
  echo "[info] removing existing $DEST_SKILL"
  rm -rf "$DEST_SKILL"
fi
if [[ "$MODE" == "symlink" ]]; then
  ln -s "$SRC_SKILL" "$DEST_SKILL"
  echo "symlinked: $DEST_SKILL -> $SRC_SKILL"
else
  cp -R "$SRC_SKILL" "$DEST_SKILL"
  echo "copied: $SRC_SKILL -> $DEST_SKILL"
fi
echo

echo "=== done ==="
echo
echo "The skill is now discoverable by ZCode. Verify:"
echo "  ls -la $DEST_SKILL/SKILL.md"
echo
echo "Quick test (sends one prompt to your ChatGPT Pro):"
echo "  python3 $REPO_ROOT/skills/$SKILL_NAME/scripts/ask.py 'hello, which model are you?'"
echo
echo "Run the full test suite (20 tests, uses your Pro quota):"
echo "  cd $REPO_ROOT && python3 run_suite.py --only single"
