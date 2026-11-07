# Soundfonts bundled in the .exe

This folder is filled by `build_exe.bat` (or by
`python -m wintrypiano.soundfonts.download --dest assets/soundfonts`) and ends up
inside the program built with PyInstaller.

The files are not stored in the Git repository because they exceed GitHub's 100 MB limit.

| Soundfont | License | Source |
|---|---|---|
| Salamander Grand Piano V3 (Alexander Holm, SF2 conversion by FreePats) | CC BY 3.0 | https://freepats.zenvoid.org/Piano/acoustic-grand-piano.html |
| YDP Grand Piano (FreePats) | CC BY 3.0 | https://freepats.zenvoid.org/Piano/acoustic-grand-piano.html |

The CC BY 3.0 license allows redistributing them, including inside the program,
as long as the author and license are credited (the Help → About and credits window
does this, as does the `*-CREDITS.txt` file written next to each soundfont).
