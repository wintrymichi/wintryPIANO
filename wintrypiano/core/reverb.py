"""Riverbero semplice stile Freeverb, vettorizzato a blocchi con numpy.

I filtri comb e allpass hanno ritardi maggiori della dimensione del
sotto-blocco, quindi ogni sotto-blocco si calcola senza loop per campione.
Tutti i buffer sono pre-allocati: ``process`` può girare nella callback audio.
"""
from __future__ import annotations

import numpy as np

_COMBS = (1116, 1188, 1277, 1356, 1422, 1491, 1557, 1617)
_ALLPASS = (556, 441, 341, 225)
_SPREAD = 23
_SUB = 200  # dimensione massima del sotto-blocco (< ritardo minimo)


class _Delay:
    """Linea di ritardo circolare con lettura/scrittura a blocchi senza allocazioni."""

    def __init__(self, delay: int, maxblock: int):
        self.delay = delay
        self.size = delay + maxblock + 2
        self.buf = np.zeros(self.size, dtype=np.float32)
        self.pos = 0  # prossimo indice di scrittura
        self._idx = np.empty(maxblock, dtype=np.int64)
        self._ar = np.arange(maxblock, dtype=np.int64)

    def read(self, extra: int, n: int, out: np.ndarray) -> None:
        """out[i] = y[t+i - delay - extra] con t = posizione di scrittura."""
        idx = self._idx[:n]
        np.add(self._ar[:n], self.pos - self.delay - extra, out=idx)
        np.remainder(idx, self.size, out=idx)
        np.take(self.buf, idx, out=out)

    def write(self, data: np.ndarray) -> None:
        n = data.shape[0]
        start = self.pos
        first = min(n, self.size - start)
        self.buf[start:start + first] = data[:first]
        if first < n:
            self.buf[:n - first] = data[first:]
        self.pos = (self.pos + n) % self.size

    def reset(self) -> None:
        self.buf.fill(0.0)


class SimpleReverb:
    def __init__(self, samplerate: int, room: float = 0.78, damp: float = 0.35,
                 wet: float = 0.22, max_block: int = 4096):
        scale = samplerate / 44100.0
        self.wet = wet
        self.room = room
        self.damp = damp
        self.max_block = max_block
        sub = _SUB
        self.combs = [[_Delay(max(int(d * scale) + ch * int(_SPREAD * scale), sub + 2), sub)
                       for d in _COMBS] for ch in range(2)]
        self.allpasses = [[_Delay(max(int(d * scale) + ch * int(_SPREAD * scale), sub + 1), sub)
                           for d in _ALLPASS] for ch in range(2)]
        self._in = np.zeros(sub, dtype=np.float32)
        self._acc = np.zeros(sub, dtype=np.float32)
        self._t1 = np.zeros(sub, dtype=np.float32)
        self._t2 = np.zeros(sub, dtype=np.float32)
        self._y = np.zeros(sub, dtype=np.float32)

    def reset(self) -> None:
        for ch in range(2):
            for d in self.combs[ch] + self.allpasses[ch]:
                d.reset()

    def process(self, block: np.ndarray) -> np.ndarray:
        """Aggiunge il riverbero in-place a un blocco stereo (frames, 2) float32."""
        n_total = block.shape[0]
        pos = 0
        while pos < n_total:
            n = min(_SUB, n_total - pos)
            self._process_sub(block[pos:pos + n], n)
            pos += n
        return block

    def _process_sub(self, block: np.ndarray, n: int) -> None:
        fb = self.room
        d = self.damp
        x = self._in[:n]
        # ingresso mono (somma dei canali), attenuato come Freeverb
        np.add(block[:, 0], block[:, 1], out=x)
        x *= 0.015
        for ch in range(2):
            acc = self._acc[:n]
            acc.fill(0.0)
            t1 = self._t1[:n]
            t2 = self._t2[:n]
            y = self._y[:n]
            for comb in self.combs[ch]:
                comb.read(0, n, t1)          # y[n-D]  (uscita del comb)
                comb.read(1, n, t2)          # y[n-D-1]
                acc += t1
                # y = x + fb*((1-d)*t1 + d*t2)
                np.multiply(t1, (1.0 - d) * fb, out=y)
                t2 *= d * fb
                y += t2
                y += x
                comb.write(y)
            for ap in self.allpasses[ch]:
                ap.read(0, n, t1)            # v[n-D]
                # v = acc + 0.5*v[n-D];  out = v[n-D] - acc
                np.multiply(t1, 0.5, out=y)
                y += acc
                ap.write(y)
                np.subtract(t1, acc, out=acc)
            acc *= self.wet
            block[:, ch] += acc


def apply_reverb_offline(audio: np.ndarray, samplerate: int, wet: float = 0.22,
                         tail_s: float = 2.5) -> np.ndarray:
    """Applica il riverbero a un intero file, aggiungendo la coda."""
    tail = int(tail_s * samplerate)
    out = np.zeros((audio.shape[0] + tail, 2), dtype=np.float32)
    out[:audio.shape[0]] = audio
    rev = SimpleReverb(samplerate, wet=wet)
    chunk = 4096
    for i in range(0, out.shape[0], chunk):
        rev.process(out[i:i + chunk])
    return out
