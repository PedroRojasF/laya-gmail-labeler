[CmdletBinding()]
param(
    [switch]$Apply
)

$ErrorActionPreference = 'Stop'
$taskName = 'Laya Gmail Labeler'
$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonPath = Join-Path $projectRoot '.venv\Scripts\python.exe'

if (-not (Test-Path -LiteralPath $pythonPath -PathType Leaf)) {
    throw 'Project virtual environment not found. Create .venv and install this project first.'
}

$watchMode = if ($Apply) { '--apply' } else { '--dry-run' }
$action = New-ScheduledTaskAction `
    -Execute $pythonPath `
    -Argument "-m laya_gmail_labeler watch $watchMode" `
    -WorkingDirectory $projectRoot
$trigger = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"
$principal = New-ScheduledTaskPrincipal `
    -UserId "$env:USERDOMAIN\$env:USERNAME" `
    -LogonType Interactive `
    -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit ([TimeSpan]::Zero)

Register-ScheduledTask `
    -TaskName $taskName `
    -Action $action `
    -Trigger $trigger `
    -Principal $principal `
    -Settings $settings `
    -Description 'Classify new Gmail Inbox messages locally with Laya.' `
    -Force | Out-Null

if ($Apply) {
    Write-Host 'Scheduled task installed with label application enabled.'
} else {
    Write-Host 'Scheduled task installed in dry-run mode. Use -Apply to enable label changes.'
}