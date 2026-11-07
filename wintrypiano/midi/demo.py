"""Demo mode: simulates a MIDI piano playing, to try everything without hardware."""
from __future__ import annotations

import random
import threading
import time
from typing import Callable

from wintrypiano.core.events import CC_SUSTAIN, CONTROL, NOTE_OFF, NOTE_ON

# Progression in C major: (chord, melody)
_PROGRESSION = [
    ((48, 55, 60, 64), (72, 74, 76, 79)),
    ((45, 52, 57, 60), (76, 74, 72, 69)),
    ((41, 48, 53, 57), (69, 72, 77, 76)),
    ((43, 50, 55, 59), (74, 71, 67, 74)),
]


def demo_events(bpm: float = 100.0, bars: int = 4, seed: int = 7):
    """Generate ``(t, kind, a, b)`` events for a short piece with sustain pedal."""
    rnd = random.Random(seed)
    beat = 60.0 / bpm
    events = []
    for bar in range(bars):
        chord, melody = _PROGRESSION[bar % len(_PROGRESSION)]
        t0 = bar * 4 * beat
        events.append((t0 + 0.01, CONTROL, CC_SUSTAIN, 0))
        events.append((t0 + 0.03, CONTROL, CC_SUSTAIN, 127))
        for i, n in enumerate(chord):
            events.append((t0 + i * 0.012, NOTE_ON, n, 55 + rnd.randint(0, 20)))
            events.append((t0 + 3.6 * beat, NOTE_OFF, n, 0))
        for i, n in enumerate(melody):
            t = t0 + i * beat
            events.append((t, NOTE_ON, n, 70 + rnd.randint(0, 35)))
            events.append((t + beat * 0.9, NOTE_OFF, n, 0))
    end = bars * 4 * beat
    events.append((end, CONTROL, CC_SUSTAIN, 0))
    return sorted(events, key=lambda e: e[0])


class DemoPlayer(threading.Thread):
    """Send the demo events to ``sink`` in a loop, like a real piano would."""

    def __init__(self, sink: Callable[[int, int, int], None], bpm: float = 100.0):
        super().__init__(daemon=True, name="wintry-demo")
        self.sink = sink
        self.bpm = bpm
        self._stop_evt = threading.Event()

    def run(self) -> None:
        seed = 1
        while not self._stop_evt.is_set():
            events = demo_events(self.bpm, bars=4, seed=seed)
            start = time.perf_counter()
            for t, kind, a, b in events:
                while not self._stop_evt.is_set():
                    wait = start + t - time.perf_counter()
                    if wait <= 0:
                        break
                    time.sleep(min(wait, 0.02))
                if self._stop_evt.is_set():
                    break
                self.sink(kind, a, b)
            seed += 1
        # release everything
        self.sink(CONTROL, CC_SUSTAIN, 0)
        for n in range(21, 109):
            self.sink(NOTE_OFF, n, 0)

    def stop(self) -> None:
        self._stop_evt.set()
