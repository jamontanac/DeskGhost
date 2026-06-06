# DeskGhost

Silently keeps your presence alive on Teams (and similar apps) by injecting
a zero-movement input event whenever you go idle. Runs only during configured
work hours and self-exits when the day is over.

Supports **macOS** and **Windows**. A single command runs the right code for
your platform automatically.

---

## How it works

DeskGhost watches the OS-level idle timer — the same counter Teams reads to
decide whether to show you as Away. When you have been idle long enough it
posts a synthetic input event that resets the timer, keeping Teams green.

| Platform | Idle detection | Nudge mechanism |
| --- | --- | --- |
| macOS | `CGEventSourceSecondsSinceLastEventType` (Quartz) | `CGEventCreateMouseEvent(kCGEventMouseMoved)` posted to `kCGHIDEventTap` — cursor does not move |
| Windows | `GetLastInputInfo` (user32) | `SendInput` with `MOUSEEVENTF_MOVE` dx=0 dy=0 — cursor does not move |

On both platforms the cursor **never moves visibly**. No keystrokes are
injected. The events go directly into the HID input stream, which is what the
OS idle timer and Teams both observe.

During lunch, DeskGhost pauses input simulation but keeps the display awake
(macOS: `caffeinate -d`; Windows: `SetThreadExecutionState`) so the screen
does not lock while you are away from your desk.

---

## Requirements

| Requirement | Notes |
| --- | --- |
| Python 3.13+ | Pinned in `.python-version` |
| [uv](https://docs.astral.sh/uv/) | Package manager — replaces pip/poetry |
| macOS 12+ or Windows 10/11 | Other platforms are not supported |

Install `uv` if you don't have it:

```bash
# macOS / Linux
curl -LsSf https://astral.sh/uv/install.sh | sh

# Windows (PowerShell)
irm https://astral.sh/uv/install.ps1 | iex
```

## Build icon/logo formats (Nuitka)

Nuitka accepts these icon formats:

- macOS app bundle (`--macos-app-icon`): `.png` or `.icns`
- Windows executable (`--windows-icon-from-ico`): `.ico` or `.png`

The setup scripts look for logo files in `media/` using these names:

- `media/deskghost.icns` (macOS preferred)
- `media/deskghost.png` (works for both macOS and Windows builds)
- `media/deskghost.jpg` or `media/deskghost.jpeg`

On macOS, if the icon is PNG/JPG/JPEG, the build script auto-converts it to ICNS
before invoking Nuitka, which avoids requiring Python `imageio` just for icon conversion.

If you currently only have `media/deskghost.jpg` and want Windows icon embedding too,
create a PNG copy:

```bash
sips -s format png media/deskghost.jpg --out media/deskghost.png
```

## Troubleshooting and Restricted Environments

### Quick decision tree

1. Install and startup registration both work:
Use installed mode (`install-source` or `install-packaged`).

2. Install works but startup registration is blocked:
Use manual run mode and start DeskGhost when needed.

3. Install is blocked:
Use packaged portable zip (if available) or source/manual mode.

4. Python/uv is blocked:
Use packaged runtime (if approved by policy) or request IT exception.

### macOS common issues

1. Accessibility not granted

- Symptoms: logs show accessibility warnings and Teams still goes idle.
- Fix:
  - `bash scripts/setup.sh grant-ax source`
  - or `bash scripts/setup.sh grant-ax packaged`
  - then reinstall startup for your mode:
    - source: `bash scripts/setup.sh uninstall && bash scripts/setup.sh install-source`
    - packaged: `bash scripts/setup.sh uninstall && bash scripts/setup.sh install-packaged`

1. LaunchAgent installed but not active

- Check:
  - `bash scripts/setup.sh status`
  - `bash scripts/setup.sh logs`
  - verify plist exists at `~/Library/LaunchAgents/com.deskghost.agent.plist`
- Fix:
  - `bash scripts/setup.sh uninstall`
  - `bash scripts/setup.sh install-source`

### Windows common issues

1. PowerShell blocks setup script

- Run:
  - `Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned`

1. Task Scheduler registration denied

- Use manual run mode (no scheduler).
- Request IT exception if startup automation is required.

1. Antivirus/Defender/SmartScreen blocks execution

- Prefer packaged artifacts from trusted releases.
- Provide hash and publisher details to IT for allow-list review.
- Use source/manual mode if approved by policy.

### Manual fallback (no installer / no scheduler)

macOS and Windows:

```bash
uv sync
uv run deskghost
```

Alternative direct source entrypoint:

```bash
uv run python src/deskghost/main.py
```

If startup registration is blocked, keep a terminal open while running and stop with `Ctrl+C`.

### Log collection for support

Collect these files:

- `~/.deskghost/logs/deskghost.log`
- `~/.deskghost/logs/stdout.log`
- `~/.deskghost/logs/stderr.log`

Include:

1. OS version
2. How DeskGhost was started (source install / packaged install / manual)
3. Exact error text
4. Whether scheduler registration is allowed in your environment

---

## Configuration

All tuneable values live in **`conf/config.yaml`** at the project root.
Edit that file and re-run `install-source` to apply changes — no Python editing required.

```yaml
nudge:
  idle_time_seconds: 120       # how long idle before nudging starts
  move_interval_seconds: 5     # seconds between nudges while idle

schedule:
  work_start: "08:00"          # base start time
  work_end:   "18:00"          # base end time
  work_days:  [0, 1, 2, 3, 4]   # base enabled days (0=Mon ... 6=Sun)
  timezone: "America/Bogota"   # optional IANA timezone; defaults to local machine timezone
  day_overrides:
    4:                          # Friday
      work_end: "14:00"        # shorten Friday
    2:                          # Wednesday
      enabled: false            # disable this day
    5:                          # Saturday
      enabled: true             # enable weekend work
      work_start: "09:00"
      work_end: "12:00"

lunch:
  start: "12:30"               # lunch begins
  duration_minutes: 60         # lunch duration
```

Rule precedence:

- Base schedule comes from `work_days`, `work_start`, `work_end`.
- `day_overrides[weekday]` is merged on top.
- `enabled: false` disables that day even if it is in `work_days`.
- `enabled: true` enables that day even if it is not in `work_days`.
- If only one time bound is overridden, the other bound comes from base schedule.

Timezone behavior:

- Work and lunch checks run in `schedule.timezone` if set, otherwise local machine timezone.
- Install scripts convert the effective schedule into local OS trigger times.
- After any schedule change, re-run install:
  - macOS: `bash scripts/setup.sh uninstall && bash scripts/setup.sh install-source`
  - Windows: `.\scripts\setup.ps1 uninstall` then `.\scripts\setup.ps1 install-source`

---

## Running for development

```bash
# 1. Install dependencies into .venv
uv sync

# 2. Run directly
uv run deskghost

# 3. Or run the source file directly
uv run python src/deskghost/main.py
```

Logs are printed to the terminal and also written to
`~/.deskghost/logs/deskghost.log`.

Press `Ctrl+C` to stop.

---

## macOS — Accessibility permission

DeskGhost needs the **Accessibility** permission to post events into the HID
stream. Without it the nudge runs silently but Teams will still go idle.

**System Settings → Privacy & Security → Accessibility** — add the Python
executable printed in the startup warning, then reinstall:

```bash
bash scripts/setup.sh grant-ax source
bash scripts/setup.sh uninstall && bash scripts/setup.sh install-source
```

For packaged runtime mode, request permission against the packaged binary:

```bash
bash scripts/setup.sh grant-ax packaged
```

---

## Installing as a scheduled task

The setup scripts register DeskGhost to start automatically in **two ways**:

1. **At login / session start** — so DeskGhost is running from the moment you
   open your laptop, even if you missed the time-based trigger because the
   machine was off or asleep.
2. **At configured schedule start times** — as a belt-and-suspenders trigger
   for days when the machine is already on at that time.

DeskGhost self-exits when `work_end` is reached (or immediately if started
outside work hours), so a login-time start on a weekend or evening is harmless.

Configured start triggers are derived from the effective schedule (base days,
day overrides, and timezone) and converted to local OS scheduler times.

### Single-instance guarantee

A platform-level **file lock** (`~/.deskghost/deskghost.lock`) ensures only
one instance of DeskGhost ever runs at a time. If a second launch is attempted
while the first is still running — for example when the machine wakes from
sleep mid-day and the scheduler fires a missed trigger — the new process
detects the lock, logs nothing, and exits immediately. The OS releases the
lock automatically if the process dies unexpectedly, so no manual cleanup is
ever needed.

### macOS — LaunchAgent

```bash
# Make the script executable (one time only)
chmod +x scripts/setup.sh

# Start interactive menu (recommended)
bash scripts/setup.sh

# Or register source-mode LaunchAgent directly
bash scripts/setup.sh install-source

# Register packaged-mode LaunchAgent directly
bash scripts/setup.sh install-packaged

# Build and package from unified script
bash scripts/setup.sh build
bash scripts/setup.sh package

# Verify it is loaded
bash scripts/setup.sh status

# Test it right now without waiting for a scheduled trigger
bash scripts/setup.sh run-now-source

# View logs
bash scripts/setup.sh logs

# Clean runtime leftovers and local build artifacts (with confirmation)
bash scripts/setup.sh clean

# Remove the LaunchAgent
# If currently installed in packaged mode, this also removes build/release artifacts.
bash scripts/setup.sh uninstall
```

The plist is installed to `~/Library/LaunchAgents/com.deskghost.agent.plist`.
Logs go to `~/.deskghost/logs/`.

### Windows — Task Scheduler

Open **PowerShell** (no administrator rights needed):

```powershell
# Start interactive menu (recommended)
.\scripts\setup.ps1

# Register the scheduled task
.\scripts\setup.ps1 install-source

# Register packaged-mode scheduled task
.\scripts\setup.ps1 install-packaged

# Build and package from unified script
.\scripts\setup.ps1 build
.\scripts\setup.ps1 package

# Verify it is registered
.\scripts\setup.ps1 status

# Test it right now
.\scripts\setup.ps1 run-now-source

# View logs
.\scripts\setup.ps1 logs

# Clean runtime leftovers and local build artifacts (with confirmation)
.\scripts\setup.ps1 clean

# Remove the task
# If currently installed in packaged mode, this also removes build/release artifacts.
.\scripts\setup.ps1 uninstall
```

If PowerShell blocks the script due to execution policy, run this first:

```powershell
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
```

The task runs under your user account with limited privileges (no elevation).
Logs go to `~/.deskghost/logs/`.

---

## Logs

Regardless of how DeskGhost is started, output is always written to:

```text
~/.deskghost/logs/deskghost.log
```

When started via the scheduler, stdout and stderr are also captured to:

```text
~/.deskghost/logs/stdout.log
~/.deskghost/logs/stderr.log
```

Log format: `[HH:MM:SS] [LEVEL] message`

---

## Project structure

```text
src/deskghost/
├── main.py          # entry point — detects OS and delegates
├── config.py        # loads conf/config.yaml and exposes typed constants
├── lock.py          # cross-platform single-instance file lock
├── schedule.py      # work-hours / lunch logic
├── logger.py        # shared logger + ThrottledLogger
├── macos/
│   └── watcher.py   # macOS: Quartz CGEvent nudge, caffeinate display lock
└── windows/
    └── watcher.py   # Windows: ctypes SendInput nudge, SetThreadExecutionState

scripts/
├── setup.sh         # macOS unified setup/build/package tool
└── setup.ps1        # Windows unified setup/build/package tool

conf/
└── config.yaml      # all user-facing settings

tests/
├── conftest.py
├── test_config.py
├── test_schedule.py
├── test_logger.py
├── test_main.py
├── test_install.py
├── macos/test_watcher.py   # runs on macOS only
└── windows/test_watcher.py # runs on Windows only
```

---

## Running tests

```bash
uv run pytest          # run all tests
uv run pytest -v       # verbose output
```

Platform-specific tests are skipped automatically on the wrong OS — macOS
watcher tests skip on Windows and vice versa.

### Installation verification tests

`tests/test_install.py` contains a suite of tests that verify the OS-level
scheduler integration is correctly configured. These tests **skip
automatically** when the agent / task has not been installed on the current
machine, so a clean development environment always produces a clean run.

Once you have run `bash scripts/setup.sh install-source` (macOS) or
`scripts\setup.ps1 install-source` (Windows), the install tests become active and
check that:

- The plist / scheduled task file exists and is valid.
- `RunAtLoad` is set (macOS) / a `LogonTrigger` is present (Windows) so
  DeskGhost starts on every login.
- Time-based trigger weekday/hour/minute entries match the effective local
  scheduler entries derived from `conf/config.yaml`.
- The `~/.deskghost/` directory exists and is writable (required for the
  lock file and logs).
- The agent is actually loaded in launchctl (macOS).

Run them explicitly at any time to confirm your install is healthy:

```bash
uv run pytest tests/test_install.py -v
```

---

## Security and antivirus considerations

- **No keystrokes are ever injected.** DeskGhost uses zero-delta mouse events
  exclusively (`CGEvent` on macOS, `SendInput` on Windows). These are
  indistinguishable from the cursor sitting still, which means EDR tools
  (CrowdStrike, SentinelOne, etc.) have nothing behaviour-based to flag.
- If distributing binaries, prefer **Nuitka-built + code-signed** artifacts.
  Unsigned or low-reputation binaries that simulate input are likely to trigger
  AV/EDR heuristics; always keep the documented source/manual run path as a
  fallback in restricted environments.
- Use this tool at your own discretion and in accordance with your
  organisation's policies.
