"""Prova le combinazioni di buffer e modalità WASAPI e dice qual è la latenza più bassa stabile.

Uso:  python -m wintrypiano.audio.latency_test [--secondi 6] [--salva] [--anche-esclusivo]
Con --salva scrive la combinazione migliore nelle impostazioni del programma.
Il volume è a zero: non si sente nulla (il microfono viene solo letto).
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
        return {"errore": str(exc)}
    eng.monitor_enabled = True
    eng.monitor_gain = 0.0
    time.sleep(1.0)              # il margine del monitor si assesta
    eng.monitor_underruns = 0
    eng.xruns = 0
    time.sleep(seconds)
    res = {
        "uscita": eng.output_name, "microfono": eng.input_name or "(non aperto)",
        "tasto→suono ms": round(eng.estimated_latency_ms(), 1),
        "voce→cuffie ms": round(eng.monitor_latency_ms(), 1) if eng.input_name else None,
        "xrun": eng.xruns, "interruzioni monitor": eng.monitor_underruns,
        "errori": eng.callback_errors, "microfono_errore": eng.input_error,
    }
    eng.close()
    return res


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--secondi", type=float, default=6.0)
    ap.add_argument("--salva", action="store_true")
    ap.add_argument("--anche-esclusivo", action="store_true",
                    help="prova anche WASAPI esclusivo (le altre app non suonano finché Wintry Piano è aperto)")
    args = ap.parse_args(argv)
    cfg = Config.load()
    apis = devices.candidate_hostapis(cfg.host_api)
    api = apis[0] if apis else ""
    print(f"Driver: {api}")
    combos = [(b, False) for b in (512, 256, 128, 64)]
    if api == "Windows WASAPI" and args.anche_esclusivo:
        combos += [(b, True) for b in (256, 128, 64)]
    best = None
    for block, excl in combos:
        r = try_config(cfg, api, block, excl, args.secondi)
        label = f"buffer {block}{' esclusivo' if excl else ''}"
        print(label, r, flush=True)
        if not r or "errore" in r or r["microfono"] == "(non aperto)":
            continue
        stable = r["xrun"] == 0 and r["errori"] == 0 and r["interruzioni monitor"] <= 2
        if stable and (best is None or r["voce→cuffie ms"] < best[2]["voce→cuffie ms"]):
            best = (block, excl, r)
    if best is None:
        print("Nessuna combinazione stabile trovata.")
        return 1
    block, excl, r = best
    print(f"MIGLIORE: buffer {block}, esclusivo={excl}: tasto→suono {r['tasto→suono ms']} ms, "
          f"voce→cuffie {r['voce→cuffie ms']} ms")
    if args.salva:
        cfg.block_size = block
        cfg.wasapi_exclusive = excl
        cfg.save()
        print("Salvato nelle impostazioni.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
