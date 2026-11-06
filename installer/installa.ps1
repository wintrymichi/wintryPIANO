# Installer di Wintry Piano per Windows 10/11.
# Uso: doppio clic su installa.bat (oppure: powershell -ExecutionPolicy Bypass -File installer\installa.ps1)
# Opzioni: -SoloYDP (scarica solo il pianoforte leggero)  -SenzaFFmpeg  -SenzaCollegamento  -FFmpegZip  -PythonNuGet

param(
    [switch]$SoloYDP,
    [switch]$SenzaFFmpeg,
    [switch]$SenzaCollegamento,
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

function Installa-PythonNuGet {
    # Pacchetto ufficiale python.org distribuito su NuGet: un semplice zip, senza Windows Installer.
    $url = "https://www.nuget.org/api/v2/package/python/$PyVersion"
    $zip = Join-Path $env:TEMP "python-$PyVersion-nuget.zip"
    try {
        Write-Host "      Scarico Python $PyVersion (pacchetto zip ufficiale)..."
        Invoke-WebRequest -Uri $url -OutFile $zip -UseBasicParsing
        if (Test-Path $NuGetDir) { Remove-Item $NuGetDir -Recurse -Force }
        Expand-Archive -Path $zip -DestinationPath $NuGetDir -Force
        Remove-Item $zip -Force -ErrorAction SilentlyContinue
        return (Test-Path $NuGetPython)
    } catch {
        Avviso "installazione di Python dallo zip non riuscita"
        return $false
    }
}

function Passo($n, $testo) { Write-Host ""; Write-Host "[$n/6] $testo" -ForegroundColor Cyan }
function Ok($testo) { Write-Host "      OK  $testo" -ForegroundColor Green }
function Avviso($testo) { Write-Host "      !   $testo" -ForegroundColor Yellow }
function Fallito($testo) {
    Write-Host ""
    Write-Host "ERRORE: $testo" -ForegroundColor Red
    Write-Host "Puoi rilanciare installa.bat: i passi già completati vengono saltati."
    exit 1
}

function Trova-Python312 {
    $candidati = @()
    if (Get-Command py -ErrorAction SilentlyContinue) {
        try {
            $p = & py -3.12 -c "import sys; print(sys.executable)" 2>$null
            if ($LASTEXITCODE -eq 0 -and $p) { $candidati += $p.Trim() }
        } catch {}
    }
    $candidati += $NuGetPython
    $candidati += "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe"
    $candidati += "$env:ProgramFiles\Python312\python.exe"
    foreach ($c in $candidati) {
        if ($c -and (Test-Path $c)) {
            $v = & $c -c "import sys, struct; print('%d.%d %d' % (sys.version_info[0], sys.version_info[1], struct.calcsize('P')*8))"
            if ($v -eq "3.12 64") { return $c }
        }
    }
    return $null
}

Write-Host "=============================================" -ForegroundColor Cyan
Write-Host "        Installazione di wintry piano" -ForegroundColor Cyan
Write-Host "=============================================" -ForegroundColor Cyan
Write-Host "Cartella: $Root"

# ---------------------------------------------------------------- 1. Python
Passo 1 "Python 3.12 (64 bit)"
$python = Trova-Python312
if ($PythonNuGet -and -not (Test-Path $NuGetPython)) {
    if (Installa-PythonNuGet) { $python = $NuGetPython }
} elseif ($PythonNuGet) {
    $python = $NuGetPython
}
if (-not $python) {
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        Write-Host "      Installo Python 3.12 con winget..."
        & winget install -e --id Python.Python.3.12 --scope user --silent --accept-package-agreements --accept-source-agreements | Out-Host
        $python = Trova-Python312
    }
}
if (-not $python) {
    $url = "https://www.python.org/ftp/python/$PyVersion/python-$PyVersion-amd64.exe"
    $exe = Join-Path $env:TEMP "python-$PyVersion-amd64.exe"
    try {
        Write-Host "      Scarico Python $PyVersion da python.org..."
        Invoke-WebRequest -Uri $url -OutFile $exe -UseBasicParsing
        Write-Host "      Installo Python (solo per questo utente)..."
        $proc = Start-Process -FilePath $exe -ArgumentList "/quiet InstallAllUsers=0 PrependPath=0 Include_launcher=1 Include_test=0" -Wait -PassThru
        if ($proc.ExitCode -ne 0) { Avviso "il setup di Python è terminato con codice $($proc.ExitCode), provo con lo zip" }
    } catch {
        Avviso "setup di Python non riuscito, provo con lo zip"
    }
    $python = Trova-Python312
}
if (-not $python) {
    if (Installa-PythonNuGet) { $python = $NuGetPython }
}
if (-not $python) { Fallito "non riesco a installare Python 3.12. Installalo da python.org e rilancia." }
Ok $python

# ---------------------------------------------------------- 2. ambiente .venv
Passo 2 "Ambiente Python del programma (.venv)"
$venvPy = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPy)) {
    & $python -m venv (Join-Path $Root ".venv")
    if ($LASTEXITCODE -ne 0) { Fallito "non riesco a creare l'ambiente .venv." }
}
Ok ".venv pronto"

# ---------------------------------------------------------------- 3. librerie
Passo 3 "Librerie (PySide6, mido, python-rtmidi, sounddevice, soundfile, numpy, tinysoundfont)"
& $venvPy -m pip install --disable-pip-version-check --upgrade pip | Out-Null
& $venvPy -m pip install --disable-pip-version-check --only-binary=:all: -r (Join-Path $Root "requirements.txt")
if ($LASTEXITCODE -ne 0) { Fallito "installazione delle librerie non riuscita." }
& $venvPy -c "import PySide6, mido, rtmidi, sounddevice, soundfile, numpy, tinysoundfont"
if ($LASTEXITCODE -ne 0) { Fallito "le librerie sono installate ma non si caricano." }
Ok "librerie installate"

# ------------------------------------------------------------------ 4. ffmpeg
Passo 4 "ffmpeg (per esportare in MP3)"
function Installa-FFmpegZip {
    $dest = Join-Path $Root "ffmpeg"
    $urls = @(
        "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip",
        "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip"
    )
    foreach ($url in $urls) {
        $zip = Join-Path $env:TEMP "wintry-ffmpeg.zip"
        $tmp = Join-Path $env:TEMP "wintry-ffmpeg"
        try {
            Write-Host "      Scarico ffmpeg da $url ..."
            Invoke-WebRequest -Uri $url -OutFile $zip -UseBasicParsing
            if (Test-Path $tmp) { Remove-Item $tmp -Recurse -Force }
            Expand-Archive -Path $zip -DestinationPath $tmp -Force
            $exe = Get-ChildItem -Path $tmp -Recurse -Filter ffmpeg.exe | Select-Object -First 1
            if (-not $exe) { throw "ffmpeg.exe non trovato nell'archivio" }
            if (Test-Path $dest) { Remove-Item $dest -Recurse -Force }
            New-Item -ItemType Directory -Path (Join-Path $dest "bin") -Force | Out-Null
            Copy-Item $exe.FullName (Join-Path $dest "bin\ffmpeg.exe")
            $lic = Get-ChildItem -Path $tmp -Recurse -Filter "LICENSE*" | Select-Object -First 1
            if ($lic) { Copy-Item $lic.FullName (Join-Path $dest "LICENSE.txt") }
            Remove-Item $zip, $tmp -Recurse -Force -ErrorAction SilentlyContinue
            return $true
        } catch {
            Avviso "download da $url non riuscito"
        }
    }
    return $false
}

$ffLocale = Join-Path $Root "ffmpeg\bin\ffmpeg.exe"
if ($SenzaFFmpeg) {
    Avviso "saltato su richiesta: potrai esportare solo in WAV"
} elseif ((Test-Path $ffLocale) -or ((-not $FFmpegZip) -and (Get-Command ffmpeg -ErrorAction SilentlyContinue))) {
    Ok "già presente"
} else {
    $fatto = $false
    if ((-not $FFmpegZip) -and (Get-Command winget -ErrorAction SilentlyContinue)) {
        & winget install -e --id Gyan.FFmpeg --silent --accept-package-agreements --accept-source-agreements | Out-Host
        $fatto = ($LASTEXITCODE -eq 0)
    }
    if (-not $fatto) { $fatto = Installa-FFmpegZip }
    if ($fatto) { Ok "ffmpeg installato" } else { Avviso "ffmpeg non installato: l'export WAV funziona comunque" }
}

# --------------------------------------------------- 5. suoni del pianoforte
Passo 5 "Suoni del pianoforte a coda (licenza CC BY 3.0, FreePats)"
if ($SoloYDP) {
    & $venvPy -m wintrypiano.soundfonts.download ydp
} else {
    Write-Host "      Salamander Grand Piano (~296 MB) e YDP Grand Piano (~36 MB): può volerci qualche minuto."
    & $venvPy -m wintrypiano.soundfonts.download
}
if ($LASTEXITCODE -ne 0) {
    Avviso "download dei suoni non completato. Rilancia installa.bat, oppure scegli il suono dal programma."
} else {
    Ok "suoni installati in $env:APPDATA\WintryPiano\soundfonts"
}

# ------------------------------------------------------------ 6. collegamento
Passo 6 "Collegamento sul desktop"
if ($SenzaCollegamento) {
    Avviso "saltato"
} else {
    try {
        $shell = New-Object -ComObject WScript.Shell
        $lnk = $shell.CreateShortcut((Join-Path ([Environment]::GetFolderPath("Desktop")) "Wintry Piano.lnk"))
        # Il pacchetto zip di Python non ha pythonw.exe: in quel caso uso python.exe
        # a finestra ridotta, e avvia.py chiude subito la console.
        $baseHome = (Get-Content (Join-Path $Root ".venv\pyvenv.cfg") | Where-Object { $_ -match '^\s*home\s*=' } | Select-Object -First 1) -replace '^\s*home\s*=\s*', ''
        if ($baseHome -and (Test-Path (Join-Path $baseHome.Trim() "pythonw.exe"))) {
            $lnk.TargetPath = Join-Path $Root ".venv\Scripts\pythonw.exe"
        } else {
            $lnk.TargetPath = Join-Path $Root ".venv\Scripts\python.exe"
            $lnk.WindowStyle = 7
        }
        $lnk.Arguments = '"' + (Join-Path $Root "avvia.py") + '"'
        $lnk.WorkingDirectory = $Root
        $lnk.Description = "wintry piano"
        $lnk.Save()
        Ok "creato 'Wintry Piano' sul desktop"
    } catch {
        Avviso "non riesco a creare il collegamento: avvia il programma con avvia.py"
    }
}

Write-Host ""
Write-Host "Installazione completata." -ForegroundColor Green
Write-Host "Avvia con il collegamento sul desktop oppure con:  .venv\Scripts\python.exe avvia.py"
Write-Host "Per provare senza piano collegato:                  .venv\Scripts\python.exe avvia.py --demo"
