"""Builds a tiny sine-wave .sf2 soundfont for the tests (no download)."""
from __future__ import annotations

import struct
from pathlib import Path

import numpy as np


def _chunk(cid: bytes, data: bytes) -> bytes:
    pad = b"\0" if len(data) % 2 else b""
    return cid + struct.pack("<I", len(data)) + data + pad


def _list(kind: bytes, payload: bytes) -> bytes:
    return _chunk(b"LIST", kind + payload)


def _name(s: str) -> bytes:
    return s.encode("ascii")[:20].ljust(20, b"\0")


def build_sine_sf2(path: Path, sample_rate: int = 44000) -> Path:
    period = 100  # 440 Hz at 44 kHz -> note 69
    n = period * 200
    t = np.arange(n)
    samples = (np.sin(2 * np.pi * t / period) * 20000).astype("<i2")
    smpl = samples.tobytes() + b"\0" * 92  # 46 padding samples required

    info = _list(b"INFO", _chunk(b"ifil", struct.pack("<HH", 2, 1)) +
                 _chunk(b"isng", b"EMU8000\0") + _chunk(b"INAM", b"Test Piano\0\0"))
    sdta = _list(b"sdta", _chunk(b"smpl", smpl))

    phdr = (_name("Test Piano") + struct.pack("<HHHIII", 0, 0, 0, 0, 0, 0) +
            _name("EOP") + struct.pack("<HHHIII", 0, 0, 1, 0, 0, 0))
    pbag = struct.pack("<HH", 0, 0) + struct.pack("<HH", 1, 0)
    pmod = b"\0" * 10
    pgen = struct.pack("<HH", 41, 0) + struct.pack("<HH", 0, 0)  # instrument 0
    inst = _name("Sine") + struct.pack("<H", 0) + _name("EOI") + struct.pack("<H", 1)
    ibag = struct.pack("<HH", 0, 0) + struct.pack("<HH", 4, 0)
    imod = b"\0" * 10
    igen = (struct.pack("<Hh", 38, -2400) +   # releaseVolEnv ~ 0.25 s
            struct.pack("<HH", 54, 1) +       # sampleModes: loop
            struct.pack("<HH", 58, 69) +      # overridingRootKey
            struct.pack("<HH", 53, 0) +       # sampleID
            struct.pack("<HH", 0, 0))
    shdr = (_name("sine") + struct.pack("<IIIIIBbHH", 0, n, period * 10, period * 190,
                                        sample_rate, 69, 0, 0, 1) +
            _name("EOS") + b"\0" * 26)
    pdta = _list(b"pdta", _chunk(b"phdr", phdr) + _chunk(b"pbag", pbag) + _chunk(b"pmod", pmod) +
                 _chunk(b"pgen", pgen) + _chunk(b"inst", inst) + _chunk(b"ibag", ibag) +
                 _chunk(b"imod", imod) + _chunk(b"igen", igen) + _chunk(b"shdr", shdr))
    body = b"sfbk" + info + sdta + pdta
    Path(path).write_bytes(b"RIFF" + struct.pack("<I", len(body)) + body)
    return Path(path)
