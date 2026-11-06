import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from sf2_builder import build_sine_sf2  # noqa: E402

SR = 48000


@pytest.fixture(autouse=True)
def _isolated_home(tmp_path, monkeypatch):
    monkeypatch.setenv("WINTRYPIANO_HOME", str(tmp_path / "home"))


@pytest.fixture(scope="session")
def sf2_path(tmp_path_factory):
    return build_sine_sf2(tmp_path_factory.mktemp("sf") / "sine.sf2")


@pytest.fixture
def synth(sf2_path):
    from wintrypiano.core.synth import LoadedFont, PianoSynth

    s = PianoSynth(SR)
    s.set_font(LoadedFont(sf2_path, SR))
    return s
