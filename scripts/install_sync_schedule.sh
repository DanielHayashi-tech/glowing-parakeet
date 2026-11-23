#!/bin/bash
# Install (or remove) the nightly Garmin sync as a macOS launchd agent.
#
#   scripts/install_nightly_sync.sh              install, runs every night at 00:00
#   scripts/install_nightly_sync.sh --run-now    trigger one run immediately
#   scripts/install_nightly_sync.sh --uninstall  remove it
#
# launchd runs a missed job when the Mac wakes, so a sleeping laptop at midnight
# still syncs. Output goes to ~/Library/Logs/move2zero-sync.log and a failure
# (for example an expired Garmin key) raises a macOS notification.
set -euo pipefail

LABEL="com.move2zero.nightly-sync"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
LOG="$HOME/Library/Logs/move2zero-sync.log"
REPO="$(cd "$(dirname "$0")/.." && pwd)"
DOMAIN="gui/$(id -u)"

case "${1:-install}" in
  --uninstall)
    launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
    rm -f "$PLIST"
    echo "Nightly sync removed."
    exit 0
    ;;
  --run-now)
    launchctl kickstart -k "$DOMAIN/$LABEL"
    echo "Started. Follow along with: tail -f $LOG"
    exit 0
    ;;
  install) ;;
  *)
    echo "Unknown option: $1" >&2
    exit 1
    ;;
esac

# Same interpreter the app uses, as an absolute path (launchd has a minimal PATH).
PYTHON="$(command -v python || command -v python3)"
mkdir -p "$HOME/Library/LaunchAgents" "$HOME/Library/Logs"

cat > "$PLIST" <<PLIST_EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>$PYTHON</string>
    <string>$REPO/run_sync.py</string>
    <string>--trigger</string>
    <string>nightly</string>
    <string>--notify</string>
  </array>
  <key>WorkingDirectory</key>
  <string>$REPO</string>
  <key>StartCalendarInterval</key>
  <dict>
    <key>Hour</key>
    <integer>0</integer>
    <key>Minute</key>
    <integer>0</integer>
  </dict>
  <key>StandardOutPath</key>
  <string>$LOG</string>
  <key>StandardErrorPath</key>
  <string>$LOG</string>
</dict>
</plist>
PLIST_EOF

plutil -lint "$PLIST" >/dev/null
launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
launchctl bootstrap "$DOMAIN" "$PLIST"
echo "Nightly sync installed: every night at 00:00."
echo "  python: $PYTHON"
echo "  repo:   $REPO"
echo "  log:    $LOG"
echo "Remove with: scripts/install_nightly_sync.sh --uninstall"
