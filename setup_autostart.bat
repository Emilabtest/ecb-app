@echo off
REM setup_autostart.bat -- One-time setup per PC: run the server watchdog at
REM every logon + enable Stereo Mix capture (for PC-output audio in streams).
REM Portable: uses this machine's own paths, so the same file works on other
REM PCs -- just copy the project and run this once.
setlocal
set "PROJ=%~dp0"
set "PROJ=%PROJ:~0,-1%"
set "STARTUP=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
if not exist "%STARTUP%" (
  echo Startup folder not found: %STARTUP%
  exit /b 1
)
> "%STARTUP%\LeiturgiaWatchdog.vbs" echo Set sh = CreateObject("WScript.Shell")
>> "%STARTUP%\LeiturgiaWatchdog.vbs" echo sh.Run "powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File ""%PROJ%\watchdog.ps1""", 0, False
echo Installed: %STARTUP%\LeiturgiaWatchdog.vbs
wscript "%STARTUP%\LeiturgiaWatchdog.vbs"
echo Watchdog started. It will also run automatically at every logon.
echo.
echo Audio setup: enabling Stereo Mix capture (admin approval may pop up)...
powershell -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "%PROJ%\setup_audio.ps1"
echo Done. Copy this project to other PCs and run setup_autostart.bat once there.
endlocal
