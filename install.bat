@echo off
rem Wintry Piano installer: double-click this file.
rem Installs Python 3.12 (if missing), the libraries, ffmpeg and downloads the piano sounds.
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0installer\install.ps1" %*
echo.
pause
