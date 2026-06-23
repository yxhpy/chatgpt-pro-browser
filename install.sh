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
# Both skills shipped by this plugin:
SKILL_NAMES=("chatgpt-pro-browser" "chatgpt-pro-planner")
DEST_ROOT="${HOME}/.agents/skills"
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
echo "targets: ${SKILL_NAMES[*]}"
echo

# 1. Prerequisite check (informational; don't abort so --copy still works)
echo "--- [1/4] prerequisites ---"
if bash "$REPO_ROOT/plugins/chatgpt-pro-browser/skills/chatgpt-pro-browser/scripts/prereq_check.sh"; then
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

# 4. Install the skills
echo "--- [4/4] install skills ---"
mkdir -p "$DEST_ROOT"
for SKILL_NAME in "${SKILL_NAMES[@]}"; do
  SRC_SKILL="$REPO_ROOT/plugins/chatgpt-pro-browser/skills/$SKILL_NAME"
  DEST_SKILL="$DEST_ROOT/$SKILL_NAME"
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
done
echo

echo "=== done ==="
echo
echo "Both skills are now discoverable by ZCode. Verify:"
echo "  ls -la $DEST_ROOT/chatgpt-pro-browser/SKILL.md"
echo "  ls -la $DEST_ROOT/chatgpt-pro-planner/SKILL.md"
echo
echo "Quick tests:"
echo "  # call ChatGPT Pro:"
echo "  python3 $REPO_ROOT/plugins/chatgpt-pro-browser/skills/chatgpt-pro-browser/scripts/ask.py 'hello, which model are you?'"
echo "  # generate an executable dev plan via Pro:"
echo "  python3 $REPO_ROOT/plugins/chatgpt-pro-browser/skills/chatgpt-pro-planner/scripts/plan.py dev 'your goal here' --context README.md"
echo
echo "As a plugin (zcode/codex): this repo ships .zcode-plugin/plugin.json and"
echo "  .codex-plugin/plugin.json — use your CLI's plugin-add command against"
echo "  https://github.com/yxhpy/chatgpt-pro-browser"
