Option Explicit

Dim shell, fileSystem, baseDirectory, batchFile, logFile
Dim command, exitCode

Set shell = CreateObject("WScript.Shell")
Set fileSystem = CreateObject("Scripting.FileSystemObject")

baseDirectory = fileSystem.GetParentFolderName(WScript.ScriptFullName)
batchFile = fileSystem.BuildPath(baseDirectory, "run.bat")
logFile = fileSystem.BuildPath(baseDirectory, "DocSwift-startup.log")

shell.Environment("PROCESS")("DOCSWIFT_NO_PAUSE") = "1"
command = shell.ExpandEnvironmentStrings("%ComSpec%") & _
    " /D /S /C " & Quote(Quote(batchFile) & _
    " --console > " & Quote(logFile) & " 2>&1")

exitCode = shell.Run(command, 0, True)

If exitCode <> 0 Then
    shell.Popup "DocSwift failed to start." & vbCrLf & _
        "See log: " & logFile, 0, "DocSwift", 16
ElseIf fileSystem.FileExists(logFile) Then
    On Error Resume Next
    fileSystem.DeleteFile logFile, True
    On Error GoTo 0
End If

Function Quote(value)
    Quote = Chr(34) & value & Chr(34)
End Function
