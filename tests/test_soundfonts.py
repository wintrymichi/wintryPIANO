import io
import shutil
import tarfile

import pytest

from wintrypiano.soundfonts import catalog, download
from wintrypiano.errors import UserError


def _make_archive(path, sf2_path):
    with tarfile.open(path, "w:xz") as tar:
        tar.add(sf2_path, arcname="Salamander/SalamanderGrandPiano-V3.sf2")
        data = b"Creative Commons Attribution 3.0"
        info = tarfile.TarInfo("Salamander/README.txt")
        info.size = len(data)
        tar.addfile(info, io.BytesIO(data))


def test_install_extracts_sf2_and_writes_credits(tmp_path, sf2_path, monkeypatch):
    archive = tmp_path / "src.tar.xz"
    _make_archive(archive, sf2_path)
    monkeypatch.setattr(download, "_download", lambda url, dest, progress, cancel=None: shutil.copy(archive, dest))
    dest = tmp_path / "sf"
    steps = []
    path = download.install(catalog.SALAMANDER, dest, progress=lambda f, m: steps.append(f))
    assert path.name == catalog.SALAMANDER.filename and path.read_bytes() == sf2_path.read_bytes()
    credits = (dest / "SalamanderGrandPiano-CREDITS.txt").read_text(encoding="utf-8")
    assert "CC BY 3.0" in credits and "freepats" in credits
    assert steps[-1] == 1.0
    assert list(dest.glob("*.part")) == []
    # already installed: no new download
    monkeypatch.setattr(download, "_download", lambda *a, **k: pytest.fail("must not download again"))
    assert download.install(catalog.SALAMANDER, dest) == path


def test_broken_archive_gives_clear_error(tmp_path, monkeypatch):
    monkeypatch.setattr(download, "_download",
                        lambda url, dest, progress, cancel=None: dest.write_bytes(b"not an archive"))
    with pytest.raises(UserError):
        download.install(catalog.YDP, tmp_path / "sf")


def test_default_soundfont_prefers_saved_then_salamander(tmp_path, sf2_path, monkeypatch):
    user = tmp_path / "user"
    user.mkdir()
    monkeypatch.setattr(catalog, "search_dirs", lambda: [tmp_path / "bundled", user])
    assert catalog.find_default_soundfont("") is None
    shutil.copy(sf2_path, user / catalog.YDP.filename)
    assert catalog.find_default_soundfont("").name == catalog.YDP.filename
    shutil.copy(sf2_path, user / catalog.SALAMANDER.filename)
    assert catalog.find_default_soundfont("").name == catalog.SALAMANDER.filename
    assert catalog.find_default_soundfont(str(sf2_path)) == sf2_path


def test_catalog_licenses_allow_redistribution():
    for info in catalog.CATALOG:
        assert "CC BY 3.0" in info.license
        assert info.url.startswith("https://freepats.zenvoid.org/")
