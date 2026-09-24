@echo off
REM Creates a Desktop shortcut that launches this app via run.bat.
REM Re-run it after moving the folder to repoint the shortcut at the new path.
setlocal
cd /d "%~dp0"

set "TARGET=%~dp0run.bat"
set "ICON=%~dp0assets\app.ico"

powershell -NoProfile -Command ^
  "$ws = New-Object -ComObject WScript.Shell;" ^
  "$lnk = $ws.CreateShortcut([IO.Path]::Combine([Environment]::GetFolderPath('Desktop'),'UHV-SEM Spectrum.lnk'));" ^
  "$lnk.TargetPath = '%TARGET%';" ^
  "$lnk.WorkingDirectory = '%~dp0';" ^
  "if (Test-Path '%ICON%') { $lnk.IconLocation = '%ICON%' };" ^
  "$lnk.Description = 'UHV-SEM Energetic Spectrum';" ^
  "$lnk.Save();"

if errorlevel 1 (
    echo Failed to create the shortcut.
    pause
    exit /b 1
)
echo Desktop shortcut "UHV-SEM Spectrum" created.
pause
endlocal
