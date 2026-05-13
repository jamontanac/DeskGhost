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
|---|---|---|
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
|---|---|
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

---

## Configuration

All tuneable values live in **`conf/config.yaml`** at the project root.
Edit that file and re-run `install` to apply changes — no Python editing required.

```yaml
nudge:
  idle_time_seconds: 120       # how long idle before nudging starts
  move_interval_seconds: 5     # seconds between nudges while idle

schedule:
  work_start: "07:00"          # bot starts at this time; also the scheduled task trigger
  work_end:   "18:00"          # bot self-exits at this time
  work_days:  [0, 1, 2, 3, 4] # 0=Mon … 4=Fri

lunch:
  start: "12:30"               # lunch begins
  duration_minutes: 60         # lunch duration
```

`work_start` is used as **both** the in-process work-hours boundary and the
scheduled task trigger time. Changing it and re-running `install` updates the
LaunchAgent / Task Scheduler trigger automatically — no manual plist/XML editing.

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
bash scripts/setup.sh uninstall && bash scripts/setup.sh install
```

---

## Installing as a scheduled task

The setup scripts register DeskGhost to start automatically in **two ways**:

1. **At login / session start** — so DeskGhost is running from the moment you
   open your laptop, even if you missed the time-based trigger because the
   machine was off or asleep.
2. **At the `work_start` time** Mon–Fri — as a belt-and-suspenders trigger for
   days when the machine is already on at that time.

DeskGhost self-exits when `work_end` is reached (or immediately if started
outside work hours), so a login-time start on a weekend or evening is harmless.

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

# Register the LaunchAgent
bash scripts/setup.sh install

# Verify it is loaded
bash scripts/setup.sh status

# Test it right now without waiting for work_start
bash scripts/setup.sh run-now

# View logs
bash scripts/setup.sh logs

# Remove the LaunchAgent
bash scripts/setup.sh uninstall
```

The plist is installed to `~/Library/LaunchAgents/com.deskghost.agent.plist`.
Logs go to `~/.deskghost/logs/`.

### Windows — Task Scheduler

Open **PowerShell** (no administrator rights needed):

```powershell
# Register the scheduled task
.\scripts\setup.ps1 install

# Verify it is registered
.\scripts\setup.ps1 status

# Test it right now
.\scripts\setup.ps1 run-now

# View logs
.\scripts\setup.ps1 logs

# Remove the task
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

```
~/.deskghost/logs/deskghost.log
```

When started via the scheduler, stdout and stderr are also captured to:

```
~/.deskghost/logs/stdout.log
~/.deskghost/logs/stderr.log
```

Log format: `[HH:MM:SS] [LEVEL] message`

---

## Project structure

```
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
├── setup.sh         # macOS installer (launchd LaunchAgent)
└── setup.ps1        # Windows installer (Task Scheduler)

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

Once you have run `bash scripts/setup.sh install` (macOS) or
`scripts\setup.ps1 install` (Windows), the install tests become active and
check that:

- The plist / scheduled task file exists and is valid.
- `RunAtLoad` is set (macOS) / a `LogonTrigger` is present (Windows) so
  DeskGhost starts on every login.
- The time-based trigger hour and minute match `conf/config.yaml` — no
  drift if you edit the config and forget to reinstall.
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
- **Do not package this as a standalone `.exe`** using PyInstaller or similar
  tools. Packed Python binaries that simulate input are near-certain to trigger
  AV heuristics. Running via `uv run deskghost` from source is the safe approach.
- Use this tool at your own discretion and in accordance with your
  organisation's policies.
