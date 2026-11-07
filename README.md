# ❄ wintry piano

Programma per Windows 10/11 per suonare un piano MIDI USB con un suono di pianoforte a coda realistico, registrarlo e poi cantarci sopra con il microfono. Tutto avviene nello stesso programma, senza DAW né plugin VST.

Il flusso è in tre passi: **1. suona e registra il piano**, **2. canta**, **3. esporta**.

## Installazione (consigliata)

1. Scarica o clona questa cartella.
2. Fai doppio clic su **`installa.bat`**. L'installer:
   - installa Python 3.12 a 64 bit, se manca (con winget, oppure da python.org);
   - crea l'ambiente `.venv` e installa tutte le librerie;
   - installa ffmpeg per l'export in MP3 (con winget, oppure scaricandolo in `ffmpeg\` se winget manca);
   - scarica i suoni del pianoforte (Salamander Grand Piano, circa 296 MB, e YDP Grand Piano, circa 36 MB);
   - crea il collegamento "Wintry Piano" sul desktop.
3. Avvia il programma con il collegamento oppure con **`avvia.py`** (doppio clic, oppure `.venv\Scripts\python.exe avvia.py`).

Opzioni dell'installer: `installa.bat -SoloYDP` scarica solo il pianoforte leggero, `-SenzaFFmpeg` salta ffmpeg, `-SenzaCollegamento` non crea il collegamento.

Per provare tutto senza piano collegato: `avvia.py --demo`, oppure *Impostazioni → Modalità demo*.

> Serve **Python 3.12**: python-rtmidi e tinysoundfont non hanno ancora i pacchetti precompilati per Python 3.13 su Windows.

## Suoni del pianoforte e licenze

| Suono | Licenza | Note |
|---|---|---|
| Salamander Grand Piano V3 (Yamaha C5, Alexander Holm, conversione SF2 di FreePats) | CC BY 3.0 | Il più realistico, ed è quello predefinito. Occupa 1,2 GB su disco e circa 2,5 GB di RAM: con meno di 8 GB di RAM conviene YDP |
| YDP Grand Piano (FreePats) | CC BY 3.0 | Più leggero |

Fonte: <https://freepats.zenvoid.org/Piano/acoustic-grand-piano.html>

La licenza CC BY 3.0 permette di ridistribuirli citando l'autore. Non sono nel repository Git solo perché superano il limite di 100 MB per file di GitHub: li scaricano l'installer, il programma stesso (al primo avvio, se mancano) e `build_exe.bat`, che li mette dentro l'exe. Da *Impostazioni → Suono del pianoforte* puoi scegliere anche un tuo file `.sf2` o `.sf3`.

## Uso

- **Dispositivi** (menu): ingresso MIDI, microfono e uscita audio. Il driver migliore viene scelto da solo (ASIO se c'è, altrimenti WASAPI), e le scelte restano salvate al riavvio. Se colleghi o scolleghi il piano MIDI, il programma se ne accorge da solo. Se perdi l'uscita audio, riprova a riaprirla ogni 2 secondi.
- **Passo 1**: suona, poi usa Registra, Stop e Riascolta. Hai volume, riverbero, metronomo con i bpm e un conto alla rovescia di 4 battiti. La take si salva come `piano.mid`, quindi puoi cambiare suono senza risuonare. Il metronomo non finisce mai nell'export. Con **«Canta mentre suoni»** il microfono si registra nella stessa take: piano in `piano.mid`, voce in `voce.wav`, già allineati (usa le cuffie, così il piano non rientra nel microfono).
- **Passo 2**: con le cuffie, Registra voce fa ripartire il piano dall'inizio. Vedi il livello del microfono, con un avviso se satura. L'ascolto del microfono in cuffia è spento di default. Puoi rifare la voce senza toccare il piano.
- **Passo 3**: imposti volume di piano e voce e il riverbero sulla voce, ascolti il mix ed esporti in WAV (24 bit), MP3, oppure il solo piano in MIDI (`.mid`). Il mix viene abbassato da solo se supererebbe -1 dBFS, così non c'è clipping.
- **Importare un MIDI o una canzone** (menu *File*):
  - *Importa MIDI come piano* usa un file `.mid` come take del piano: suona col pianoforte scelto, tutti i canali tranne la batteria. Il bpm viene preso dal file.
  - *Importa audio (MP3, WAV…)* aggiunge una canzone o una base come traccia separata (MP3, WAV, FLAC, OGG, e con ffmpeg anche M4A). Ha il suo volume al passo 3, finisce nel mix e nell'export, e suona mentre registri il piano o la voce (si può spegnere al passo 1).
  - *Sincronizza tracce* mostra le forme d'onda di piano, voce e audio importato. Il piano è il riferimento: le altre tracce si trascinano col mouse (Maiusc per lo spostamento fine) o si spostano in millisecondi, e si ascolta da qualsiasi punto. *Allinea automaticamente* confronta le note del MIDI con gli attacchi dell'audio e trova lo spostamento giusto; con *Correggi anche la velocità del MIDI* trova anche la velocità (dall'80% al 125%), utile quando il MIDI ha un tempo un po' diverso dalla registrazione.
- **Piano e voce sempre a tempo**: ogni nota viene registrata nell'istante in cui premi il tasto (il programma toglie la latenza dell'uscita audio), e la voce viene spostata della latenza di microfono e cuffie riportata dal driver. Se senti ancora uno scarto costante, correggilo in *Impostazioni* (correzione manuale della voce in ms).
- **Ascoltarsi in cuffia**: «Ascoltati in cuffia mentre canti» (passo 1 con «Canta mentre suoni», e passo 2). Il ritardo è il minimo possibile: un solo buffer oltre alla latenza del driver, ed è mostrato in ms. Per trovare il buffer più basso che regge sul tuo PC: `.venv\Scripts\python -m wintrypiano.audio.latency_test --salva` (a programma chiuso).
- **Impostazioni**: driver, WASAPI esclusivo, buffer audio con la latenza stimata in ms, correzione manuale della voce in ms e volume del metronomo.

### Progetti

Ogni progetto è una cartella (di default in `Documenti\Wintry Piano`):

```
progetto.json   impostazioni (bpm, volumi, riverberi, compensazione latenza…)
piano.mid       take del piano
voce.wav        take della voce (mono, senza effetti)
base.flac       audio importato (se c'è), convertito una volta sola
.recovery/      file scritti durante la registrazione
```

Prima di sovrascrivere una take il programma chiede sempre conferma. Durante la registrazione il piano e la voce vengono scritti su disco di continuo in `.recovery/`. Se il programma si chiude male, al riavvio propone di recuperarli.

Il log degli errori si trova in `%APPDATA%\WintryPiano\wintrypiano.log`.

## Creare l'exe con PyInstaller

Dopo `installa.bat`, esegui **`build_exe.bat`**. Equivale a:

```bat
.venv\Scripts\python -m pip install "pyinstaller>=6.10"
.venv\Scripts\python -m wintrypiano.soundfonts.download --dest assets\soundfonts
.venv\Scripts\python -m PyInstaller --noconfirm --clean --windowed --name "Wintry Piano" ^
  --add-data "assets;assets" --collect-binaries tinysoundfont ^
  --hidden-import mido.backends.rtmidi --hidden-import rtmidi avvia.py
```

Il risultato è in `dist\Wintry Piano\Wintry Piano.exe`. Uso la modalità a cartella e non `--onefile`, perché il soundfont pesa centinaia di MB e andrebbe estratto a ogni avvio.

DLL e moduli binari da includere (PyInstaller li prende da solo tramite i suoi hook, e lo script controlla che ci siano):

- `_sounddevice_data\portaudio-binaries\libportaudio64bit.dll` e `libportaudio64bit-asio.dll` (PortAudio, con e senza ASIO)
- `_soundfile_data\libsndfile_x64.dll` (libsndfile)
- `tinysoundfont\_tinysoundfont.cp312-win_amd64.pyd`
- `rtmidi\_rtmidi.cp312-win_amd64.pyd` (usa `winmm.dll` di Windows)
- le DLL di Qt6 di PySide6
- facoltativo: `ffmpeg.exe` accanto all'exe, per l'MP3 se ffmpeg non è nel PATH

## Sviluppo e test

```bat
.venv\Scripts\python -m pip install -r requirements-dev.txt
.venv\Scripts\python -m pytest
```

I test non richiedono hardware e coprono progetto, salvataggio MIDI, render del soundfont (con un piccolo `.sf2` generato al volo), mix, export, import di MIDI e audio, allineamento automatico (anche della velocità), recupero dopo un crash, motore audio (conto alla rovescia, metronomo, compensazione della latenza, monitor) e modalità demo. `test_gui_smoke.py` prova l'intero flusso nella GUI e parte solo se c'è un dispositivo audio.

Struttura del codice:

```
wintrypiano/
  audio/      dispositivi (ASIO/WASAPI) e motore in tempo reale
  midi/       ingresso MIDI USB e modalità demo
  core/       sintetizzatore, riverbero, metronomo, MIDI, mix, export, progetto, recupero,
              import di audio e MIDI, allineamento automatico
  soundfonts/ catalogo e download dei pianoforti
  gui/        finestra principale, impostazioni, scelta del suono
```
