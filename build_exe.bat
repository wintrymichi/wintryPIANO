@echo off
rem Crea "dist\Wintry Piano\Wintry Piano.exe" con i suoni del pianoforte inclusi.
rem Prima esegui installa.bat (crea .venv con tutte le librerie).
cd /d "%~dp0"
set PY=.venv\Scripts\python.exe
if not exist %PY% (
  echo Esegui prima installa.bat
  pause
  exit /b 1
)
%PY% -m pip install --disable-pip-version-check "pyinstaller>=6.10"
%PY% -m wintrypiano.soundfonts.download --dest assets\soundfonts
%PY% -m PyInstaller --noconfirm --clean --windowed --name "Wintry Piano" ^
  --add-data "assets;assets" ^
  --collect-binaries tinysoundfont ^
  --hidden-import mido.backends.rtmidi --hidden-import rtmidi ^
  avvia.py
set OUT=dist\Wintry Piano\_internal
if not exist "%OUT%\_sounddevice_data\portaudio-binaries\libportaudio64bit-asio.dll" echo ATTENZIONE: manca la DLL di PortAudio, aggiorna pyinstaller-hooks-contrib
if not exist "%OUT%\_soundfile_data\libsndfile_x64.dll" echo ATTENZIONE: manca libsndfile_x64.dll, aggiorna pyinstaller-hooks-contrib
echo.
echo Fatto: dist\Wintry Piano\Wintry Piano.exe
pause
