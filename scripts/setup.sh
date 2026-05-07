#!/usr/bin/env bash
# =============================================================================
# setup.sh — DeskGhost macOS installer
#
# Registers a launchd LaunchAgent that starts DeskGhost at 07:00 Mon–Fri.
# The script self-exits when outside work hours, so launchd only needs to
# kick it off once per day.
#
# Usage:
#   bash scripts/setup.sh install    # register the LaunchAgent
#   bash scripts/setup.sh uninstall  # remove the LaunchAgent
#   bash scripts/setup.sh run-now    # run DeskGhost immediately (for testing)
#   bash scripts/setup.sh status     # check whether the agent is loaded
#   bash scripts/setup.sh logs       # tail the log files
# =============================================================================

set -euo pipefail

# ── Constants ────────────────────────────────────────────────────────────────

LABEL="com.deskghost.agent"
PLIST_DST="$HOME/Library/LaunchAgents/${LABEL}.plist"
LOG_DIR="$HOME/.deskghost/logs"
STDOUT_LOG="${LOG_DIR}/stdout.log"
STDERR_LOG="${LOG_DIR}/stderr.log"

# Project root is the directory that contains this script
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# ── Helpers ───────────────────────────────────────────────────────────────────

green()  { printf '\033[32m%s\033[0m\n' "$*"; }
red()    { printf '\033[31m%s\033[0m\n' "$*"; }
yellow() { printf '\033[33m%s\033[0m\n' "$*"; }

require_uv() {
    if ! UV_PATH="$(command -v uv 2>/dev/null)"; then
        red "Error: 'uv' not found on PATH."
        red "Install it from https://docs.astral.sh/uv/getting-started/installation/"
        exit 1
    fi
}

read_work_start() {
    # Read WORK_START_TIME from conf/config.yaml via Python so we have a single
    # source of truth.  Outputs two space-separated integers: "<hour> <minute>".
    "$UV_PATH" run --project "$PROJECT_ROOT" python -c \
        "from deskghost.config import WORK_START_TIME; print(WORK_START_TIME[0], WORK_START_TIME[1])"
}

write_plist() {
    mkdir -p "$(dirname "$PLIST_DST")"
    mkdir -p "$LOG_DIR"

    # Read trigger time from config (single source of truth: conf/config.yaml)
    local work_start
    work_start="$(read_work_start)"
    local WORK_HOUR WORK_MINUTE
    WORK_HOUR="$(echo "$work_start"  | cut -d' ' -f1)"
    WORK_MINUTE="$(echo "$work_start" | cut -d' ' -f2)"

    cat > "$PLIST_DST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>${LABEL}</string>

    <key>ProgramArguments</key>
    <array>
        <string>${UV_PATH}</string>
        <string>run</string>
        <string>deskghost</string>
    </array>

    <key>WorkingDirectory</key>
    <string>${PROJECT_ROOT}</string>

    <!-- Fire at work_start time (read from conf/config.yaml) on every weekday -->
    <key>StartCalendarInterval</key>
    <array>
        <dict><key>Weekday</key><integer>1</integer><key>Hour</key><integer>${WORK_HOUR}</integer><key>Minute</key><integer>${WORK_MINUTE}</integer></dict>
        <dict><key>Weekday</key><integer>2</integer><key>Hour</key><integer>${WORK_HOUR}</integer><key>Minute</key><integer>${WORK_MINUTE}</integer></dict>
        <dict><key>Weekday</key><integer>3</integer><key>Hour</key><integer>${WORK_HOUR}</integer><key>Minute</key><integer>${WORK_MINUTE}</integer></dict>
        <dict><key>Weekday</key><integer>4</integer><key>Hour</key><integer>${WORK_HOUR}</integer><key>Minute</key><integer>${WORK_MINUTE}</integer></dict>
        <dict><key>Weekday</key><integer>5</integer><key>Hour</key><integer>${WORK_HOUR}</integer><key>Minute</key><integer>${WORK_MINUTE}</integer></dict>
    </array>

    <!-- Do not restart automatically — the script self-exits after work hours -->
    <key>KeepAlive</key>
    <false/>

    <key>StandardOutPath</key>
    <string>${STDOUT_LOG}</string>

    <key>StandardErrorPath</key>
    <string>${STDERR_LOG}</string>
</dict>
</plist>
PLIST
}

agent_is_loaded() {
    launchctl list 2>/dev/null | grep -q "$LABEL"
}

# ── Commands ──────────────────────────────────────────────────────────────────

cmd_install() {
    require_uv

    # Verify the project looks sane before installing
    if [[ ! -f "${PROJECT_ROOT}/pyproject.toml" ]]; then
        red "Error: pyproject.toml not found in ${PROJECT_ROOT}"
        red "Run this script from inside the deskghost repository."
        exit 1
    fi

    # Unload stale agent if present
    if agent_is_loaded; then
        yellow "Existing agent found — reloading..."
        launchctl unload "$PLIST_DST" 2>/dev/null || true
    fi

    write_plist
    launchctl load "$PLIST_DST"

    green "LaunchAgent installed."
    green "  plist     : ${PLIST_DST}"
    green "  uv        : ${UV_PATH}"
    green "  project   : ${PROJECT_ROOT}"
    green "  logs      : ${LOG_DIR}"
    green "DeskGhost will start automatically at $(read_work_start | awk '{printf "%02d:%02d", $1, $2}') Mon–Fri."
    yellow "To test right now run:  bash scripts/setup.sh run-now"
}

cmd_uninstall() {
    if agent_is_loaded; then
        launchctl unload "$PLIST_DST"
        green "LaunchAgent unloaded."
    else
        yellow "Agent was not loaded."
    fi

    if [[ -f "$PLIST_DST" ]]; then
        rm -f "$PLIST_DST"
        green "Plist removed: ${PLIST_DST}"
    else
        yellow "Plist not found (already removed?)."
    fi
}

cmd_run_now() {
    require_uv
    green "Starting DeskGhost now (Ctrl+C to stop)..."
    cd "$PROJECT_ROOT"
    exec "$UV_PATH" run deskghost
}

cmd_status() {
    if agent_is_loaded; then
        green "Agent IS loaded:"
        launchctl list | grep "$LABEL"
    else
        red "Agent is NOT loaded."
        yellow "Run:  bash scripts/setup.sh install"
    fi
}

cmd_logs() {
    echo "── stdout (${STDOUT_LOG}) ─────────────────────────────"
    if [[ -f "$STDOUT_LOG" ]]; then
        tail -40 "$STDOUT_LOG"
    else
        yellow "(no stdout log yet)"
    fi
    echo ""
    echo "── stderr (${STDERR_LOG}) ─────────────────────────────"
    if [[ -f "$STDERR_LOG" ]]; then
        tail -20 "$STDERR_LOG"
    else
        yellow "(no stderr log yet)"
    fi
}

# ── Dispatch ──────────────────────────────────────────────────────────────────

case "${1:-}" in
    install)   cmd_install   ;;
    uninstall) cmd_uninstall ;;
    run-now)   cmd_run_now   ;;
    status)    cmd_status    ;;
    logs)      cmd_logs      ;;
    *)
        echo "Usage: bash scripts/setup.sh [install|uninstall|run-now|status|logs]"
        exit 1
        ;;
esac
