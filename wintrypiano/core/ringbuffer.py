"""Buffer circolare single-producer / single-consumer per audio float32.

Pre-allocato: scrittura e lettura non allocano memoria, quindi può essere
usato dentro la callback audio.
"""
from __future__ import annotations

import numpy as np


class RingBuffer:
    def __init__(self, capacity: int, channels: int = 1):
        self.capacity = int(capacity)
        self.channels = channels
        self._buf = np.zeros((self.capacity, channels), dtype=np.float32)
        self._write = 0  # totale frame scritti (monotono)
        self._read = 0   # totale frame letti (monotono)
        self.overflows = 0

    def available(self) -> int:
        return self._write - self._read

    def space(self) -> int:
        return self.capacity - self.available()

    def clear(self) -> None:
        self._read = self._write

    def write(self, data: np.ndarray) -> int:
        n = data.shape[0]
        if n > self.space():
            self.overflows += 1
            n = self.space()
            if n <= 0:
                return 0
        start = self._write % self.capacity
        first = min(n, self.capacity - start)
        self._buf[start:start + first] = data[:first]
        if first < n:
            self._buf[:n - first] = data[first:n]
        self._write += n
        return n

    def read_into(self, out: np.ndarray) -> int:
        """Legge al massimo len(out) frame in ``out``; ritorna i frame letti."""
        n = min(out.shape[0], self.available())
        if n <= 0:
            return 0
        start = self._read % self.capacity
        first = min(n, self.capacity - start)
        out[:first] = self._buf[start:start + first]
        if first < n:
            out[first:n] = self._buf[:n - first]
        self._read += n
        return n

    def read_all(self) -> np.ndarray:
        """Legge tutto il disponibile in un nuovo array (fuori dalla callback)."""
        out = np.empty((self.available(), self.channels), dtype=np.float32)
        self.read_into(out)
        return out
