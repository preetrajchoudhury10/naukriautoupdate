$TaskName = "NaukriProfileUpdater"
$ScriptPath = "$PSScriptRoot\run_updater.vbs"
$WorkingDir = $PSScriptRoot

$Action = New-ScheduledTaskAction -Execute "wscript.exe" -Argument "`"$ScriptPath`"" -WorkingDirectory $WorkingDir

$Trigger8AM = New-ScheduledTaskTrigger -Daily -At "08:00AM"
$Trigger5PM = New-ScheduledTaskTrigger -Daily -At "05:00PM"

$Settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew

$Principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -RunLevel Highest

Register-ScheduledTask -TaskName $TaskName `
    -Action $Action `
    -Trigger @($Trigger8AM, $Trigger5PM) `
    -Settings $Settings `
    -Principal $Principal `
    -Force

Write-Host "Task '$TaskName' created!"
Write-Host "Runs at: 8:00 AM and 5:00 PM daily"
Write-Host "If PC is off at scheduled time, runs as soon as PC turns on (StartWhenAvailable)"
Write-Host ""
Write-Host "To test: Run this in PowerShell:"
Write-Host "  Start-ScheduledTask -TaskName '$TaskName'"
