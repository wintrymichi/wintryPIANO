# Soundfont inclusi nel .exe

Questa cartella viene riempita da `build_exe.bat` (o da
`python -m wintrypiano.soundfonts.download --dest assets/soundfonts`) e finisce
dentro il programma creato con PyInstaller.

I file non sono nel repository Git perché superano il limite di 100 MB di GitHub.

| Soundfont | Licenza | Fonte |
|---|---|---|
| Salamander Grand Piano V3 (Alexander Holm, conversione SF2 FreePats) | CC BY 3.0 | https://freepats.zenvoid.org/Piano/acoustic-grand-piano.html |
| YDP Grand Piano (FreePats) | CC BY 3.0 | https://freepats.zenvoid.org/Piano/acoustic-grand-piano.html |

La licenza CC BY 3.0 permette di ridistribuirli, anche dentro il programma,
a condizione di citare autore e licenza (lo fa la finestra Aiuto → Informazioni
e il file `*-CREDITS.txt` scritto accanto a ogni soundfont).
