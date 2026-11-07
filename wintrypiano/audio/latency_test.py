"""Tries buffer sizes and WASAPI modes and reports the lowest latency that stays stable.

Usage:  python -m wintrypiano.audio.latency_test [--seconds 6] [--save] [--include-exclusive] [--experimental]
With --save the best combination is written to the program settings.
The volume is zero: nothing is heard (the microphone is only read).
"""
from __future__ import annotations

import argparse
import os
import time

os.environ.setdefault("SD_ENABLE_ASIO", "1")

from wintrypiano.audio import devices  # noqa: E402
from wintrypiano.audio.engine import AudioEngine  # noqa: E402
from wintrypiano.config import Config  # noqa: E402
from wintrypiano.core.synth import PianoSynth  # noqa: E402
from wintrypiano.errors import UserError  # noqa: E402


def try_config(cfg: Config, api: str, block: int, exclusive: bool, seconds: float):
    out = devices.find_device(cfg.audio_output, api, "output") or devices.default_device(api, "output")
    if out is None:
        return None
    inp = devices.find_device(cfg.audio_input, api, "input") or devices.default_device(api, "input")
    eng = AudioEngine(PianoSynth(48000), 48000)
    eng.piano_volume = 0.0
    try:
        eng.open(out, inp, block, exclusive)
    except UserError as exc:
        return {"error": str(exc)}
    eng.monitor_enabled = True
    eng.monitor_gain = 0.0
    time.sleep(1.0)              # let the monitor margin settle
    eng.monitor_underruns = 0
    eng.xruns = 0
    time.sleep(seconds)
    res = {
        "output": eng.output_name, "microphone": eng.input_name or "(not open)",
        "key-to-sound ms": round(eng.estimated_latency_ms(), 1),
        "voice-to-headphones ms": round(eng.monitor_latency_ms(), 1) if eng.input_name else None,
        "xruns": eng.xruns, "monitor dropouts": eng.monitor_underruns,
        "callback errors": eng.callback_errors, "microphone error": eng.input_error,
    }
    eng.close()
    return res


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Find the lowest stable audio latency")
    ap.add_argument("--seconds", type=float, default=6.0, help="duration of each test")
    ap.add_argument("--save", action="store_true", help="save the best combination to the settings")
    ap.add_argument("--include-exclusive", action="store_true",
                    help="also try WASAPI exclusive mode (other apps are muted while Wintry Piano is open)")
    ap.add_argument("--experimental", action="store_true", help="also try the 48, 32 and 16 sample buffers")
    args = ap.parse_args(argv)
    try:  # the console or a log file may not be UTF-8
        import sys
        sys.stdout.reconfigure(errors="replace")
    except Exception:
        pass
    cfg = Config.load()
    apis = devices.candidate_hostapis(cfg.host_api)
    api = apis[0] if apis else ""
    print(f"Driver: {api}")
    sizes = (512, 256, 192, 128, 96, 64)
    if args.experimental:
        sizes += (48, 32, 16)
    combos = [(b, False) for b in sizes if b <= 512]
    if api == "Windows WASAPI" and args.include_exclusive:
        combos += [(b, True) for b in sizes if b <= 256]
    best = None
    for block, excl in combos:
        r = try_config(cfg, api, block, excl, args.seconds)
        label = f"buffer {block}{' exclusive' if excl else ''}"
        print(label, r, flush=True)
        if not r or "error" in r or r["microphone"] == "(not open)":
            continue
        stable = r["xruns"] == 0 and r["callback errors"] == 0 and r["monitor dropouts"] <= 2
        if stable and (best is None or r["voice-to-headphones ms"] < best[2]["voice-to-headphones ms"]):
            best = (block, excl, r)
    if best is None:
        print("No stable combination found.")
        return 1
    block, excl, r = best
    print(f"BEST: buffer {block}, exclusive={excl}: key-to-sound {r['key-to-sound ms']} ms, "
          f"voice-to-headphones {r['voice-to-headphones ms']} ms")
    if args.save:
        cfg.block_size = block
        cfg.wasapi_exclusive = excl
        cfg.save()
        print("Saved to the settings.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
