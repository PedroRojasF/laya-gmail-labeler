[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$taskName = 'Laya Gmail Labeler'
$task = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if ($null -eq $task) {
    Write-Host 'Scheduled task is not installed.'
    exit 0
}

if ($task.State -eq 'Running') {
    Stop-ScheduledTask -TaskName $taskName
}

Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
Write-Host 'Scheduled task removed.'
