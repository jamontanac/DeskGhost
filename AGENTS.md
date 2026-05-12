# AGENTS.md

## Project

DeskGhost — a Python utility that prevents idle status on Teams/similar apps by nudging the mouse when the user is inactive. Single-package, no CI, no tests.

## Toolchain

- **Package manager:** `uv` (not pip, not poetry). Use `uv` for all dependency and run operations.
- **Build backend:** `uv_build` (not setuptools/hatchling).
- **Python:** 3.13 (pinned in `.python-version`; `requires-python = ">=3.13"`).

## Key Commands

```bash
uv sync            # Install/update dependencies into .venv
uv run deskghost   # Run via installed entrypoint
uv run python src/deskghost/main.py  # Run directly
uv build           # Build wheel/sdist
```

No lint, typecheck, format, or test tooling is configured. No CI workflows exist.

## Structure

```
src/deskghost/main.py   # All application logic (~178 lines)
src/deskghost/__init__.py
pyproject.toml
uv.lock
```

Single-module package. No tests directory. README.md is empty.

## Configuration

All tuneable values are **module-level constants** at the top of `src/deskghost/main.py` — no CLI flags, no env vars, no config file:

```python
IDLE_TIME_SECONDS = 120
MOVE_INTERVAL_SECONDS = 5
WORK_START_TIME = (7, 0)
WORK_END_TIME = (18, 0)
WORK_DAYS = {0, 1, 2, 3, 4}
LUNCH_START_TIME = (12, 30)
LUNCH_DURATION_MINUTES = 60
```

## Runtime Dependencies

- `pynput` — monitors mouse/keyboard input
- `pyautogui` — moves the mouse cursor

Both are runtime-only; no dev/test extras defined in `pyproject.toml`.
