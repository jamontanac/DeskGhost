#!/usr/bin/env bash
# =============================================================================
# setup.sh — Unified DeskGhost macOS setup/build/package tool
#
# Interactive mode (no args):
#   bash scripts/setup.sh
#
# Non-interactive actions:
#   bash scripts/setup.sh install-source
#   bash scripts/setup.sh install-packaged [binary-or-app-path]
#   bash scripts/setup.sh build
#   bash scripts/setup.sh package
#   bash scripts/setup.sh run-now-source
#   bash scripts/setup.sh run-now-packaged [binary-or-app-path]
#   bash scripts/setup.sh status
#   bash scripts/setup.sh logs
#   bash scripts/setup.sh clean
#   bash scripts/setup.sh uninstall
#   bash scripts/setup.sh grant-ax [auto|source|packaged] [binary-or-app-path]
#   bash scripts/setup.sh ax-status [auto|source|packaged] [binary-or-app-path]
#
# Backward-compatible aliases:
#   install  -> install-source
#   run-now  -> run-now-source
# =============================================================================

set -euo pipefail

# ── Constants ────────────────────────────────────────────────────────────────

LABEL="com.deskghost.agent"
PLIST_DST="$HOME/Library/LaunchAgents/${LABEL}.plist"
LOG_DIR="$HOME/.deskghost/logs"
STDOUT_LOG="${LOG_DIR}/stdout.log"
STDERR_LOG="${LOG_DIR}/stderr.log"

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BUILD_DIR="${PROJECT_ROOT}/build/macos"
RELEASE_DIR="${PROJECT_ROOT}/build/release/macos"
MEDIA_DIR="${PROJECT_ROOT}/media"

PROMPT_USER=0

# ── Helpers ───────────────────────────────────────────────────────────────────

green()  { printf '\033[32m%s\033[0m\n' "$*"; }
red()    { printf '\033[31m%s\033[0m\n' "$*"; }
yellow() { printf '\033[33m%s\033[0m\n' "$*"; }

require_cmd() {
    if ! command -v "$1" >/dev/null 2>&1; then
        red "Error: required command not found: $1"
        exit 1
    fi
}

require_uv() {
    if ! UV_PATH="$(command -v uv 2>/dev/null)"; then
        red "Error: 'uv' not found on PATH."
        red "Install it from https://docs.astral.sh/uv/getting-started/installation/"
        exit 1
    fi
}

assert_project_root() {
    if [[ ! -f "${PROJECT_ROOT}/pyproject.toml" ]]; then
        red "Error: pyproject.toml not found in ${PROJECT_ROOT}"
        red "Run this script from inside the deskghost repository."
        exit 1
    fi
    if [[ ! -f "${PROJECT_ROOT}/conf/config.yaml" ]]; then
        red "Error: conf/config.yaml not found in ${PROJECT_ROOT}"
        exit 1
    fi
}

ensure_macos() {
    if [[ "$(uname -s)" != "Darwin" ]]; then
        red "This script only supports macOS."
        exit 1
    fi
}

read_trigger_entries() {
    "$UV_PATH" run --project "$PROJECT_ROOT" python -c \
        "from deskghost.config import get_local_scheduler_trigger_entries; [print(f'{d} {h} {m}') for d, h, m in get_local_scheduler_trigger_entries()]"
}

read_trigger_entries_pretty() {
    "$UV_PATH" run --project "$PROJECT_ROOT" python -c \
        "from deskghost.config import get_local_scheduler_trigger_entries; days=('Mon','Tue','Wed','Thu','Fri','Sat','Sun'); [print(f'{days[d]} {h:02d}:{m:02d}') for d, h, m in get_local_scheduler_trigger_entries()]"
}

read_version() {
    require_uv
    local version
    version="$(
        cd "$PROJECT_ROOT" &&
        "$UV_PATH" run --project "$PROJECT_ROOT" python -c "import pathlib,tomllib; d=tomllib.loads(pathlib.Path('pyproject.toml').read_text(encoding='utf-8')); print(d.get('project',{}).get('version','0.0.0'))" 2>/dev/null || true
    )"
    if [[ -z "$version" ]]; then
        echo "0.0.0"
    else
        echo "$version"
    fi
}

agent_is_loaded() {
    launchctl list "$LABEL" &>/dev/null
}

read_plist_program_arg() {
    local index="$1"
    if [[ ! -f "$PLIST_DST" ]]; then
        return 0
    fi
    if [[ -x "/usr/libexec/PlistBuddy" ]]; then
        /usr/libexec/PlistBuddy -c "Print :ProgramArguments:${index}" "$PLIST_DST" 2>/dev/null || true
    fi
}

detect_installed_mode() {
    local arg0 arg1 arg2
    arg0="$(read_plist_program_arg 0)"
    arg1="$(read_plist_program_arg 1)"
    arg2="$(read_plist_program_arg 2)"

    if [[ -z "$arg0" ]]; then
        echo "unknown"
        return 0
    fi

    if [[ "$arg1" == "run" && "$arg2" == "deskghost" ]]; then
        echo "source"
        return 0
    fi

    echo "packaged"
}

remove_build_outputs() {
    local removed_any=false

    if [[ -d "$BUILD_DIR" ]]; then
        rm -rf "$BUILD_DIR"
        green "Deleted: ${BUILD_DIR}"
        removed_any=true
    fi

    if [[ -d "$RELEASE_DIR" ]]; then
        rm -rf "$RELEASE_DIR"
        green "Deleted: ${RELEASE_DIR}"
        removed_any=true
    fi

    if [[ "$removed_any" == false ]]; then
        yellow "No build artifacts found under ${PROJECT_ROOT}/build."
    fi
}

resolve_macos_app_icon() {
    local icon_icns="${MEDIA_DIR}/deskghost.icns"
    local icon_png="${MEDIA_DIR}/deskghost.png"
    local icon_jpg="${MEDIA_DIR}/deskghost.jpg"
    local icon_jpeg="${MEDIA_DIR}/deskghost.jpeg"

    if [[ -f "$icon_icns" ]]; then
        echo "$icon_icns"
        return 0
    fi

    local source_image=""
    if [[ -f "$icon_png" ]]; then
        source_image="$icon_png"
    elif [[ -f "$icon_jpg" ]]; then
        source_image="$icon_jpg"
    elif [[ -f "$icon_jpeg" ]]; then
        source_image="$icon_jpeg"
    fi

    if [[ -n "$source_image" ]]; then
        local converted_icns="${BUILD_DIR}/assets/deskghost.icns"
        local iconset_dir="${BUILD_DIR}/assets/deskghost.iconset"

        if command -v sips >/dev/null 2>&1 && command -v iconutil >/dev/null 2>&1; then
            mkdir -p "$(dirname "$converted_icns")"
            rm -rf "$iconset_dir"
            mkdir -p "$iconset_dir"

            local size doubled
            for size in 16 32 128 256 512; do
                doubled=$((size * 2))
                sips -z "$size" "$size" "$source_image" --out "${iconset_dir}/icon_${size}x${size}.png" >/dev/null
                sips -z "$doubled" "$doubled" "$source_image" --out "${iconset_dir}/icon_${size}x${size}@2x.png" >/dev/null
            done

            iconutil -c icns "$iconset_dir" -o "$converted_icns" >/dev/null
            if [[ -f "$converted_icns" ]]; then
                echo "$converted_icns"
                return 0
            fi
        fi

        yellow "Could not convert icon to icns automatically."
        yellow "Falling back to source image: ${source_image}"
        yellow "If Nuitka fails, install imageio or provide media/deskghost.icns."
        echo "$source_image"
        return 0
    fi

    echo ""
}

detect_app_bundle() {
    if [[ ! -d "$BUILD_DIR" ]]; then
        return 0
    fi

    if [[ -d "$BUILD_DIR/DeskGhost.app" ]]; then
        echo "$BUILD_DIR/DeskGhost.app"
        return 0
    fi

    if [[ -d "$BUILD_DIR/main.app" ]]; then
        echo "$BUILD_DIR/main.app"
        return 0
    fi

    find "$BUILD_DIR" -maxdepth 1 -type d -name '*.app' | head -n 1 || true
}

normalize_macos_bundle_name() {
    local app_path="$1"
    local target_path="$BUILD_DIR/DeskGhost.app"

    if [[ -z "$app_path" || ! -d "$app_path" ]]; then
        echo "$app_path"
        return 0
    fi

    if [[ "$app_path" == "$target_path" ]]; then
        echo "$app_path"
        return 0
    fi

    if [[ -d "$target_path" ]]; then
        rm -rf "$target_path"
    fi

    mv "$app_path" "$target_path"
    echo "$target_path"
}

find_packaged_binary() {
    local hint="${1:-}"
    local app_path=""

    if [[ -n "$hint" ]]; then
        if [[ -d "$hint" && "$hint" == *.app ]]; then
            app_path="$hint"
        elif [[ -f "$hint" ]]; then
            echo "$hint"
            return 0
        else
            return 0
        fi
    else
        app_path="$(detect_app_bundle)"
    fi

    if [[ -z "$app_path" ]]; then
        return 0
    fi

    if [[ -x "$app_path/Contents/MacOS/DeskGhost" ]]; then
        echo "$app_path/Contents/MacOS/DeskGhost"
        return 0
    fi

    find "$app_path/Contents/MacOS" -maxdepth 1 -type f | head -n 1 || true
}

resolve_packaged_binary() {
    local hint="${1:-}"
    local binary_path
    binary_path="$(find_packaged_binary "$hint")"

    if [[ -z "$binary_path" ]]; then
        red "No packaged binary found."
        yellow "Build first: bash scripts/setup.sh build"
        return 1
    fi

    if [[ ! -f "$binary_path" ]]; then
        red "Packaged binary path not found: $binary_path"
        return 1
    fi

    if [[ ! -x "$binary_path" ]]; then
        red "Packaged binary is not executable: $binary_path"
        return 1
    fi

    echo "$binary_path"
}

source_python_binary() {
    require_uv
    "$UV_PATH" run --project "$PROJECT_ROOT" python -c 'import os,sys; print(os.path.realpath(sys.executable))' 2>/dev/null || true
}

ax_status_source() {
    require_uv
    "$UV_PATH" run --project "$PROJECT_ROOT" python -m deskghost.main --ax-status >/dev/null 2>&1
}

ax_status_packaged() {
    local binary_path="$1"
    "$binary_path" --ax-status >/dev/null 2>&1
}

resolve_ax_mode() {
    local mode="${1:-auto}"
    local hint="${2:-}"

    case "$mode" in
        source|packaged)
            echo "$mode"
            ;;
        auto)
            if [[ -n "$hint" ]]; then
                echo "packaged"
            else
                local candidate
                candidate="$(find_packaged_binary "")"
                if [[ -n "$candidate" ]]; then
                    echo "packaged"
                else
                    echo "source"
                fi
            fi
            ;;
        *)
            red "Invalid AX mode: $mode"
            red "Use: auto | source | packaged"
            return 1
            ;;
    esac
}

cmd_ax_status() {
    local mode
    local mode_input="${1:-auto}"
    local hint="${2:-}"
    mode="$(resolve_ax_mode "$mode_input" "$hint")"

    if [[ "$mode" == "source" ]]; then
        if ax_status_source; then
            green "AX status (source): trusted"
            local py_bin
            py_bin="$(source_python_binary)"
            [[ -n "$py_bin" ]] && yellow "  runtime: $py_bin"
            return 0
        fi
        yellow "AX status (source): not-trusted"
        local py_bin
        py_bin="$(source_python_binary)"
        [[ -n "$py_bin" ]] && yellow "  runtime: $py_bin"
        return 1
    fi

    local binary_path
    binary_path="$(resolve_packaged_binary "$hint")"
    if ax_status_packaged "$binary_path"; then
        green "AX status (packaged): trusted"
        yellow "  runtime: $binary_path"
        return 0
    fi

    yellow "AX status (packaged): not-trusted"
    yellow "  runtime: $binary_path"
    return 1
}

cmd_grant_ax() {
    ensure_macos

    local mode
    local mode_input="${1:-auto}"
    local hint="${2:-}"
    mode="$(resolve_ax_mode "$mode_input" "$hint")"

    if [[ "$mode" == "source" ]]; then
        require_uv
        if ax_status_source; then
            green "Accessibility permission is already granted for source runtime."
            return 0
        fi

        yellow "Requesting Accessibility permission for source runtime..."
        "$UV_PATH" run --project "$PROJECT_ROOT" python -m deskghost.main --request-ax >/dev/null 2>&1 || true

        local py_bin
        py_bin="$(source_python_binary)"
        if [[ -n "$py_bin" ]]; then
            yellow "Runtime binary: $py_bin"
            if command -v pbcopy >/dev/null 2>&1; then
                echo -n "$py_bin" | pbcopy
                yellow "Runtime path copied to clipboard."
            fi
        fi

        if ax_status_source; then
            green "Accessibility permission granted for source runtime."
        else
            yellow "Accessibility still not granted for source runtime."
            yellow "Open: System Settings -> Privacy & Security -> Accessibility"
            yellow "Then allow the source runtime shown above."
            open "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility" >/dev/null 2>&1 || true
        fi
        return 0
    fi

    local binary_path
    binary_path="$(resolve_packaged_binary "$hint")"

    if ax_status_packaged "$binary_path"; then
        green "Accessibility permission is already granted for packaged runtime."
        yellow "  runtime: $binary_path"
        return 0
    fi

    yellow "Requesting Accessibility permission for packaged runtime..."
    if command -v pbcopy >/dev/null 2>&1; then
        echo -n "$binary_path" | pbcopy
        yellow "Packaged runtime path copied to clipboard."
    fi

    "$binary_path" --request-ax >/dev/null 2>&1 || true

    if ax_status_packaged "$binary_path"; then
        green "Accessibility permission granted for packaged runtime."
    else
        yellow "Accessibility still not granted for packaged runtime."
        yellow "Open: System Settings -> Privacy & Security -> Accessibility"
        yellow "If needed, add this runtime path:"
        yellow "  $binary_path"
        open "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility" >/dev/null 2>&1 || true
    fi
}

maybe_prompt_for_ax() {
    local mode="$1"
    local binary_path="${2:-}"

    if [[ "$mode" == "source" ]]; then
        if ax_status_source; then
            return 0
        fi
        yellow "Accessibility permission is missing for source runtime."
        if [[ "$PROMPT_USER" == "1" ]]; then
            printf "Request Accessibility permission now? [Y/n] "
            local reply
            read -r reply
            if [[ ! "$reply" =~ ^[Nn]$ ]]; then
                cmd_grant_ax source
            fi
        else
            yellow "Run: bash scripts/setup.sh grant-ax source"
        fi
        return 0
    fi

    if ax_status_packaged "$binary_path"; then
        return 0
    fi
    yellow "Accessibility permission is missing for packaged runtime."
    yellow "  runtime: $binary_path"
    if [[ "$PROMPT_USER" == "1" ]]; then
        printf "Request Accessibility permission now? [Y/n] "
        local reply
        read -r reply
        if [[ ! "$reply" =~ ^[Nn]$ ]]; then
            cmd_grant_ax packaged "$binary_path"
        fi
    else
        yellow "Run: bash scripts/setup.sh grant-ax packaged ${binary_path}"
    fi
}

write_plist() {
    local runtime_mode="$1"
    local binary_path="${2:-}"

    mkdir -p "$(dirname "$PLIST_DST")"
    mkdir -p "$LOG_DIR"

    local trigger_entries
    trigger_entries="$(read_trigger_entries)"
    if [[ -z "$trigger_entries" ]]; then
        red "Error: no enabled schedule days found in conf/config.yaml."
        red "Enable at least one weekday in schedule.work_days or schedule.day_overrides."
        exit 1
    fi

    local START_CALENDAR_XML=""
    local PY_DAY WORK_HOUR WORK_MINUTE WEEKDAY
    while IFS=' ' read -r PY_DAY WORK_HOUR WORK_MINUTE; do
        [[ -z "$PY_DAY" ]] && continue
        WEEKDAY=$((PY_DAY + 1))
        START_CALENDAR_XML+=$'\n        <dict><key>Weekday</key><integer>'"${WEEKDAY}"$'</integer><key>Hour</key><integer>'"${WORK_HOUR}"$'</integer><key>Minute</key><integer>'"${WORK_MINUTE}"$'</integer></dict>'
    done <<< "$trigger_entries"

    local PROGRAM_ARGS_XML
    if [[ "$runtime_mode" == "source" ]]; then
        PROGRAM_ARGS_XML="$(cat <<EOF
    <key>ProgramArguments</key>
    <array>
        <string>${UV_PATH}</string>
        <string>run</string>
        <string>deskghost</string>
    </array>
EOF
)"
    else
        PROGRAM_ARGS_XML="$(cat <<EOF
    <key>ProgramArguments</key>
    <array>
        <string>${binary_path}</string>
    </array>
EOF
)"
    fi

    cat > "$PLIST_DST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>${LABEL}</string>

${PROGRAM_ARGS_XML}

    <key>WorkingDirectory</key>
    <string>${PROJECT_ROOT}</string>

    <key>RunAtLoad</key>
    <true/>

    <key>StartCalendarInterval</key>
    <array>${START_CALENDAR_XML}
    </array>

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

print_install_summary() {
    local mode="$1"
    local runtime_target="${2:-}"

    green "LaunchAgent installed."
    green "  mode      : ${mode}"
    green "  plist     : ${PLIST_DST}"
    green "  project   : ${PROJECT_ROOT}"
    green "  logs      : ${LOG_DIR}"
    if [[ "$mode" == "source" ]]; then
        green "  uv        : ${UV_PATH}"
    else
        green "  runtime   : ${runtime_target}"
    fi
    green "DeskGhost will start at login and configured schedule start times (local clock)."
    yellow "Configured local triggers:"
    while IFS= read -r line; do
        yellow "  ${line}"
    done <<< "$(read_trigger_entries_pretty)"
}

# ── Commands ──────────────────────────────────────────────────────────────────

cmd_build() {
    ensure_macos
    require_uv
    assert_project_root

    mkdir -p "$BUILD_DIR"

    local icon_path
    local icon_arg
    icon_path="$(resolve_macos_app_icon)"
    if [[ -n "$icon_path" ]]; then
        icon_arg="--macos-app-icon=${icon_path}"
        yellow "Using macOS app icon: ${icon_path}"
    else
        icon_arg="--macos-app-icon=none"
        yellow "No icon found at media/deskghost.(icns|png|jpg|jpeg); building without custom app icon."
    fi

    yellow "Syncing dependencies..."
    "$UV_PATH" sync --project "$PROJECT_ROOT"

    yellow "Building macOS app bundle with Nuitka..."
    (
        cd "$PROJECT_ROOT"
        "$UV_PATH" run --project "$PROJECT_ROOT" --with nuitka python -m nuitka \
            --standalone \
            --macos-create-app-bundle \
            "$icon_arg" \
            --output-dir="$BUILD_DIR" \
            --output-filename=DeskGhost \
            --product-name="DeskGhost" \
            --include-package=deskghost \
            --include-data-files=conf/config.yaml=conf/config.yaml \
            src/deskghost/main.py
    )

    local app_path dist_path app_exe
    app_path="$(detect_app_bundle)"
    dist_path="$(find "$BUILD_DIR" -maxdepth 1 -type d -name '*.dist' | head -n 1 || true)"

    if [[ -z "$app_path" ]]; then
        red "Build finished but no .app bundle was found under ${BUILD_DIR}."
        exit 1
    fi

    app_path="$(normalize_macos_bundle_name "$app_path")"

    if [[ -x "$app_path/Contents/MacOS/DeskGhost" ]]; then
        app_exe="$app_path/Contents/MacOS/DeskGhost"
    else
        app_exe="$(find "$app_path/Contents/MacOS" -maxdepth 1 -type f ! -name '*.so' ! -name '*.dylib' | head -n 1 || true)"
    fi

    green "Build complete."
    yellow "Outputs:"
    yellow "  ${app_path}"
    [[ -n "$dist_path" ]] && yellow "  ${dist_path}"
    echo ""
    yellow "Smoke test command:"
    if [[ -n "$app_exe" ]]; then
        yellow "  ${app_exe}"
    else
        yellow "  open ${app_path}"
    fi
}

cmd_package() {
    ensure_macos
    require_cmd ditto
    assert_project_root

    local app_path
    app_path="$(detect_app_bundle)"
    if [[ -z "$app_path" ]]; then
        red "No .app bundle found under ${BUILD_DIR}."
        yellow "Build first: bash scripts/setup.sh build"
        exit 1
    fi

    local version artifact zip_path
    version="$(read_version)"
    mkdir -p "$RELEASE_DIR"
    artifact="DeskGhost-macos-v${version}.zip"
    zip_path="${RELEASE_DIR}/${artifact}"

    rm -f "$zip_path"
    ditto -c -k --sequesterRsrc --keepParent "$app_path" "$zip_path"

    green "Packaging complete."
    yellow "App bundle : ${app_path}"
    yellow "Artifact   : ${zip_path}"
}

cmd_install_source() {
    ensure_macos
    require_uv
    assert_project_root

    if agent_is_loaded; then
        yellow "Existing agent found — reloading..."
        launchctl bootout "gui/$(id -u)" "$PLIST_DST" 2>/dev/null || true
    fi

    write_plist "source"
    launchctl bootstrap "gui/$(id -u)" "$PLIST_DST"

    print_install_summary "source"
    maybe_prompt_for_ax "source"
    yellow "To test right now run: bash scripts/setup.sh run-now-source"
}

cmd_install_packaged() {
    ensure_macos
    require_uv
    assert_project_root

    local binary_path
    binary_path="$(resolve_packaged_binary "${1:-}")"

    if agent_is_loaded; then
        yellow "Existing agent found — reloading..."
        launchctl bootout "gui/$(id -u)" "$PLIST_DST" 2>/dev/null || true
    fi

    write_plist "packaged" "$binary_path"
    launchctl bootstrap "gui/$(id -u)" "$PLIST_DST"

    print_install_summary "packaged" "$binary_path"
    maybe_prompt_for_ax "packaged" "$binary_path"
    yellow "To test right now run: bash scripts/setup.sh run-now-packaged"
}

cmd_uninstall() {
    local installed_mode="unknown"
    if [[ -f "$PLIST_DST" ]]; then
        installed_mode="$(detect_installed_mode)"
    fi

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

    if [[ "$installed_mode" == "packaged" ]]; then
        yellow "Packaged install detected. Removing build artifacts..."
        remove_build_outputs
    fi
}

cmd_run_now_source() {
    require_uv
    assert_project_root
    maybe_prompt_for_ax "source"
    green "Starting DeskGhost now in source mode (Ctrl+C to stop)..."
    cd "$PROJECT_ROOT"
    exec "$UV_PATH" run deskghost
}

cmd_run_now_packaged() {
    local binary_path
    binary_path="$(resolve_packaged_binary "${1:-}")"
    maybe_prompt_for_ax "packaged" "$binary_path"
    green "Starting DeskGhost now in packaged mode (Ctrl+C to stop)..."
    exec "$binary_path"
}

cmd_status() {
    if agent_is_loaded; then
        green "Agent IS loaded:"
        launchctl list "$LABEL"
    else
        red "Agent is NOT loaded."
        yellow "Run: bash scripts/setup.sh install-source"
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

    local actions=()
    local has_work=false

    if [[ "$pid_alive" == true ]]; then
        actions+=("  [kill]   PID ${pid} (deskghost process)")
        has_work=true
    fi

    for f in "$LOG_FILE" "$LOG_FILE_1" "$STDOUT_LOG" "$STDERR_LOG"; do
        if [[ -f "$f" ]]; then
            local size
            size="$(du -sh "$f" 2>/dev/null | cut -f1)"
            actions+=("  [delete] ${f}  (${size})")
            has_work=true
        fi
    done

    for d in "$BUILD_DIR" "$RELEASE_DIR"; do
        if [[ -d "$d" ]]; then
            local size
            size="$(du -sh "$d" 2>/dev/null | cut -f1)"
            actions+=("  [delete] ${d}  (${size})")
            has_work=true
        fi
    done

    if [[ -f "$LOCK_FILE" ]]; then
        if [[ "$pid_alive" == false ]]; then
            rm -f "$LOCK_FILE"
        else
            actions+=("  [delete] ${LOCK_FILE}")
        fi
    fi

    if [[ "$has_work" == false ]]; then
        green "Nothing to clean."
        return 0
    fi

    yellow "The following actions will be taken:"
    for action in "${actions[@]}"; do
        yellow "$action"
    done
    echo ""
    printf "Proceed? [y/N] "
    local reply
    read -r reply
    echo ""

    if [[ ! "$reply" =~ ^[Yy]$ ]]; then
        yellow "Aborted. Nothing was changed."
        return 0
    fi

    if [[ "$pid_alive" == true ]]; then
        kill -TERM "$pid" 2>/dev/null || true
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

    for f in "$LOG_FILE" "$LOG_FILE_1" "$STDOUT_LOG" "$STDERR_LOG"; do
        if [[ -f "$f" ]]; then
            rm -f "$f"
            green "Deleted: ${f}"
        fi
    done

    for d in "$BUILD_DIR" "$RELEASE_DIR"; do
        if [[ -d "$d" ]]; then
            rm -rf "$d"
            green "Deleted: ${d}"
        fi
    done
}

show_usage() {
    cat <<'USAGE'
Usage: bash scripts/setup.sh [action] [args]

Actions:
  install / install-source
  install-packaged [binary-or-app-path]
  build
  package
  run-now / run-now-source
  run-now-packaged [binary-or-app-path]
  grant-ax [auto|source|packaged] [binary-or-app-path]
  ax-status [auto|source|packaged] [binary-or-app-path]
  status
  logs
  clean
  uninstall
  help

No args starts interactive mode.
USAGE
}

interactive_menu() {
    PROMPT_USER=1

    while true; do
        echo ""
        yellow "DeskGhost macOS setup"
        echo "  1) Install agent (source mode: uv run deskghost)"
        echo "  2) Build app (Nuitka)"
        echo "  3) Package built app (.zip)"
        echo "  4) Install agent (packaged mode)"
        echo "  5) Request Accessibility permission (source mode)"
        echo "  6) Request Accessibility permission (packaged mode)"
        echo "  7) Run now (source mode)"
        echo "  8) Run now (packaged mode)"
        echo "  9) Status"
        echo " 10) Logs"
        echo " 11) Clean"
        echo " 12) Uninstall"
        echo "  0) Exit"
        printf "Choose an option [0-12]: "

        local choice
        read -r choice

        case "$choice" in
            1) cmd_install_source ;;
            2) cmd_build ;;
            3) cmd_package ;;
            4)
                printf "Binary/App path (leave empty to auto-detect): "
                local path
                read -r path
                cmd_install_packaged "$path"
                ;;
            5) cmd_grant_ax source ;;
            6)
                printf "Binary/App path (leave empty to auto-detect): "
                local path
                read -r path
                cmd_grant_ax packaged "$path"
                ;;
            7) cmd_run_now_source ;;
            8)
                printf "Binary/App path (leave empty to auto-detect): "
                local path
                read -r path
                cmd_run_now_packaged "$path"
                ;;
            9) cmd_status ;;
            10) cmd_logs ;;
            11) cmd_clean ;;
            12) cmd_uninstall ;;
            0) break ;;
            *) red "Invalid option. Choose 0-12." ;;
        esac
    done
}

# ── Dispatch ──────────────────────────────────────────────────────────────────

action="${1:-}"

if [[ -z "$action" ]]; then
    interactive_menu
    exit 0
fi

if [[ "$action" == "help" || "$action" == "-h" || "$action" == "--help" ]]; then
    show_usage
    exit 0
fi

case "$action" in
    install|install-source)
        cmd_install_source
        ;;
    install-packaged)
        cmd_install_packaged "${2:-}"
        ;;
    build)
        cmd_build
        ;;
    package)
        cmd_package
        ;;
    run-now|run-now-source)
        cmd_run_now_source
        ;;
    run-now-packaged)
        cmd_run_now_packaged "${2:-}"
        ;;
    grant-ax)
        cmd_grant_ax "${2:-auto}" "${3:-}"
        ;;
    ax-status)
        cmd_ax_status "${2:-auto}" "${3:-}"
        ;;
    status)
        cmd_status
        ;;
    logs)
        cmd_logs
        ;;
    clean)
        cmd_clean
        ;;
    uninstall)
        cmd_uninstall
        ;;
    *)
        red "Unknown action: $action"
        show_usage
        exit 1
        ;;
esac
