import json

import numpy as np
import pytest

from wintrypiano.core.events import CONTROL, NOTE_OFF, NOTE_ON
from wintrypiano.core.project import Project, default_project_folder
from wintrypiano.errors import TakeExistsError, UserError

EVENTS = [(0.0, NOTE_ON, 60, 100), (0.5, NOTE_OFF, 60, 0)]


def test_create_open_save(tmp_path):
    p = Project.create(tmp_path / "Song", "Song")
    assert p.json_path.is_file()
    p.settings.bpm = 87
    p.settings.voice_reverb = True
    p.save()
    data = json.loads(p.json_path.read_text(encoding="utf-8"))
    assert data["settings"]["bpm"] == 87
    q = Project.open(tmp_path / "Song")
    assert q.settings.bpm == 87 and q.settings.voice_reverb and q.settings.name == "Song"


def test_create_refuses_existing_project(tmp_path):
    Project.create(tmp_path / "a")
    with pytest.raises(UserError):
        Project.create(tmp_path / "a")


def test_open_invalid_folder(tmp_path):
    with pytest.raises(UserError):
        Project.open(tmp_path)
    (tmp_path / "project.json").write_text("{broken", encoding="utf-8")
    with pytest.raises(UserError) as e:
        Project.open(tmp_path)
    assert "damaged" in e.value.message


def test_piano_take_never_overwritten_without_confirmation(tmp_path):
    p = Project.create(tmp_path / "p")
    p.save_piano_take(EVENTS)
    before = p.piano_path.read_bytes()
    with pytest.raises(TakeExistsError):
        p.save_piano_take([(0.0, NOTE_ON, 72, 50), (1.0, NOTE_OFF, 72, 0)])
    assert p.piano_path.read_bytes() == before
    p.save_piano_take([(0.0, NOTE_ON, 72, 50), (1.0, NOTE_OFF, 72, 0)], overwrite=True)
    assert p.load_piano_take()[0][2] == 72


def test_voice_take_and_redo_keeps_piano(tmp_path):
    p = Project.create(tmp_path / "p")
    p.save_piano_take(EVENTS)
    piano_bytes = p.piano_path.read_bytes()
    audio = (np.sin(np.arange(48000) / 10) * 0.5).astype(np.float32)
    p.save_voice_take(audio, 48000, auto_offset_ms=-12.5)
    with pytest.raises(TakeExistsError):
        p.save_voice_take(audio, 48000, 0)
    p.save_voice_take(audio * 0.5, 48000, -10.0, overwrite=True)
    v, sr = p.load_voice_take()
    assert sr == 48000 and np.allclose(v, audio * 0.5)
    assert p.piano_path.read_bytes() == piano_bytes
    assert Project.open(p.folder).settings.voice_auto_offset_ms == -10.0


def test_mix_settings_include_manual_offset(tmp_path):
    p = Project.create(tmp_path / "p")
    p.settings.voice_auto_offset_ms = -20
    assert p.mix_settings(manual_offset_ms=5).voice_offset_ms == -15


def test_default_project_folder(tmp_path):
    assert default_project_folder(tmp_path).name == "Project 1"
    Project.create(tmp_path / "Project 1")
    assert default_project_folder(tmp_path).name == "Project 2"


def test_old_italian_project_files_are_migrated(tmp_path):
    p = Project.create(tmp_path / "old")
    p.save_piano_take(EVENTS)
    audio = (np.sin(np.arange(4800) / 10) * 0.5).astype(np.float32)
    p.save_voice_take(audio, 48000, auto_offset_ms=-5.0)
    # rename the files the way older versions called them
    p.json_path.rename(p.folder / "progetto.json")
    p.voice_path.rename(p.folder / "voce.wav")
    q = Project.open(p.folder)
    assert (p.folder / "project.json").is_file() and not (p.folder / "progetto.json").exists()
    assert q.has_voice() and not (p.folder / "voce.wav").exists()
    assert q.has_piano() and q.settings.voice_auto_offset_ms == -5.0
