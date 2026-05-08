#Requires -Version 5.1
<#
.SYNOPSIS
    DeskGhost Windows installer — manages a Task Scheduler task that starts
    DeskGhost at login AND at the configured work-start time Mon–Fri.

.DESCRIPTION
    DeskGhost self-exits when outside work hours, so a login-time launch
    outside working hours is harmless.  A PID lock inside the app prevents
    double-launch when both triggers fire for the same session (e.g. the
    machine wakes from sleep with DeskGhost already running and the scheduler
    fires the missed trigger via StartWhenAvailable).

.PARAMETER Action
    install    Register the scheduled task
    uninstall  Remove the scheduled task
    run-now    Run DeskGhost immediately (for testing)
    status     Show whether the task exists and its last run result
    logs       Tail the log files

.EXAMPLE
    .\scripts\setup.ps1 install
    .\scripts\setup.ps1 run-now
    .\scripts\setup.ps1 logs
#>

param(
    [Parameter(Position = 0, Mandatory = $true)]
    [ValidateSet("install", "uninstall", "run-now", "status", "logs")]
    [string]$Action
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# ── Constants ─────────────────────────────────────────────────────────────────

$TaskName   = "DeskGhost"
$LogDir     = Join-Path $HOME ".deskghost\logs"
$StdoutLog  = Join-Path $LogDir "stdout.log"
$StderrLog  = Join-Path $LogDir "stderr.log"

# Project root = parent of the directory containing this script
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path

# ── Helpers ───────────────────────────────────────────────────────────────────

function Write-Green  { param([string]$Msg) Write-Host $Msg -ForegroundColor Green  }
function Write-Red    { param([string]$Msg) Write-Host $Msg -ForegroundColor Red    }
function Write-Yellow { param([string]$Msg) Write-Host $Msg -ForegroundColor Yellow }

function Get-UvPath {
    try {
        $uv = (Get-Command uv -ErrorAction Stop).Source
        return $uv
    } catch {
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
}

function Task-Exists {
    $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    return ($null -ne $task)
}

# ── Commands ──────────────────────────────────────────────────────────────────

function Get-WorkStart {
    # Read WORK_START_TIME from conf/config.yaml via Python — single source of truth.
    # Returns a string like "07:00" suitable for New-ScheduledTaskTrigger -At.
    $uvPath = Get-UvPath
    $result = & $uvPath run --project $ProjectRoot python -c @'
from deskghost.config import WORK_START_TIME
print(f"{WORK_START_TIME[0]:02d}:{WORK_START_TIME[1]:02d}")
'@
    return $result.Trim()
}

function Invoke-Install {
    $uvPath = Get-UvPath
    Assert-ProjectRoot

    # Ensure log directory exists
    New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

    # Remove stale task if present
    if (Task-Exists) {
        Write-Yellow "Existing task found — replacing..."
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    }

    # The action wraps the command in cmd /c so stdout/stderr can be redirected
    # to the log files.  cmd /c is the simplest cross-version way to do this
    # without requiring extra modules.
    $cmdLine = "`"$uvPath`" run deskghost >> `"$StdoutLog`" 2>> `"$StderrLog`""
    $action  = New-ScheduledTaskAction `
        -Execute  "cmd.exe" `
        -Argument "/c $cmdLine" `
        -WorkingDirectory $ProjectRoot

    # Triggers:
    #   1. At user logon — ensures DeskGhost starts even if the machine was off
    #      or asleep when the time-based trigger was supposed to fire.
    #   2. Weekly at work_start time Mon–Fri — fires on time when machine is on.
    # StartWhenAvailable means the time-based trigger also fires on wake if missed.
    $workStart   = Get-WorkStart
    $triggerTime = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At $workStart
    $triggerLogon = New-ScheduledTaskTrigger -AtLogOn -User ([System.Security.Principal.WindowsIdentity]::GetCurrent().Name)

    # Settings: run only when user is logged on, limited privilege (no elevation)
    $settings = New-ScheduledTaskSettingsSet `
        -ExecutionTimeLimit (New-TimeSpan -Hours 12) `
        -MultipleInstances IgnoreNew `
        -StartWhenAvailable

    $principal = New-ScheduledTaskPrincipal `
        -UserId ([System.Security.Principal.WindowsIdentity]::GetCurrent().Name) `
        -LogonType Interactive `
        -RunLevel Limited

    Register-ScheduledTask `
        -TaskName  $TaskName `
        -Action    $action `
        -Trigger   @($triggerLogon, $triggerTime) `
        -Settings  $settings `
        -Principal $principal `
        -Force | Out-Null

    Write-Green "Scheduled task registered."
    Write-Green "  task      : $TaskName"
    Write-Green "  uv        : $uvPath"
    Write-Green "  project   : $ProjectRoot"
    Write-Green "  logs      : $LogDir"
    Write-Green "DeskGhost will start at login and at $workStart Mon-Fri."
    Write-Yellow "To test right now run:  .\scripts\setup.ps1 run-now"
}

function Invoke-Uninstall {
    if (Task-Exists) {
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
        Write-Green "Scheduled task removed."
    } else {
        Write-Yellow "Task '$TaskName' not found (already removed?)."
    }
}

function Invoke-RunNow {
    $uvPath = Get-UvPath
    Assert-ProjectRoot
    Write-Green "Starting DeskGhost now (Ctrl+C to stop)..."
    Set-Location $ProjectRoot
    & $uvPath run deskghost
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
    } else {
        Write-Red "Task '$TaskName' is NOT registered."
        Write-Yellow "Run:  .\scripts\setup.ps1 install"
    }
}

function Invoke-Logs {
    Write-Host "── stdout ($StdoutLog) ─────────────────────────────"
    if (Test-Path $StdoutLog) {
        Get-Content $StdoutLog -Tail 40
    } else {
        Write-Yellow "(no stdout log yet)"
    }
    Write-Host ""
    Write-Host "── stderr ($StderrLog) ─────────────────────────────"
    if (Test-Path $StderrLog) {
        Get-Content $StderrLog -Tail 20
    } else {
        Write-Yellow "(no stderr log yet)"
    }
}

# ── Dispatch ──────────────────────────────────────────────────────────────────

switch ($Action) {
    "install"   { Invoke-Install   }
    "uninstall" { Invoke-Uninstall }
    "run-now"   { Invoke-RunNow    }
    "status"    { Invoke-Status    }
    "logs"      { Invoke-Logs      }
}
