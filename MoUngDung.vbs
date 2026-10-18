Option Explicit
Dim fs, sh, root, exe, py, script
Set fs = CreateObject("Scripting.FileSystemObject")
Set sh = CreateObject("WScript.Shell")
root = fs.GetParentFolderName(WScript.ScriptFullName)
exe = root & "\posture_model\dist\PostureMonitor\PostureMonitor.exe"
If fs.FileExists(exe) Then
  sh.Run Chr(34) & exe & Chr(34), 1, False
Else
  py = root & "\.venv\Scripts\pythonw.exe"
  If Not fs.FileExists(py) Then
    py = fs.GetParentFolderName(root) & "\tools\camera-check-venv\Scripts\pythonw.exe"
  End If
  If Not fs.FileExists(py) Then
    MsgBox "Chua cai ung dung. Xem api_handover\desktop-app.md hoac nhan thu muc PostureMonitor da dong goi.", 48, "Posture Monitor"
    WScript.Quit 1
  End If
  script = root & "\posture_model\app.py"
  sh.CurrentDirectory = root
  sh.Run Chr(34) & py & Chr(34) & " " & Chr(34) & script & Chr(34), 0, False
End If
