$TaskName = "NaukriProfileUpdater"
$ScriptPath = "$PSScriptRoot\run_updater.bat"
$Action8AM = New-ScheduledTaskAction -Execute $ScriptPath
$Action5PM = New-ScheduledTaskAction -Execute $ScriptPath

$Trigger8AM = New-ScheduledTaskTrigger -Daily -At "08:00AM"
$Trigger5PM = New-ScheduledTaskTrigger -Daily -At "05:00PM"

$Settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable

Register-ScheduledTask -TaskName $TaskName `
    -Action @($Action8AM, $Action5PM) `
    -Trigger @($Trigger8AM, $Trigger5PM) `
    -Settings $Settings `
    -RunLevel Highest `
    -User $env:USERNAME `
    -Force

Write-Host "Scheduled task '$TaskName' created to run at 8:00 AM and 5:00 PM daily."
