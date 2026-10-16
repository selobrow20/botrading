$WshShell = New-Object -comObject WScript.Shell
$Desktop = [System.Environment]::GetFolderPath('Desktop')
$Shortcut = $WshShell.CreateShortcut("$Desktop\Botrading Cockpit.lnk")
$Shortcut.TargetPath = "$PSScriptRoot\Botrading.exe"
$Shortcut.WorkingDirectory = "$PSScriptRoot"
$Shortcut.IconLocation = "$PSScriptRoot\app_icon.ico"
$Shortcut.Description = "Botrading Unified Command Center & Trading Terminal"
$Shortcut.Save()
Write-Host "[SUKSES] Shortcut 'Botrading Cockpit' berhasil dibuat di Desktop Windows!" -ForegroundColor Green
