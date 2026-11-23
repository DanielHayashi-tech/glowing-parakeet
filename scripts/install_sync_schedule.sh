#!/bin/bash
# Install (or remove) the automatic Garmin sync as a macOS launchd agent.
#
#   scripts/install_sync_schedule.sh              install: every hour, at login, and on wake
#   scripts/install_sync_schedule.sh --run-now    trigger one run immediately
#   scripts/install_sync_schedule.sh --uninstall  remove it
#
# The schedule is a calendar interval (every hour at :00). Per launchd.plist(5), unlike cron
# launchd runs a missed calendar job the next time the Mac wakes, coalescing the missed hours
# into one run. (A plain StartInterval would be skipped while asleep, so it is not used.)
# Output goes to ~/Library/Logs/move2zero-sync.log. A macOS notification appears on failure,
# when new activities arrive, or when the Garmin key is about to expire; otherwise it is quiet.
set -euo pipefail

LABEL="com.move2zero.sync"
OLD_LABEL="com.move2zero.nightly-sync"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
OLD_PLIST="$HOME/Library/LaunchAgents/$OLD_LABEL.plist"
LOG="$HOME/Library/Logs/move2zero-sync.log"
REPO="$(cd "$(dirname "$0")/.." && pwd)"
DOMAIN="gui/$(id -u)"

case "${1:-install}" in
  --uninstall)
    launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
    launchctl bootout "$DOMAIN/$OLD_LABEL" 2>/dev/null || true
    rm -f "$PLIST" "$OLD_PLIST"
    echo "Automatic sync removed."
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
    <string>scheduled</string>
    <string>--notify</string>
  </array>
  <key>WorkingDirectory</key>
  <string>$REPO</string>
  <key>RunAtLoad</key>
  <true/>
  <key>StartCalendarInterval</key>
  <dict>
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
# Replace the earlier nightly agent, if present.
launchctl bootout "$DOMAIN/$OLD_LABEL" 2>/dev/null || true
rm -f "$OLD_PLIST"
launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
launchctl bootstrap "$DOMAIN" "$PLIST"
echo "Automatic sync installed: every hour, at login, and when the Mac wakes."
echo "  python: $PYTHON"
echo "  repo:   $REPO"
echo "  log:    $LOG"
echo "Remove with: scripts/install_sync_schedule.sh --uninstall"
