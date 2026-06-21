# 创建桌面快捷方式到 start_gui.bat
$WshShell = New-Object -ComObject WScript.Shell
$DesktopPath = [Environment]::GetFolderPath("Desktop")
$ShortcutPath = Join-Path $DesktopPath "novel_agent.lnk"
$AppDir = Split-Path -Parent $MyInvocation.MyCommand.Path

$Shortcut = $WshShell.CreateShortcut($ShortcutPath)
$Shortcut.TargetPath = Join-Path $AppDir "start_gui.bat"
$Shortcut.WorkingDirectory = $AppDir
$Shortcut.Description = "novel_agent - AI Novel Writing Tool"
$Shortcut.IconLocation = "imageres.dll, 168"
$Shortcut.Save()

Write-Host "[OK] Desktop shortcut created: $ShortcutPath"
