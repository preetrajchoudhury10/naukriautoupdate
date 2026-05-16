' Runs Python script silently (no console window)
Dim shell
Set shell = CreateObject("WScript.Shell")
shell.Run "python naukri_updater.py", 0, False
Set shell = Nothing
