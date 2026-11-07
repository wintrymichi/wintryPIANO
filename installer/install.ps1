# Wintry Piano installer for Windows 10/11.
# Usage: double-click install.bat (or: powershell -ExecutionPolicy Bypass -File installer\install.ps1)
# Options: -YdpOnly (download only the light piano)  -NoFFmpeg  -NoShortcut  -FFmpegZip  -PythonNuGet

param(
    [switch]$YdpOnly,
    [switch]$NoFFmpeg,
    [switch]$NoShortcut,
    [switch]$FFmpegZip,
    [switch]$PythonNuGet
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
$PyVersion = "3.12.10"
$NuGetDir = Join-Path $env:LOCALAPPDATA "WintryPiano\python312"
$NuGetPython = Join-Path $NuGetDir "tools\python.exe"

function Install-PythonNuGet {
    # Official python.org package published on NuGet: a plain zip, no Windows Installer.
    $url = "https://www.nuget.org/api/v2/package/python/$PyVersion"
    $zip = Join-Path $env:TEMP "python-$PyVersion-nuget.zip"
    try {
        Write-Host "      Downloading Python $PyVersion (official zip package)..."
        Invoke-WebRequest -Uri $url -OutFile $zip -UseBasicParsing
        if (Test-Path $NuGetDir) { Remove-Item $NuGetDir -Recurse -Force }
        Expand-Archive -Path $zip -DestinationPath $NuGetDir -Force
        Remove-Item $zip -Force -ErrorAction SilentlyContinue
        return (Test-Path $NuGetPython)
    } catch {
        Warn "installing Python from the zip failed"
        return $false
    }
}

function Step($n, $text) { Write-Host ""; Write-Host "[$n/6] $text" -ForegroundColor Cyan }
function Ok($text) { Write-Host "      OK  $text" -ForegroundColor Green }
function Warn($text) { Write-Host "      !   $text" -ForegroundColor Yellow }
function Fail($text) {
    Write-Host ""
    Write-Host "ERROR: $text" -ForegroundColor Red
    Write-Host "You can run install.bat again: steps already completed are skipped."
    exit 1
}

function Find-Python312 {
    $candidates = @()
    if (Get-Command py -ErrorAction SilentlyContinue) {
        try {
            $p = & py -3.12 -c "import sys; print(sys.executable)" 2>$null
            if ($LASTEXITCODE -eq 0 -and $p) { $candidates += $p.Trim() }
        } catch {}
    }
    $candidates += $NuGetPython
    $candidates += "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe"
    $candidates += "$env:ProgramFiles\Python312\python.exe"
    foreach ($c in $candidates) {
        if ($c -and (Test-Path $c)) {
            $v = & $c -c "import sys, struct; print('%d.%d %d' % (sys.version_info[0], sys.version_info[1], struct.calcsize('P')*8))"
            if ($v -eq "3.12 64") { return $c }
        }
    }
    return $null
}

Write-Host "=============================================" -ForegroundColor Cyan
Write-Host "          Installing wintry piano" -ForegroundColor Cyan
Write-Host "=============================================" -ForegroundColor Cyan
Write-Host "Folder: $Root"

# ---------------------------------------------------------------- 1. Python
Step 1 "Python 3.12 (64 bit)"
$python = Find-Python312
if ($PythonNuGet -and -not (Test-Path $NuGetPython)) {
    if (Install-PythonNuGet) { $python = $NuGetPython }
} elseif ($PythonNuGet) {
    $python = $NuGetPython
}
if (-not $python) {
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        Write-Host "      Installing Python 3.12 with winget..."
        & winget install -e --id Python.Python.3.12 --scope user --silent --accept-package-agreements --accept-source-agreements | Out-Host
        $python = Find-Python312
    }
}
if (-not $python) {
    $url = "https://www.python.org/ftp/python/$PyVersion/python-$PyVersion-amd64.exe"
    $exe = Join-Path $env:TEMP "python-$PyVersion-amd64.exe"
    try {
        Write-Host "      Downloading Python $PyVersion from python.org..."
        Invoke-WebRequest -Uri $url -OutFile $exe -UseBasicParsing
        Write-Host "      Installing Python (for this user only)..."
        $proc = Start-Process -FilePath $exe -ArgumentList "/quiet InstallAllUsers=0 PrependPath=0 Include_launcher=1 Include_test=0" -Wait -PassThru
        if ($proc.ExitCode -ne 0) { Warn "the Python setup exited with code $($proc.ExitCode), trying the zip" }
    } catch {
        Warn "the Python setup failed, trying the zip"
    }
    $python = Find-Python312
}
if (-not $python) {
    if (Install-PythonNuGet) { $python = $NuGetPython }
}
if (-not $python) { Fail "could not install Python 3.12. Install it from python.org and run this again." }
Ok $python

# -------------------------------------------------------- 2. .venv environment
Step 2 "The program's Python environment (.venv)"
$venvPy = Join-Path $Root ".venv\Scripts\python.exe"
if (Test-Path $venvPy) {
    # A .venv created with a Python that no longer exists (or is not visible) does not start: recreate it.
    $okVenv = $false
    try {
        $out = & $venvPy -c "import sys; print(sys.version_info[:2] == (3, 12))" 2>$null
        $okVenv = ($LASTEXITCODE -eq 0 -and "$out".Trim() -eq "True")
    } catch {}
    if (-not $okVenv) {
        Warn "the existing .venv environment does not work: recreating it"
        Remove-Item (Join-Path $Root ".venv") -Recurse -Force
    }
}
if (-not (Test-Path $venvPy)) {
    & $python -m venv (Join-Path $Root ".venv")
    if ($LASTEXITCODE -ne 0) { Fail "could not create the .venv environment." }
}
Ok ".venv ready"

# --------------------------------------------------------------- 3. libraries
Step 3 "Libraries (PySide6, mido, python-rtmidi, sounddevice, soundfile, numpy, tinysoundfont)"
& $venvPy -m pip install --disable-pip-version-check --upgrade pip | Out-Null
& $venvPy -m pip install --disable-pip-version-check --only-binary=:all: -r (Join-Path $Root "requirements.txt")
if ($LASTEXITCODE -ne 0) { Fail "installing the libraries failed." }
& $venvPy -c "import PySide6, mido, rtmidi, sounddevice, soundfile, numpy, tinysoundfont"
if ($LASTEXITCODE -ne 0) { Fail "the libraries are installed but do not load." }
Ok "libraries installed"

# ------------------------------------------------------------------ 4. ffmpeg
Step 4 "ffmpeg (for MP3 export)"
function Install-FFmpegZip {
    $dest = Join-Path $Root "ffmpeg"
    $urls = @(
        "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip",
        "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip"
    )
    foreach ($url in $urls) {
        $zip = Join-Path $env:TEMP "wintry-ffmpeg.zip"
        $tmp = Join-Path $env:TEMP "wintry-ffmpeg"
        try {
            Write-Host "      Downloading ffmpeg from $url ..."
            Invoke-WebRequest -Uri $url -OutFile $zip -UseBasicParsing
            if (Test-Path $tmp) { Remove-Item $tmp -Recurse -Force }
            Expand-Archive -Path $zip -DestinationPath $tmp -Force
            $exe = Get-ChildItem -Path $tmp -Recurse -Filter ffmpeg.exe | Select-Object -First 1
            if (-not $exe) { throw "ffmpeg.exe not found in the archive" }
            if (Test-Path $dest) { Remove-Item $dest -Recurse -Force }
            New-Item -ItemType Directory -Path (Join-Path $dest "bin") -Force | Out-Null
            Copy-Item $exe.FullName (Join-Path $dest "bin\ffmpeg.exe")
            $lic = Get-ChildItem -Path $tmp -Recurse -Filter "LICENSE*" | Select-Object -First 1
            if ($lic) { Copy-Item $lic.FullName (Join-Path $dest "LICENSE.txt") }
            Remove-Item $zip, $tmp -Recurse -Force -ErrorAction SilentlyContinue
            return $true
        } catch {
            Warn "download from $url failed"
        }
    }
    return $false
}

$ffLocal = Join-Path $Root "ffmpeg\bin\ffmpeg.exe"
if ($NoFFmpeg) {
    Warn "skipped on request: you can only export WAV"
} elseif ((Test-Path $ffLocal) -or ((-not $FFmpegZip) -and (Get-Command ffmpeg -ErrorAction SilentlyContinue))) {
    Ok "already installed"
} else {
    $done = $false
    if ((-not $FFmpegZip) -and (Get-Command winget -ErrorAction SilentlyContinue)) {
        & winget install -e --id Gyan.FFmpeg --silent --accept-package-agreements --accept-source-agreements | Out-Host
        $done = ($LASTEXITCODE -eq 0)
    }
    if (-not $done) { $done = Install-FFmpegZip }
    if ($done) { Ok "ffmpeg installed" } else { Warn "ffmpeg not installed: WAV export still works" }
}

# ------------------------------------------------------------- 5. piano sounds
Step 5 "Grand piano sounds (CC BY 3.0 license, FreePats)"
if ($YdpOnly) {
    & $venvPy -m wintrypiano.soundfonts.download ydp
} else {
    Write-Host "      Salamander Grand Piano (~296 MB) and YDP Grand Piano (~36 MB): this can take a few minutes."
    & $venvPy -m wintrypiano.soundfonts.download
}
if ($LASTEXITCODE -ne 0) {
    Warn "the sound download did not finish. Run install.bat again, or pick a sound inside the program."
} else {
    Ok "sounds installed in $env:APPDATA\WintryPiano\soundfonts"
}

# ------------------------------------------------------------- 6. shortcut
Step 6 "Desktop shortcut"
if ($NoShortcut) {
    Warn "skipped"
} else {
    try {
        $shell = New-Object -ComObject WScript.Shell
        $lnk = $shell.CreateShortcut((Join-Path ([Environment]::GetFolderPath("Desktop")) "Wintry Piano.lnk"))
        # The Python zip package has no pythonw.exe: then use python.exe
        # minimised, and start.py closes the console right away.
        $baseHome = (Get-Content (Join-Path $Root ".venv\pyvenv.cfg") | Where-Object { $_ -match '^\s*home\s*=' } | Select-Object -First 1) -replace '^\s*home\s*=\s*', ''
        if ($baseHome -and (Test-Path (Join-Path $baseHome.Trim() "pythonw.exe"))) {
            $lnk.TargetPath = Join-Path $Root ".venv\Scripts\pythonw.exe"
        } else {
            $lnk.TargetPath = Join-Path $Root ".venv\Scripts\python.exe"
            $lnk.WindowStyle = 7
        }
        $lnk.Arguments = '"' + (Join-Path $Root "start.py") + '"'
        $lnk.WorkingDirectory = $Root
        $lnk.Description = "wintry piano"
        $lnk.Save()
        Ok "created 'Wintry Piano' on the desktop"
    } catch {
        Warn "could not create the shortcut: start the program with start.py"
    }
}

Write-Host ""
Write-Host "Installation complete." -ForegroundColor Green
Write-Host "Start it from the desktop shortcut or with:  .venv\Scripts\python.exe start.py"
Write-Host "To try it without a piano connected:        .venv\Scripts\python.exe start.py --demo"
