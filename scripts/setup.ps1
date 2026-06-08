#Requires -Version 5.1
<#
.SYNOPSIS
    Unified DeskGhost Windows setup/build/package tool.

.DESCRIPTION
    Interactive mode (no args):
      .\scripts\setup.ps1

    Non-interactive actions:
      .\scripts\setup.ps1 install-source
      .\scripts\setup.ps1 install-packaged [binary-or-folder-path]
      .\scripts\setup.ps1 build
      .\scripts\setup.ps1 package
      .\scripts\setup.ps1 run-now-source
      .\scripts\setup.ps1 run-now-packaged [binary-or-folder-path]
      .\scripts\setup.ps1 status
      .\scripts\setup.ps1 logs
      .\scripts\setup.ps1 clean
      .\scripts\setup.ps1 uninstall

    Backward-compatible aliases:
      install -> install-source
      run-now -> run-now-source
#>

param(
    [Parameter(Position = 0)]
    [string]$Action = "",

    [Parameter(Position = 1)]
    [string]$Arg1 = "",

    [Parameter(Position = 2)]
    [string]$Arg2 = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# ── Constants ─────────────────────────────────────────────────────────────────

$TaskName   = "DeskGhost"
$LogDir     = Join-Path $HOME ".deskghost\logs"
$StdoutLog  = Join-Path $LogDir "stdout.log"
$StderrLog  = Join-Path $LogDir "stderr.log"

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$BuildDir    = Join-Path $ProjectRoot "build\windows"
$ReleaseDir  = Join-Path $ProjectRoot "build\release\windows"
$MediaDir    = Join-Path $ProjectRoot "media"

$script:PromptUser = $false

# ── Helpers ───────────────────────────────────────────────────────────────────

function Write-Green  { param([string]$Msg) Write-Host $Msg -ForegroundColor Green }
function Write-Red    { param([string]$Msg) Write-Host $Msg -ForegroundColor Red }
function Write-Yellow { param([string]$Msg) Write-Host $Msg -ForegroundColor Yellow }

function Get-UvPath {
    try {
        return (Get-Command uv -ErrorAction Stop).Source
    }
    catch {
        Write-Red "Error: 'uv' not found on PATH."
        Write-Red "Install it from https://docs.astral.sh/uv/getting-started/installation/"
        exit 1
    }
}

function Assert-ProjectRoot {
    if (-not (Test-Path (Join-Path $ProjectRoot "pyproject.toml"))) {
        Write-Red "Error: pyproject.toml not found in $ProjectRoot"
        Write-Red "Run this script from inside the deskghost repository."
        exit 1
    }
    if (-not (Test-Path (Join-Path $ProjectRoot "conf\config.yaml"))) {
        Write-Red "Error: conf\config.yaml not found in $ProjectRoot"
        exit 1
    }
}

function Task-Exists {
    $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    return ($null -ne $task)
}

function Get-InstalledMode {
    if (-not (Task-Exists)) {
        return "unknown"
    }

    $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    $actions = @($task.Actions)
    if ($null -eq $task -or $actions.Count -eq 0) {
        return "unknown"
    }

    $actionArgs = [string]$actions[0].Arguments
    if ($actionArgs -match '\brun\s+deskghost\b') {
        return "source"
    }

    return "packaged"
}

function Remove-BuildArtifacts {
    $removedAny = $false

    foreach ($dir in @($BuildDir, $ReleaseDir)) {
        if (Test-Path $dir) {
            Remove-Item -Recurse -Force $dir
            Write-Green "Deleted: $dir"
            $removedAny = $true
        }
    }

    if (-not $removedAny) {
        Write-Yellow "No build artifacts found under $(Join-Path $ProjectRoot 'build')."
    }
}

function Get-Version {
    $uvPath = Get-UvPath

    Push-Location $ProjectRoot
    try {
        $version = & $uvPath run --project $ProjectRoot python -c "import pathlib,tomllib; d=tomllib.loads(pathlib.Path('pyproject.toml').read_text(encoding='utf-8')); print(d.get('project',{}).get('version','0.0.0'))" 2>$null
        if ([string]::IsNullOrWhiteSpace($version)) {
            return "0.0.0"
        }
        return $version.Trim()
    }
    finally {
        Pop-Location
    }
}

function Get-WindowsMetadataVersion {
    $rawVersion = Get-Version
    $numericParts = @([regex]::Matches($rawVersion, '\d+') | ForEach-Object { [int]$_.Value })

    if ($numericParts.Count -eq 0) {
        return "0.0.0.0"
    }

    while ($numericParts.Count -lt 4) {
        $numericParts += 0
    }

    if ($numericParts.Count -gt 4) {
        $numericParts = $numericParts[0..3]
    }

    return ($numericParts -join ".")
}

function Get-TriggerEntries {
    param([string]$UvPath)

    $lines = & $UvPath run --project $ProjectRoot python -c @'
from deskghost.config import get_local_scheduler_trigger_entries
for day, hour, minute in get_local_scheduler_trigger_entries():
    print(f"{day} {hour} {minute}")
'@

    $entries = @()
    foreach ($line in $lines) {
        if ([string]::IsNullOrWhiteSpace($line)) {
            continue
        }
        $parts = $line.Trim().Split(' ', [System.StringSplitOptions]::RemoveEmptyEntries)
        if ($parts.Length -ne 3) {
            throw "Unexpected trigger entry format from Python: '$line'"
        }
        $entries += [pscustomobject]@{
            Weekday = [int]$parts[0]
            Hour    = [int]$parts[1]
            Minute  = [int]$parts[2]
        }
    }
    return $entries
}

function Format-TriggerEntriesPretty {
    param([array]$Entries)

    $dayNames = @("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
    return $Entries |
        Sort-Object Weekday, Hour, Minute |
        ForEach-Object { "{0} {1:00}:{2:00}" -f $dayNames[$_.Weekday], $_.Hour, $_.Minute }
}

function Find-PackagedBinary {
    param([string]$Hint)

    if (-not [string]::IsNullOrWhiteSpace($Hint)) {
        if ((Test-Path $Hint) -and (Get-Item $Hint).PSIsContainer) {
            $preferred = Join-Path $Hint "DeskGhost.exe"
            if (Test-Path $preferred) {
                return (Resolve-Path $preferred).Path
            }
            $any = Get-ChildItem -Path $Hint -File -Filter *.exe -ErrorAction SilentlyContinue | Select-Object -First 1
            if ($any) {
                return $any.FullName
            }
        }
        elseif ((Test-Path $Hint) -and -not (Get-Item $Hint).PSIsContainer) {
            return (Resolve-Path $Hint).Path
        }
        return $null
    }

    $defaultExe = Join-Path $BuildDir "DeskGhost.exe"
    if (Test-Path $defaultExe) {
        return (Resolve-Path $defaultExe).Path
    }

    if (-not (Test-Path $BuildDir)) {
        return $null
    }

    $candidate = Get-ChildItem -Path $BuildDir -File -Filter *.exe -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($candidate) {
        return $candidate.FullName
    }

    return $null
}

function Resolve-WindowsBuildIcon {
    $icoPath = Join-Path $MediaDir "deskghost.ico"
    if (Test-Path $icoPath) {
        return (Resolve-Path $icoPath).Path
    }

    $pngPath = Join-Path $MediaDir "deskghost.png"
    if (Test-Path $pngPath) {
        return (Resolve-Path $pngPath).Path
    }

    $jpgPath = Join-Path $MediaDir "deskghost.jpg"
    $jpegPath = Join-Path $MediaDir "deskghost.jpeg"
    if ((Test-Path $jpgPath) -or (Test-Path $jpegPath)) {
        Write-Yellow "Found JPG logo in media/, but Windows icon build expects deskghost.png or deskghost.ico."
        Write-Yellow "Create media\\deskghost.png (recommended) to embed the icon in DeskGhost.exe."
    }

    return $null
}

function Resolve-PackagedBinary {
    param([string]$Hint)

    $binaryPath = Find-PackagedBinary -Hint $Hint
    if ([string]::IsNullOrWhiteSpace($binaryPath)) {
        Write-Red "No packaged executable found."
        Write-Yellow "Build first: .\scripts\setup.ps1 build"
        exit 1
    }

    if (-not (Test-Path $binaryPath)) {
        Write-Red "Packaged executable not found: $binaryPath"
        exit 1
    }

    return $binaryPath
}

function New-DeskGhostAction {
    param(
        [ValidateSet("source", "packaged")]
        [string]$Mode,
        [string]$UvPath,
        [string]$BinaryPath
    )

    if ($Mode -eq "source") {
        $cmdLine = "`"$UvPath`" run deskghost >> `"$StdoutLog`" 2>> `"$StderrLog`""
    }
    else {
        $cmdLine = "`"$BinaryPath`" >> `"$StdoutLog`" 2>> `"$StderrLog`""
    }

    return New-ScheduledTaskAction `
        -Execute "cmd.exe" `
        -Argument "/c $cmdLine" `
        -WorkingDirectory $ProjectRoot
}

function Register-DeskGhostTask {
    param(
        [ValidateSet("source", "packaged")]
        [string]$Mode,
        [string]$BinaryPath = ""
    )

    $uvPath = Get-UvPath
    Assert-ProjectRoot

    New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

    if (Task-Exists) {
        Write-Yellow "Existing task found — replacing..."
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    }

    $action = New-DeskGhostAction -Mode $Mode -UvPath $uvPath -BinaryPath $BinaryPath

    $triggerEntries = @(Get-TriggerEntries -UvPath $uvPath)
    if ($triggerEntries.Count -eq 0) {
        Write-Red "Error: no enabled schedule days found in conf/config.yaml."
        Write-Red "Enable at least one weekday in schedule.work_days or schedule.day_overrides."
        exit 1
    }

    $dayMap = @{
        0 = "Monday"
        1 = "Tuesday"
        2 = "Wednesday"
        3 = "Thursday"
        4 = "Friday"
        5 = "Saturday"
        6 = "Sunday"
    }

    $triggerTime = @()
    foreach ($entry in $triggerEntries) {
        if (-not $dayMap.ContainsKey($entry.Weekday)) {
            throw "Invalid weekday from config trigger conversion: $($entry.Weekday)"
        }
        $at = "{0:00}:{1:00}" -f $entry.Hour, $entry.Minute
        $triggerTime += New-ScheduledTaskTrigger -Weekly -DaysOfWeek $dayMap[$entry.Weekday] -At $at
    }

    $triggerLogon = New-ScheduledTaskTrigger -AtLogOn -User ([System.Security.Principal.WindowsIdentity]::GetCurrent().Name)
    $allTriggers = @($triggerLogon) + $triggerTime

    $settings = New-ScheduledTaskSettingsSet `
        -ExecutionTimeLimit (New-TimeSpan -Hours 12) `
        -MultipleInstances IgnoreNew `
        -StartWhenAvailable

    $principal = New-ScheduledTaskPrincipal `
        -UserId ([System.Security.Principal.WindowsIdentity]::GetCurrent().Name) `
        -LogonType Interactive `
        -RunLevel Limited

    Register-ScheduledTask `
        -TaskName $TaskName `
        -Action $action `
        -Trigger $allTriggers `
        -Settings $settings `
        -Principal $principal `
        -Force | Out-Null

    Write-Green "Scheduled task registered."
    Write-Green "  task      : $TaskName"
    Write-Green "  mode      : $Mode"
    Write-Green "  project   : $ProjectRoot"
    Write-Green "  logs      : $LogDir"
    if ($Mode -eq "source") {
        Write-Green "  uv        : $uvPath"
    }
    else {
        Write-Green "  runtime   : $BinaryPath"
    }

    Write-Green "DeskGhost will start at login and configured schedule start times (local clock)."
    Write-Yellow "Configured local triggers:"
    Format-TriggerEntriesPretty -Entries $triggerEntries | ForEach-Object {
        Write-Yellow "  $_"
    }
}

# ── Commands ──────────────────────────────────────────────────────────────────

function Invoke-Build {
    $uvPath = Get-UvPath
    Assert-ProjectRoot
    $metadataVersion = Get-WindowsMetadataVersion

    if (($env:CI -eq "true") -and -not (Get-Command depends.exe -ErrorAction SilentlyContinue)) {
        throw "Dependency Walker (depends.exe) is required for Windows standalone Nuitka builds in CI. Ensure the workflow installs it before running .\scripts\setup.ps1 build."
    }

    New-Item -ItemType Directory -Force -Path $BuildDir | Out-Null

    Write-Yellow "Syncing dependencies..."
    & $uvPath sync --project $ProjectRoot
    if ($LASTEXITCODE -ne 0) {
        throw "uv sync failed with exit code $LASTEXITCODE."
    }

    $nuitkaArgs = @(
        "--standalone",
        "--assume-yes-for-downloads",
        "--output-dir=$BuildDir",
        "--output-filename=DeskGhost.exe",
        "--company-name=DeskGhost",
        "--product-name=DeskGhost",
        "--file-version=$metadataVersion",
        "--product-version=$metadataVersion",
        "--include-package=deskghost",
        "--include-data-files=conf/config.yaml=conf/config.yaml",
        "--include-data-files=pyproject.toml=pyproject.toml",
        "src/deskghost/main.py"
    )

    $iconPath = Resolve-WindowsBuildIcon
    if (-not [string]::IsNullOrWhiteSpace($iconPath)) {
        Write-Yellow "Using Windows executable icon: $iconPath"
        $nuitkaArgs += "--windows-icon-from-ico=$iconPath"
    }

    $uvRunArgs = @(
        "run",
        "--project",
        $ProjectRoot,
        "--with",
        "nuitka"
    )

    if (-not [string]::IsNullOrWhiteSpace($iconPath)) {
        $iconExt = [System.IO.Path]::GetExtension($iconPath).ToLowerInvariant()
        if ($iconExt -ne ".ico") {
            Write-Yellow "Non-ICO icon detected. Adding imageio so Nuitka can convert icon formats automatically."
            $uvRunArgs += @("--with", "imageio")
        }
    }

    $uvRunArgs += @("python", "-m", "nuitka")
    $uvRunArgs += $nuitkaArgs

    Write-Yellow "Building Windows executable with Nuitka..."
    Push-Location $ProjectRoot
    try {
        & $uvPath @uvRunArgs
        if ($LASTEXITCODE -ne 0) {
            throw "Nuitka build failed with exit code $LASTEXITCODE."
        }
    }
    finally {
        Pop-Location
    }

    $distDir = Get-ChildItem -Path $BuildDir -Directory -Filter *.dist -ErrorAction SilentlyContinue | Select-Object -First 1
    $exeFile = Find-PackagedBinary -Hint ""

    Write-Green "Build complete."
    Write-Yellow "Outputs:"
    if ($exeFile) {
        Write-Yellow "  $exeFile"
    }
    if ($distDir) {
        Write-Yellow "  $($distDir.FullName)"
    }
    Write-Host ""
    Write-Yellow "Smoke test command:"
    if ($exeFile) {
        Write-Yellow "  $exeFile"
    }
}

function Invoke-Package {
    Assert-ProjectRoot

    if (-not (Test-Path $BuildDir)) {
        Write-Red "Build directory not found: $BuildDir"
        Write-Yellow "Build first: .\scripts\setup.ps1 build"
        exit 1
    }

    $distDir = Get-ChildItem -Path $BuildDir -Directory -Filter *.dist -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $distDir) {
        Write-Red "No *.dist directory found in $BuildDir"
        Write-Yellow "Build first: .\scripts\setup.ps1 build"
        exit 1
    }

    $version = Get-Version
    $zipPath = Join-Path $ReleaseDir ("DeskGhost-windows-v{0}-portable.zip" -f $version)
    $stageDir = Join-Path $ReleaseDir "DeskGhost"

    New-Item -ItemType Directory -Force -Path $ReleaseDir | Out-Null

    if (Test-Path $stageDir) {
        Remove-Item -Recurse -Force $stageDir
    }
    New-Item -ItemType Directory -Force -Path $stageDir | Out-Null

    Copy-Item -Recurse -Force (Join-Path $distDir.FullName "*") $stageDir

    if (Test-Path $zipPath) {
        Remove-Item -Force $zipPath
    }
    Compress-Archive -Path (Join-Path $stageDir "*") -DestinationPath $zipPath -Force

    Write-Green "Packaging complete."
    Write-Yellow "Dist folder: $($distDir.FullName)"
    Write-Yellow "Artifact   : $zipPath"
}

function Invoke-InstallSource {
    Register-DeskGhostTask -Mode source
    Write-Yellow "To test right now run: .\scripts\setup.ps1 run-now-source"
}

function Invoke-InstallPackaged {
    param([string]$BinaryPath)

    $resolved = Resolve-PackagedBinary -Hint $BinaryPath
    Register-DeskGhostTask -Mode packaged -BinaryPath $resolved
    Write-Yellow "To test right now run: .\scripts\setup.ps1 run-now-packaged"
}

function Invoke-Uninstall {
    $installedMode = Get-InstalledMode

    if (Task-Exists) {
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
        Write-Green "Scheduled task removed."
    }
    else {
        Write-Yellow "Task '$TaskName' not found (already removed?)."
    }

    if ($installedMode -eq "packaged") {
        Write-Yellow "Packaged install detected. Removing build artifacts..."
        Remove-BuildArtifacts
    }
}

function Invoke-RunNowSource {
    $uvPath = Get-UvPath
    Assert-ProjectRoot
    Write-Green "Starting DeskGhost now in source mode (Ctrl+C to stop)..."
    Push-Location $ProjectRoot
    try {
        & $uvPath run deskghost
    }
    finally {
        Pop-Location
    }
}

function Invoke-RunNowPackaged {
    param([string]$BinaryPath)

    $resolved = Resolve-PackagedBinary -Hint $BinaryPath
    Write-Green "Starting DeskGhost now in packaged mode (Ctrl+C to stop)..."
    & $resolved
}

function Invoke-Status {
    if (Task-Exists) {
        $task = Get-ScheduledTask -TaskName $TaskName
        $info = Get-ScheduledTaskInfo -TaskName $TaskName
        Write-Green "Task '$TaskName' IS registered."
        Write-Host  "  State           : $($task.State)"
        Write-Host  "  Last run time   : $($info.LastRunTime)"
        Write-Host  "  Last result     : $($info.LastTaskResult)"
        Write-Host  "  Next run time   : $($info.NextRunTime)"
    }
    else {
        Write-Red "Task '$TaskName' is NOT registered."
        Write-Yellow "Run: .\scripts\setup.ps1 install-source"
    }
}

function Invoke-Logs {
    Write-Host "── stdout ($StdoutLog) ─────────────────────────────"
    if (Test-Path $StdoutLog) {
        Get-Content $StdoutLog -Tail 40
    }
    else {
        Write-Yellow "(no stdout log yet)"
    }
    Write-Host ""
    Write-Host "── stderr ($StderrLog) ─────────────────────────────"
    if (Test-Path $StderrLog) {
        Get-Content $StderrLog -Tail 20
    }
    else {
        Write-Yellow "(no stderr log yet)"
    }
}

function Invoke-Clean {
    $lockFile = Join-Path $HOME ".deskghost\deskghost.lock"
    $logFile = Join-Path $LogDir "deskghost.log"
    $logFile1 = Join-Path $LogDir "deskghost.log.1"

    $pid = $null
    $pidAlive = $false

    if (Test-Path $lockFile) {
        $raw = (Get-Content $lockFile -ErrorAction SilentlyContinue | Select-Object -First 1)
        if ($raw -match '^[0-9]+$') {
            $pid = [int]$raw
            $proc = Get-Process -Id $pid -ErrorAction SilentlyContinue
            if ($null -ne $proc) {
                $pidAlive = $true
            }
        }
    }

    $actions = New-Object System.Collections.Generic.List[string]

    if ($pidAlive) {
        [void]$actions.Add("  [kill]   PID $pid (deskghost process)")
    }

    foreach ($f in @($logFile, $logFile1, $StdoutLog, $StderrLog)) {
        if (Test-Path $f) {
            [void]$actions.Add("  [delete] $f")
        }
    }

    foreach ($dir in @($BuildDir, $ReleaseDir)) {
        if (Test-Path $dir) {
            [void]$actions.Add("  [delete] $dir")
        }
    }

    if (Test-Path $lockFile -and $pidAlive) {
        [void]$actions.Add("  [delete] $lockFile")
    }

    if ($actions.Count -eq 0) {
        if (Test-Path $lockFile) {
            Remove-Item -Force $lockFile -ErrorAction SilentlyContinue
        }
        Write-Green "Nothing to clean."
        return
    }

    Write-Yellow "The following actions will be taken:"
    $actions | ForEach-Object { Write-Yellow $_ }
    Write-Host ""
    $reply = Read-Host "Proceed? [y/N]"

    if ($reply -notmatch '^[Yy]$') {
        Write-Yellow "Aborted. Nothing was changed."
        return
    }

    if ($pidAlive) {
        Stop-Process -Id $pid -Force -ErrorAction SilentlyContinue
        Write-Green "PID $pid stopped."
        if (Test-Path $lockFile) {
            Remove-Item -Force $lockFile -ErrorAction SilentlyContinue
        }
    }

    foreach ($f in @($logFile, $logFile1, $StdoutLog, $StderrLog)) {
        if (Test-Path $f) {
            Remove-Item -Force $f -ErrorAction SilentlyContinue
            Write-Green "Deleted: $f"
        }
    }

    foreach ($dir in @($BuildDir, $ReleaseDir)) {
        if (Test-Path $dir) {
            Remove-Item -Recurse -Force $dir -ErrorAction SilentlyContinue
            Write-Green "Deleted: $dir"
        }
    }
}

function Show-Usage {
@"
Usage: .\scripts\setup.ps1 [action] [arg1] [arg2]

Actions:
  install / install-source
  install-packaged [binary-or-folder-path]
  build
  package
  run-now / run-now-source
  run-now-packaged [binary-or-folder-path]
  status
  logs
  clean
  uninstall
  help

No args starts interactive mode.
"@ | Write-Host
}

function Show-Menu {
    $script:PromptUser = $true

    while ($true) {
        Write-Host ""
        Write-Yellow "DeskGhost Windows setup"
        Write-Host "  1) Install task (source mode: uv run deskghost)"
        Write-Host "  2) Build app (Nuitka)"
        Write-Host "  3) Package built app (.zip)"
        Write-Host "  4) Install task (packaged mode)"
        Write-Host "  5) Run now (source mode)"
        Write-Host "  6) Run now (packaged mode)"
        Write-Host "  7) Status"
        Write-Host "  8) Logs"
        Write-Host "  9) Clean"
        Write-Host " 10) Uninstall"
        Write-Host "  0) Exit"

        $choice = Read-Host "Choose an option [0-10]"

        switch ($choice) {
            "1" { Invoke-InstallSource }
            "2" { Invoke-Build }
            "3" { Invoke-Package }
            "4" {
                $path = Read-Host "Binary/folder path (leave empty to auto-detect)"
                Invoke-InstallPackaged -BinaryPath $path
            }
            "5" { Invoke-RunNowSource }
            "6" {
                $path = Read-Host "Binary/folder path (leave empty to auto-detect)"
                Invoke-RunNowPackaged -BinaryPath $path
            }
            "7" { Invoke-Status }
            "8" { Invoke-Logs }
            "9" { Invoke-Clean }
            "10" { Invoke-Uninstall }
            "0" { break }
            default { Write-Red "Invalid option. Choose 0-10." }
        }
    }
}

# ── Dispatch ──────────────────────────────────────────────────────────────────

if ([string]::IsNullOrWhiteSpace($Action)) {
    Show-Menu
    return
}

$actionName = $Action.ToLowerInvariant()

switch ($actionName) {
    "install" { Invoke-InstallSource }
    "install-source" { Invoke-InstallSource }
    "install-packaged" { Invoke-InstallPackaged -BinaryPath $Arg1 }
    "build" { Invoke-Build }
    "package" { Invoke-Package }
    "run-now" { Invoke-RunNowSource }
    "run-now-source" { Invoke-RunNowSource }
    "run-now-packaged" { Invoke-RunNowPackaged -BinaryPath $Arg1 }
    "status" { Invoke-Status }
    "logs" { Invoke-Logs }
    "clean" { Invoke-Clean }
    "uninstall" { Invoke-Uninstall }
    "help" { Show-Usage }
    "-h" { Show-Usage }
    "--help" { Show-Usage }
    default {
        Write-Red "Unknown action: $Action"
        Show-Usage
        exit 1
    }
}
