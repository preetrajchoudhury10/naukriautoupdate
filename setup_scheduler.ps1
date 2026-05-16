$TaskName = "NaukriUpdaterService"
$ScriptPath = "$PSScriptRoot\run_updater.vbs"
$WorkingDir = $PSScriptRoot

$Action = New-ScheduledTaskAction -Execute "wscript.exe" -Argument "`"$ScriptPath`"" -WorkingDirectory $WorkingDir

$Trigger = New-ScheduledTaskTrigger -AtStartup

$Settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew

$Principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -RunLevel Highest

Register-ScheduledTask -TaskName $TaskName `
    -Action $Action `
    -Trigger $Trigger `
    -Settings $Settings `
    -Principal $Principal `
    -Force

Write-Host "Task '$TaskName' created!"
Write-Host "Runs at Windows startup silently in background."
Write-Host "Built-in scheduler handles 8AM and 5PM updates."
Write-Host "Telegram commands: /manualrun, /status, /help"
Write-Host "Web UI: http://127.0.0.1:8080"
Write-Host ""
Write-Host "To start now: Start-ScheduledTask -TaskName '$TaskName'"
Write-Host "To stop: Stop-ScheduledTask -TaskName '$TaskName'"
