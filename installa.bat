@echo off
rem Installer di Wintry Piano: doppio clic su questo file.
rem Installa Python 3.12 (se manca), le librerie, ffmpeg e scarica i suoni del pianoforte.
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0installer\installa.ps1" %*
echo.
pause
