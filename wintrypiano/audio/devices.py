"""Elenco dei dispositivi audio e scelta automatica dell'host API migliore.

Ordine di preferenza: ASIO (se c'è un driver), poi WASAPI, poi gli altri.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass

log = logging.getLogger(__name__)

HOSTAPI_PREFERENCE = (
    "ASIO",
    "Windows WASAPI",
    "Windows DirectSound",
    "MME",
    "Core Audio",
    "JACK Audio Connection Kit",
    "ALSA",
)

HOSTAPI_LABELS = {
    "ASIO": "ASIO (latenza minima)",
    "Windows WASAPI": "WASAPI (consigliato senza ASIO)",
    "Windows DirectSound": "DirectSound",
    "MME": "MME (latenza alta)",
}


def sd():
    """Importa sounddevice abilitando la DLL con supporto ASIO su Windows."""
    os.environ.setdefault("SD_ENABLE_ASIO", "1")
    import sounddevice  # noqa: WPS433

    return sounddevice


@dataclass(frozen=True)
class Device:
    index: int
    name: str
    hostapi: str
    max_input: int
    max_output: int
    default_samplerate: float


def rescan() -> None:
    """Rilegge l'elenco dei dispositivi (PortAudio va reinizializzato)."""
    s = sd()
    try:
        s._terminate()  # noqa: SLF001 - API interna ma stabile
    except Exception:  # pragma: no cover
        pass
    s._initialize()  # noqa: SLF001


def hostapi_names() -> list[str]:
    s = sd()
    names = []
    for api in s.query_hostapis():
        if api["devices"]:
            names.append(api["name"])
    return names


def sorted_hostapis() -> list[str]:
    names = hostapi_names()
    pref = [n for n in HOSTAPI_PREFERENCE if n in names]
    return pref + [n for n in names if n not in pref]


def all_devices() -> list[Device]:
    s = sd()
    apis = s.query_hostapis()
    out = []
    for i, d in enumerate(s.query_devices()):
        out.append(Device(i, d["name"], apis[d["hostapi"]]["name"], d["max_input_channels"],
                          d["max_output_channels"], d["default_samplerate"]))
    return out


def devices_for(hostapi: str, kind: str) -> list[Device]:
    key = "max_input" if kind == "input" else "max_output"
    return [d for d in all_devices() if d.hostapi == hostapi and getattr(d, key) > 0]


def default_device(hostapi: str, kind: str) -> Device | None:
    s = sd()
    for api in s.query_hostapis():
        if api["name"] == hostapi:
            idx = api["default_input_device" if kind == "input" else "default_output_device"]
            if idx is not None and idx >= 0:
                for d in all_devices():
                    if d.index == idx:
                        return d
    devs = devices_for(hostapi, kind)
    return devs[0] if devs else None


def find_device(name: str, hostapi: str, kind: str) -> Device | None:
    if not name:
        return None
    for d in devices_for(hostapi, kind):
        if d.name == name:
            return d
    return None


def candidate_hostapis(preferred: str) -> list[str]:
    """Host API da provare, nell'ordine: quella scelta, poi le altre."""
    order = sorted_hostapis()
    if preferred and preferred != "auto" and preferred in order:
        order.remove(preferred)
        order.insert(0, preferred)
    return order
