# Schedules the Gmail alerts with Windows Task Scheduler (run once, in PowerShell).
#
#   1. Fill TA_GMAIL_USER / TA_GMAIL_APP_PASSWORD in the project's .env
#   2. tradingagents alerts test        (a test mail must arrive)
#   3. powershell -ExecutionPolicy Bypass -File scripts\register_alerts.ps1
#
# Creates three tasks (weekdays; holidays are skipped by the commands themselves):
#   TA-Digest-Evening  18:30  mail the setups list built on the day's NSE close
#   TA-Digest-Morning  08:30  mail it again before the open
#   TA-Watch           09:15  live alerts every 5 minutes until 15:30 (with gap-ups)
# Remove them with:  Unregister-ScheduledTask -TaskName TA-* -Confirm:$false

$repo = Split-Path -Parent $PSScriptRoot
$python = (Get-Command python).Source
$days = @("Monday", "Tuesday", "Wednesday", "Thursday", "Friday")

function Register-TA($name, $time, $arguments) {
    $action = New-ScheduledTaskAction -Execute $python -Argument "-m cli.main $arguments" -WorkingDirectory $repo
    $trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek $days -At $time
    $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 7)
    Register-ScheduledTask -TaskName $name -Action $action -Trigger $trigger -Settings $settings -Force | Out-Null
    Write-Output "Registered $name at $time : $arguments"
}

Register-TA "TA-Digest-Evening" "18:30" "alerts digest"
Register-TA "TA-Digest-Morning" "08:30" "alerts digest"
Register-TA "TA-Watch" "09:15" "alerts watch --every 5 --gaps"
