"""Build/package tests for macOS and Windows setup scripts.

These tests focus on two layers:
1) Contract tests that validate each script still contains the expected
   build/package command wiring and artifact naming.
2) Optional live smoke tests that can run real build/package commands when
   explicitly enabled by environment variable.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


def _project_root() -> Path:
    """Return the repository root (directory containing pyproject.toml)."""
    current = Path(__file__).resolve().parent
    while True:
        if (current / "pyproject.toml").exists():
            return current
        parent = current.parent
        if parent == current:
            raise FileNotFoundError("Could not locate project root")
        current = parent


PROJECT_ROOT = _project_root()
SETUP_SH = PROJECT_ROOT / "scripts" / "setup.sh"
SETUP_PS1 = PROJECT_ROOT / "scripts" / "setup.ps1"
RUN_BUILD_SMOKE = os.getenv("DESKGHOST_RUN_BUILD_PACKAGE_TESTS") == "1"


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=PROJECT_ROOT, capture_output=True, text=True)


def _powershell_executable() -> str | None:
    return shutil.which("pwsh") or shutil.which("powershell")


class TestBuildPackageScriptContracts:
    """Static contract checks for build/package script behavior."""

    def test_setup_scripts_exist(self):
        assert SETUP_SH.exists(), f"Missing script: {SETUP_SH}"
        assert SETUP_PS1.exists(), f"Missing script: {SETUP_PS1}"

    def test_macos_build_contract(self):
        text = _read_text(SETUP_SH)

        assert re.search(r"\bcmd_build\(\)\s*\{", text)
        assert "--macos-create-app-bundle" in text
        assert "--macos-app-icon=" in text
        assert "iconutil -c icns" in text
        assert "deskghost.icns" in text
        assert "normalize_macos_bundle_name" in text
        assert "DeskGhost.app" in text
        assert "--output-filename=DeskGhost" in text
        assert "--include-data-files=conf/config.yaml=conf/config.yaml" in text

        # Guard against selecting bundled .so/.dylib for smoke command output.
        assert 'if [[ -x "$app_path/Contents/MacOS/DeskGhost" ]]; then' in text
        assert "! -name '*.so' ! -name '*.dylib'" in text

    def test_macos_package_contract(self):
        text = _read_text(SETUP_SH)

        assert re.search(r"\bcmd_package\(\)\s*\{", text)
        assert 'artifact="DeskGhost-macos-v${version}.zip"' in text
        assert 'zip_path="${RELEASE_DIR}/${artifact}"' in text
        assert 'ditto -c -k --sequesterRsrc --keepParent "$app_path" "$zip_path"' in text

    def test_windows_build_contract(self):
        text = _read_text(SETUP_PS1)

        assert re.search(r"\bfunction\s+Invoke-Build\s*\{", text)
        assert "Resolve-WindowsBuildIcon" in text
        assert "--windows-icon-from-ico=" in text
        assert "python -m nuitka" in text
        assert "--output-filename=DeskGhost.exe" in text
        assert "--include-data-files=conf/config.yaml=conf/config.yaml" in text

    def test_windows_package_contract(self):
        text = _read_text(SETUP_PS1)

        assert re.search(r"\bfunction\s+Invoke-Package\s*\{", text)
        assert '("DeskGhost-windows-v{0}-portable.zip" -f $version)' in text
        assert 'Copy-Item -Recurse -Force (Join-Path $distDir.FullName "*") $stageDir' in text
        assert 'Compress-Archive -Path (Join-Path $stageDir "*") -DestinationPath $zipPath -Force' in text


class TestBuildPackageHelpDispatch:
    """Runnable checks that help output includes build/package commands."""

    @pytest.mark.skipif(sys.platform == "win32", reason="macOS shell helper check is not runnable on Windows")
    def test_macos_help_lists_build_and_package(self):
        result = _run(["bash", "scripts/setup.sh", "help"])
        assert result.returncode == 0, result.stderr
        assert "build" in result.stdout
        assert "package" in result.stdout

    def test_windows_help_lists_build_and_package_when_powershell_available(self):
        ps = _powershell_executable()
        if ps is None:
            pytest.skip("PowerShell not available on this host")

        result = _run([ps, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "scripts/setup.ps1", "help"])
        assert result.returncode == 0, result.stderr
        assert "build" in result.stdout.lower()
        assert "package" in result.stdout.lower()


@pytest.mark.skipif(
    not RUN_BUILD_SMOKE,
    reason="Set DESKGHOST_RUN_BUILD_PACKAGE_TESTS=1 to run live build/package smoke tests",
)
class TestLiveBuildPackageSmoke:
    """Optional real build/package smoke tests.

    These are intentionally opt-in because they are slower and require platform
    toolchains (Nuitka/compiler/PowerShell availability).
    """

    @pytest.mark.skipif(sys.platform != "darwin", reason="macOS smoke test runs on macOS only")
    def test_macos_build_and_package(self):
        build = _run(["bash", "scripts/setup.sh", "build"])
        assert build.returncode == 0, f"build failed:\nSTDOUT:\n{build.stdout}\nSTDERR:\n{build.stderr}"

        app_dirs = list((PROJECT_ROOT / "build" / "macos").glob("*.app"))
        assert app_dirs, "No .app bundle produced under build/macos"

        package = _run(["bash", "scripts/setup.sh", "package"])
        assert package.returncode == 0, f"package failed:\nSTDOUT:\n{package.stdout}\nSTDERR:\n{package.stderr}"

        artifacts = list((PROJECT_ROOT / "build" / "release" / "macos").glob("DeskGhost-macos-v*.zip"))
        assert artifacts, "No macOS packaged artifact produced"

    @pytest.mark.skipif(sys.platform != "win32", reason="Windows smoke test runs on Windows only")
    def test_windows_build_and_package(self):
        ps = _powershell_executable()
        if ps is None:
            pytest.skip("PowerShell not available on this host")

        build = _run([ps, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "scripts/setup.ps1", "build"])
        assert build.returncode == 0, f"build failed:\nSTDOUT:\n{build.stdout}\nSTDERR:\n{build.stderr}"

        dist_dirs = list((PROJECT_ROOT / "build" / "windows").glob("*.dist"))
        assert dist_dirs, "No Windows .dist directory produced under build/windows"

        package = _run([ps, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "scripts/setup.ps1", "package"])
        assert package.returncode == 0, f"package failed:\nSTDOUT:\n{package.stdout}\nSTDERR:\n{package.stderr}"

        artifacts = list((PROJECT_ROOT / "build" / "release" / "windows").glob("DeskGhost-windows-v*-portable.zip"))
        assert artifacts, "No Windows packaged artifact produced"
