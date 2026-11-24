#!/bin/bash
# Run the OpenAI Secure MCP Tunnel as a macOS launchd user agent: it starts at login and is restarted if it exits.
#
#   scripts/install_tunnel_agent.sh              install and start
#   scripts/install_tunnel_agent.sh --status     is it running and ready?
#   scripts/install_tunnel_agent.sh --uninstall  stop and remove it
#
# Reuses the existing tunnel profile (~/.config/tunnel-client/corre-cortes.yaml), which points at the restricted
# key file next to it. No credential is read, copied or printed here, and none is written to the plist or the log.
# The profile's fixed health port (127.0.0.1:8080) also stops a second tunnel from starting by hand.
# Output goes to ~/Library/Logs/corre-cortes-tunnel.log.
set -euo pipefail

LABEL="com.move2zero.tunnel"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
LOG="$HOME/Library/Logs/corre-cortes-tunnel.log"
PROFILE_DIR="$HOME/.config/tunnel-client"
PROFILE="corre-cortes"
DOMAIN="gui/$(id -u)"

case "${1:-install}" in
  --uninstall)
    launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
    rm -f "$PLIST"
    echo "Tunnel agent removed."
    exit 0
    ;;
  --status)
    if launchctl print "$DOMAIN/$LABEL" >/dev/null 2>&1; then
      echo "agent:    loaded ($(launchctl print "$DOMAIN/$LABEL" | awk '/^\tstate =/{print $3}'))"
    else
      echo "agent:    not installed"
    fi
    echo "process:  $(pgrep -f "tunnel-client run --profile $PROFILE" | wc -l | tr -d ' ') running"
    echo "ready:    $(curl -s -m 3 http://127.0.0.1:8080/readyz || echo 'no answer')"
    exit 0
    ;;
  install) ;;
  *) echo "Unknown option: $1" >&2; exit 1 ;;
esac

BIN="$(command -v tunnel-client)"
[ -f "$PROFILE_DIR/$PROFILE.yaml" ] || { echo "Missing $PROFILE_DIR/$PROFILE.yaml" >&2; exit 1; }
mkdir -p "$HOME/Library/LaunchAgents" "$HOME/Library/Logs"
touch "$LOG" && chmod 600 "$LOG"

cat > "$PLIST" <<PLIST_EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>$BIN</string>
    <string>run</string>
    <string>--profile</string>
    <string>$PROFILE</string>
    <string>--profile-dir</string>
    <string>$PROFILE_DIR</string>
  </array>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
  <key>ThrottleInterval</key>
  <integer>10</integer>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key>
    <string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string>
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
# Only one tunnel may run: stop any copy started by hand before launchd starts its own.
pkill -f "tunnel-client run --profile $PROFILE" 2>/dev/null || true
sleep 2
launchctl bootstrap "$DOMAIN" "$PLIST"
echo "Tunnel agent installed: starts at login, restarts if it stops."
echo "Check it with: scripts/install_tunnel_agent.sh --status"
echo "Log: $LOG"
