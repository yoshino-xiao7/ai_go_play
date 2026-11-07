Option Explicit

Dim shell, files, workspace, runtime, powershell, errorLog, command
Dim argument, exitCode, details, reader, launchError
Set shell = CreateObject("WScript.Shell")
Set files = CreateObject("Scripting.FileSystemObject")
workspace = files.GetParentFolderName(WScript.ScriptFullName)
runtime = files.BuildPath(shell.ExpandEnvironmentStrings("%LOCALAPPDATA%"), "Manju")
If Not files.FolderExists(runtime) Then files.CreateFolder(runtime)
runtime = files.BuildPath(runtime, "run")
If Not files.FolderExists(runtime) Then files.CreateFolder(runtime)
errorLog = files.BuildPath(runtime, "launcher-" & files.GetTempName & ".log")
powershell = shell.ExpandEnvironmentStrings("%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe")
command = QuoteArgument(powershell) & " -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File " & QuoteArgument(files.BuildPath(workspace, "start.ps1"))
For Each argument In WScript.Arguments
    command = command & " " & QuoteArgument(argument)
Next
command = command & " -ErrorLogPath " & QuoteArgument(errorLog)

On Error Resume Next
exitCode = shell.Run(command, 0, True)
launchError = Err.Description
If Err.Number <> 0 Then exitCode = 1
On Error GoTo 0

If exitCode <> 0 Then
    details = launchError
    If files.FileExists(errorLog) Then
        Set reader = files.OpenTextFile(errorLog, 1, False, -1)
        details = reader.ReadAll
        reader.Close
    End If
    If Len(details) = 0 Then details = "Run start.ps1 in PowerShell to read the startup error."
    MsgBox "Manju could not start." & vbCrLf & vbCrLf & details & vbCrLf & vbCrLf & "Logs: " & runtime, vbOKOnly + vbCritical, "Manju"
End If
WScript.Quit exitCode

Function QuoteArgument(value)
    Dim result, slashes, index, character
    result = Chr(34)
    slashes = 0
    For index = 1 To Len(value)
        character = Mid(value, index, 1)
        If character = "\" Then
            slashes = slashes + 1
        Else
            If character = Chr(34) Then
                result = result & String(slashes * 2 + 1, "\") & character
            Else
                result = result & String(slashes, "\") & character
            End If
            slashes = 0
        End If
    Next
    QuoteArgument = result & String(slashes * 2, "\") & Chr(34)
End Function
