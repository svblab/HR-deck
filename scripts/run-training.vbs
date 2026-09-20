' Запуск UX-теста двойным щелчком.
' Обычный запуск: двойной щелчок по run-training.vbs
' Сброс БД (без UI): wscript.exe run-training.vbs -Clean

Option Explicit

Dim shell, fso, scriptDir, psCommand, arg, windowStyle

Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)

' Окно PowerShell видно только при ошибке (скрипт сам делает pause).
windowStyle = 1

psCommand = "powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle " & windowStyle _
    & " -File """ & scriptDir & "\run-training.ps1"""

For Each arg In WScript.Arguments
    psCommand = psCommand & " " & arg
Next

shell.Run psCommand, windowStyle, True
