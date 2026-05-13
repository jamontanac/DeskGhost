#!/usr/bin/env bash
# =============================================================================
# setup.sh — DeskGhost macOS installer
#
# Registers a launchd LaunchAgent that starts DeskGhost:
#   • immediately on login/session start (RunAtLoad), AND
#   • at the configured work-start time Mon–Fri (StartCalendarInterval).
#
# DeskGhost self-exits when outside work hours, so a login-time launch
# outside working hours is harmless.  A PID lock inside the app prevents
# double-launch when both triggers fire for the same session (e.g. the
# machine wakes from sleep with DeskGhost already running and the scheduler
# fires the missed trigger).
#
# Usage:
#   bash scripts/setup.sh install    # register the LaunchAgent
#   bash scripts/setup.sh uninstall  # remove the LaunchAgent
#   bash scripts/setup.sh run-now    # run DeskGhost immediately (for testing)
#   bash scripts/setup.sh status     # check whether the agent is loaded
#   bash scripts/setup.sh logs       # tail the log files
#   bash scripts/setup.sh clean      # stop running instance, delete logs and lock file
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

    <!-- Run immediately when the agent is loaded (login / session start) -->
    <key>RunAtLoad</key>
    <true/>

    <!-- Also fire at work_start time (read from conf/config.yaml) on every weekday -->
    <key>StartCalendarInterval</key>
    <array>
        <dict><key>Weekday</key><integer>1</integer><key>Hour</key><integer>${WORK_HOUR}</integer><key>Minute</key><integer>${WORK_MINUTE}</integer></dict>
        <dict><key>Weekday</key><integer>2</integer><key>Hour</key><integer>${WORK_HOUR}</integer><key>Minute</key><integer>${WORK_MINUTE}</integer></dict>
        <dict><key>Weekday</key><integer>3</integer><key>Hour</key><integer>${WORK_HOUR}</integer><key>Minute</key><integer>${WORK_MINUTE}</integer></dict>
        <dict><key>Weekday</key><integer>4</integer><key>Hour</key><integer>${WORK_HOUR}</integer><key>Minute</key><integer>${WORK_MINUTE}</integer></dict>
        <dict><key>Weekday</key><integer>5</integer><key>Hour</key><integer>${WORK_HOUR}</integer><key>Minute</key><integer>${WORK_MINUTE}</integer></dict>
    </array>

    <!-- Do not restart automatically — the app self-exits after work hours -->
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
    launchctl list "$LABEL" &>/dev/null
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
        launchctl bootout "gui/$(id -u)" "$PLIST_DST" 2>/dev/null || true
    fi

    write_plist
    launchctl bootstrap "gui/$(id -u)" "$PLIST_DST"

    # Resolve the Python interpreter the venv will actually use so we can
    # show the user exactly which binary to add to Accessibility.
    local PY_BIN
    PY_BIN="$("$UV_PATH" run --no-env-file python -c 'import sys; print(sys.executable)' 2>/dev/null || echo "(unknown — run: uv run python -c 'import sys; print(sys.executable)')")"

    green "LaunchAgent installed."
    green "  plist     : ${PLIST_DST}"
    green "  uv        : ${UV_PATH}"
    green "  project   : ${PROJECT_ROOT}"
    green "  logs      : ${LOG_DIR}"
    green "DeskGhost will start automatically at $(read_work_start | awk '{printf "%02d:%02d", $1, $2}') Mon–Fri."
    echo ""
    yellow "────────────────────────────────────────────────────────"
    yellow "  ACTION REQUIRED — Accessibility permission"
    yellow "  DeskGhost requires macOS Accessibility permission so that"
    yellow "  CGEventPost can inject HID events to reset the idle timer."
    yellow "  Without it, Teams (and similar apps) will still go idle."
    yellow ""
    yellow "  1. Open:  System Settings → Privacy & Security → Accessibility"
    yellow "  2. Click the lock to make changes, then click  +"
    yellow "  3. Add this binary:"
    yellow "       ${PY_BIN}"
    yellow "  4. Re-run:  bash scripts/setup.sh uninstall && bash scripts/setup.sh install"
    yellow "────────────────────────────────────────────────────────"
    echo ""
    yellow "To test right now run:  bash scripts/setup.sh run-now"
}

cmd_uninstall() {
    if agent_is_loaded; then
        launchctl bootout "gui/$(id -u)" "$PLIST_DST"
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
        launchctl list "$LABEL"
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

cmd_clean() {
    local LOCK_FILE="$HOME/.deskghost/deskghost.lock"
    local LOG_FILE="${LOG_DIR}/deskghost.log"
    local LOG_FILE_1="${LOG_DIR}/deskghost.log.1"

    # ── Discover what exists ───────────────────────────────────────────────────

    local pid=""
    local pid_alive=false

    if [[ -f "$LOCK_FILE" ]]; then
        local raw
        raw="$(cat "$LOCK_FILE" 2>/dev/null || true)"
        if [[ "$raw" =~ ^[0-9]+$ ]]; then
            pid="$raw"
            if kill -0 "$pid" 2>/dev/null; then
                pid_alive=true
            fi
        fi
    fi

    # Build the list of actions to display
    local actions=()
    local has_work=false

    if [[ "$pid_alive" == true ]]; then
        actions+=("  [kill]   PID ${pid} (deskghost process)")
        has_work=true
    fi

    for f in "$LOG_FILE" "$LOG_FILE_1"; do
        if [[ -f "$f" ]]; then
            local size
            size="$(du -sh "$f" 2>/dev/null | cut -f1)"
            actions+=("  [delete] ${f}  (${size})")
            has_work=true
        fi
    done

    if [[ -f "$LOCK_FILE" ]]; then
        if [[ "$pid_alive" == false ]]; then
            # Stale or unreadable PID — delete silently without prompting
            rm -f "$LOCK_FILE"
        else
            actions+=("  [delete] ${LOCK_FILE}")
        fi
    fi

    # ── Nothing to do ─────────────────────────────────────────────────────────

    if [[ "$has_work" == false ]]; then
        green "Nothing to clean."
        return 0
    fi

    # ── Show summary and prompt ────────────────────────────────────────────────

    yellow "The following actions will be taken:"
    for action in "${actions[@]}"; do
        yellow "$action"
    done
    echo ""
    printf "Proceed? [y/N] "
    read -r reply
    echo ""

    if [[ ! "$reply" =~ ^[Yy]$ ]]; then
        yellow "Aborted. Nothing was changed."
        return 0
    fi

    # ── Execute ───────────────────────────────────────────────────────────────

    if [[ "$pid_alive" == true ]]; then
        kill -TERM "$pid" 2>/dev/null || true
        # Wait up to 3 seconds for graceful exit, then SIGKILL
        local waited=0
        while kill -0 "$pid" 2>/dev/null && (( waited < 3 )); do
            sleep 1
            (( waited++ )) || true
        done
        if kill -0 "$pid" 2>/dev/null; then
            kill -KILL "$pid" 2>/dev/null || true
            green "PID ${pid} force-killed (SIGKILL)."
        else
            green "PID ${pid} stopped."
        fi
        rm -f "$LOCK_FILE"
    fi

    for f in "$LOG_FILE" "$LOG_FILE_1"; do
        if [[ -f "$f" ]]; then
            rm -f "$f"
            green "Deleted: ${f}"
        fi
    done
}

# ── Dispatch ──────────────────────────────────────────────────────────────────

case "${1:-}" in
    install)   cmd_install   ;;
    uninstall) cmd_uninstall ;;
    run-now)   cmd_run_now   ;;
    status)    cmd_status    ;;
    logs)      cmd_logs      ;;
    clean)     cmd_clean     ;;
    *)
        echo "Usage: bash scripts/setup.sh [install|uninstall|run-now|status|logs|clean]"
        exit 1
        ;;
esac
