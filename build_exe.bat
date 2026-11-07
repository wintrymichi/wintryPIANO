@echo off
rem Builds "dist\Wintry Piano\Wintry Piano.exe" with the piano sounds included.
rem Run install.bat first (it creates .venv with all the libraries).
cd /d "%~dp0"
set PY=.venv\Scripts\python.exe
if not exist %PY% (
  echo Run install.bat first
  pause
  exit /b 1
)
%PY% -m pip install --disable-pip-version-check "pyinstaller>=6.10"
%PY% -m wintrypiano.soundfonts.download --dest assets\soundfonts
%PY% -m PyInstaller --noconfirm --clean --windowed --name "Wintry Piano" ^
  --add-data "assets;assets" ^
  --collect-binaries tinysoundfont ^
  --hidden-import mido.backends.rtmidi --hidden-import rtmidi ^
  start.py
set OUT=dist\Wintry Piano\_internal
if not exist "%OUT%\_sounddevice_data\portaudio-binaries\libportaudio64bit-asio.dll" echo WARNING: the PortAudio DLL is missing, update pyinstaller-hooks-contrib
if not exist "%OUT%\_soundfile_data\libsndfile_x64.dll" echo WARNING: libsndfile_x64.dll is missing, update pyinstaller-hooks-contrib
echo.
echo Done: dist\Wintry Piano\Wintry Piano.exe
pause
