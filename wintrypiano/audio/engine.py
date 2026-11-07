"""Motore audio in tempo reale.

Tutto ciò che gira nella callback audio usa buffer pre-allocati e non tocca
mai il disco: gli eventi MIDI arrivano da una ``deque`` (thread-safe), la voce
registrata finisce in un ``RingBuffer`` che un thread separato scrive su disco.
La GUI legge lo stato del motore con un timer (polling), senza bloccarsi.
"""
from __future__ import annotations

import logging
import threading
import time
from collections import deque

import numpy as np

from wintrypiano.audio import devices as devmod
from wintrypiano.core.events import CC_SUSTAIN, CONTROL
from wintrypiano.core.metronome import Metronome
from wintrypiano.core.reverb import SimpleReverb
from wintrypiano.core.ringbuffer import RingBuffer
from wintrypiano.core.synth import PianoSynth
from wintrypiano.errors import UserError

log = logging.getLogger(__name__)

IDLE, COUNT_IN, REC_PIANO, PLAYING, REC_VOICE = range(5)
MAX_BLOCK = 4096


class AudioEngine:
    def __init__(self, synth: PianoSynth, samplerate: int = 48000):
        self.synth = synth
        self.midi_queue: deque = deque(maxlen=8192)
        self.rec_queue: deque = deque()
        # parametri modificabili dalla GUI (assegnazioni atomiche)
        self.piano_volume = 0.8
        self.piano_reverb = False
        self.metronome_enabled = False
        self.metronome_gain = 0.6
        self.monitor_enabled = False
        self.monitor_gain = 1.0
        self.playback_gain = 1.0
        # stream
        self._out = None
        self._in = None
        self._duplex = None
        self._closing = False
        self.blocksize = 256
        self.hostapi = ""
        self.output_name = ""
        self.input_name = ""
        self.input_error = ""
        self.output_latency = 0.0
        self.input_latency = 0.0
        self.clock = None        # solo per i test: sostituisce l'orologio dello stream
        self.monitor_extra = 0   # margine (campioni) del monitor, cresce solo se servono
        self.monitor_underruns = 0
        self._setup(samplerate)

    # ------------------------------------------------------------ allocazioni
    def _setup(self, samplerate: int) -> None:
        self.samplerate = int(samplerate)
        sr = self.samplerate
        self.reverb = SimpleReverb(sr, max_block=MAX_BLOCK)
        self.metronome = Metronome(sr)
        self.voice_ring = RingBuffer(sr * 30, 1)
        self.monitor_ring = RingBuffer(sr // 2, 1)
        self._scratch = np.zeros((MAX_BLOCK, 2), dtype=np.float32)
        self._mono = np.zeros((MAX_BLOCK, 1), dtype=np.float32)
        self._abs = np.zeros(MAX_BLOCK, dtype=np.float32)
        self._reset_counters()
        self.mode = IDLE
        self._playback = None
        self._play_pos = 0
        self._with_voice = False
        self._capture = False
        self._dac_time = None
        self._adc_time = None
        self._mon_had_data = False
        self.monitor_extra = 0

    def _reset_counters(self) -> None:
        self.callback_count = 0
        self.xruns = 0
        self.callback_errors = 0
        self.last_error: BaseException | None = None
        self.mic_peak = 0.0
        self.mic_clip = False
        self.stream_finished = False

    # -------------------------------------------------------------- apertura
    @property
    def is_open(self) -> bool:
        return any(s is not None for s in (self._out, self._in, self._duplex))

    def open(self, output: devmod.Device, input_dev: devmod.Device | None, blocksize: int,
             exclusive: bool = False, samplerate: int | None = None) -> int:
        """Apre gli stream. Ritorna il samplerate effettivo."""
        sd = devmod.sd()
        self.close()
        self._closing = False
        self.monitor_extra = 0
        self.blocksize = int(blocksize)
        self.input_error = ""
        rates = [samplerate or self.samplerate, int(output.default_samplerate)]
        rates = list(dict.fromkeys(r for r in rates if r))
        extra = None
        if output.hostapi == "Windows WASAPI":
            extra = sd.WasapiSettings(exclusive=exclusive, auto_convert=not exclusive)
        duplex = (input_dev is not None and output.hostapi == "ASIO")
        last_exc = None
        for sr in rates:
            if sr != self.samplerate:
                self._setup(sr)
            try:
                if duplex:
                    self._duplex = sd.Stream(
                        samplerate=sr, blocksize=self.blocksize, device=(input_dev.index, output.index),
                        channels=(1, 2), dtype="float32", latency="low", callback=self._duplex_cb,
                        finished_callback=self._finished, extra_settings=None)
                    self._duplex.start()
                    self.input_latency, self.output_latency = self._duplex.latency
                else:
                    self._out = sd.OutputStream(
                        samplerate=sr, blocksize=self.blocksize, device=output.index, channels=2,
                        dtype="float32", latency="low", callback=self._out_cb,
                        finished_callback=self._finished, extra_settings=extra)
                    self._out.start()
                    self.output_latency = self._out.latency
                last_exc = None
                break
            except Exception as exc:  # PortAudioError o parametri non supportati
                last_exc = exc
                self._safe_close_all()
        if last_exc is not None:
            log.warning("apertura uscita fallita: %s", last_exc)
            raise UserError(f"Non riesco ad aprire l'uscita audio «{output.name}». "
                            "Prova un altro dispositivo o un buffer più grande nelle impostazioni.") from last_exc
        self.hostapi = output.hostapi
        self.output_name = output.name
        self.input_name = ""
        if input_dev is not None and not duplex:
            in_extra = None
            if input_dev.hostapi == "Windows WASAPI":
                in_extra = sd.WasapiSettings(exclusive=exclusive, auto_convert=not exclusive)
            try:
                self._in = sd.InputStream(
                    samplerate=self.samplerate, blocksize=self.blocksize, device=input_dev.index,
                    channels=1, dtype="float32", latency="low", callback=self._in_cb,
                    extra_settings=in_extra)
                self._in.start()
                self.input_latency = self._in.latency
                self.input_name = input_dev.name
            except Exception as exc:
                log.warning("apertura microfono fallita: %s", exc)
                self._in = None
                self.input_error = (f"Non riesco ad aprire il microfono «{input_dev.name}». "
                                    "Controlla che sia collegato e che Windows consenta l'accesso al microfono.")
        elif duplex:
            self.input_name = input_dev.name
        return self.samplerate

    def _safe_close_all(self) -> None:
        for name in ("_duplex", "_out", "_in"):
            s = getattr(self, name)
            if s is not None:
                try:
                    s.abort(ignore_errors=True)
                    s.close(ignore_errors=True)
                except Exception:
                    pass
                setattr(self, name, None)

    def close(self) -> None:
        self._closing = True
        self._safe_close_all()
        self.mode = IDLE
        self._reset_counters()

    def _finished(self) -> None:
        if not self._closing:
            self.stream_finished = True

    def monitor_latency_ms(self) -> float:
        """Latenza stimata voce → cuffie quando ascolti il microfono."""
        b = self.blocksize / self.samplerate
        return (self.input_latency + self.output_latency + b + self.monitor_extra / self.samplerate) * 1000.0

    def estimated_latency_ms(self) -> float:
        """Latenza stimata tasto → suono: un buffer + latenza dichiarata dall'uscita."""
        base = self.blocksize / self.samplerate
        return (base + (self.output_latency or base)) * 1000.0

    # -------------------------------------------------------------- comandi
    def now(self) -> float:
        """Ora sull'orologio dello stream audio (lo stesso dei tempi della callback), 0 se non c'è."""
        if self.clock is not None:
            return self.clock()
        stream = self._duplex or self._out
        if stream is None:
            return 0.0
        try:
            return float(stream.time)
        except Exception:
            return 0.0

    def note_event(self, kind: int, a: int, b: int) -> None:
        # salvo l'istante in cui è arrivata la nota: in registrazione la metto nel punto
        # in cui l'hai suonata davvero, non in quello in cui la callback l'ha letta
        self.midi_queue.append((kind, a, b, self.now()))

    def start_piano_recording(self, bpm: float, count_in_beats: int, with_voice: bool = False,
                              backing: np.ndarray | None = None) -> None:
        """Registra il piano (MIDI). Con ``with_voice`` registra anche il microfono
        nella stessa take, allineato al piano come nella registrazione della voce."""
        self._with_voice = with_voice
        self._playback = None if backing is None else np.ascontiguousarray(backing, dtype=np.float32)
        self._play_pos = 0
        self._capture = False
        self._dac_time = None
        self._adc_time = None
        self.voice_ring.clear()
        self.metronome.set_bpm(bpm)
        self.rec_queue.clear()
        self._session_frame = 0
        self._rec_offset = count_in_beats * self.metronome.beat_frames
        self.metronome.reset()
        self._rec_started = False
        self.mode = COUNT_IN if self._rec_offset > 0 else REC_PIANO
        if self.mode == REC_PIANO:
            self._begin_rec()

    def _begin_rec(self) -> None:
        self._rec_started = True
        if self.synth.sustain:
            self.rec_queue.append((0, CONTROL, CC_SUSTAIN, 127))

    def count_in_remaining(self) -> int:
        if self.mode != COUNT_IN:
            return 0
        bf = self.metronome.beat_frames
        return max(1, -(-(self._rec_offset - self._session_frame) // bf))

    def recording_seconds(self) -> float:
        if self.mode == REC_PIANO:
            return max(0, self._session_frame - self._rec_offset) / self.samplerate
        if self.mode == REC_VOICE:
            return self._play_pos / self.samplerate
        return 0.0

    def play(self, audio: np.ndarray, bpm: float | None = None) -> None:
        """Riproduce un array stereo già pronto (riascolto piano o mix)."""
        self._playback = np.ascontiguousarray(audio, dtype=np.float32)
        self._play_pos = 0
        if bpm:
            self.metronome.set_bpm(bpm)
        self.metronome.reset()
        self._session_frame = 0
        self.mode = PLAYING

    def start_voice_recording(self, piano: np.ndarray | None, bpm: float) -> None:
        self._playback = None if piano is None else np.ascontiguousarray(piano, dtype=np.float32)
        self._play_pos = 0
        self.metronome.set_bpm(bpm)
        self.metronome.reset()
        self._session_frame = 0
        self.voice_ring.clear()
        self._dac_time = None
        self._adc_time = None
        self._capture = False
        self.mode = REC_VOICE

    def voice_offset_ms(self) -> float:
        """Compensazione automatica: dove cade il primo campione della voce rispetto al piano."""
        dac, adc = getattr(self, "_dac_time", None), getattr(self, "_adc_time", None)
        if dac and adc:
            return (adc - dac) * 1000.0
        return -(self.input_latency + self.output_latency) * 1000.0

    def stop(self) -> None:
        self.mode = IDLE
        self._capture = False
        self._with_voice = False
        self._playback = None

    def playback_position(self) -> tuple[float, float]:
        if self._playback is None:
            return 0.0, 0.0
        return self._play_pos / self.samplerate, self._playback.shape[0] / self.samplerate

    def take_mic_level(self) -> tuple[float, bool]:
        peak, clip = self.mic_peak, self.mic_clip
        self.mic_peak = 0.0
        self.mic_clip = False
        return peak, clip

    # ------------------------------------------------------------- callback
    def _out_cb(self, outdata, frames, time_info, status):
        if status.output_underflow:
            self.xruns += 1
        try:
            self._process_output(outdata, frames, time_info.outputBufferDacTime)
        except Exception as exc:  # mai propagare dalla callback
            outdata.fill(0)
            self.callback_errors += 1
            self.last_error = exc

    def _in_cb(self, indata, frames, time_info, status):
        try:
            self._process_input(indata, frames, time_info.inputBufferAdcTime)
        except Exception as exc:
            self.callback_errors += 1
            self.last_error = exc

    def _duplex_cb(self, indata, outdata, frames, time_info, status):
        if status.output_underflow:
            self.xruns += 1
        try:
            self._process_input(indata, frames, time_info.inputBufferAdcTime)
            self._process_output(outdata, frames, time_info.outputBufferDacTime)
        except Exception as exc:
            outdata.fill(0)
            self.callback_errors += 1
            self.last_error = exc

    def _process_input(self, indata, frames, adc_time) -> None:
        mono = indata[:, :1]
        a = self._abs[:frames]
        np.abs(mono[:, 0], out=a)
        peak = float(a.max()) if frames else 0.0
        if peak > self.mic_peak:
            self.mic_peak = peak
        if peak >= 0.98:
            self.mic_clip = True
        if self.monitor_enabled:
            self.monitor_ring.write(mono)
        if self._capture and self.mode in (REC_VOICE, REC_PIANO):
            if self._adc_time is None:
                self._adc_time = adc_time
            self.voice_ring.write(mono)

    def _process_output(self, out, frames, dac_time) -> None:
        self.callback_count += 1
        out.fill(0.0)
        mode = self.mode
        synth = self.synth
        q = self.midi_queue
        scratch = self._scratch[:frames]

        # Stato della registrazione del piano / conto alla rovescia
        if mode == COUNT_IN and self._session_frame >= self._rec_offset:
            self.mode = mode = REC_PIANO
            self._begin_rec()

        # Suona e canta: la voce parte esattamente all'inizio della take del piano
        if mode == REC_PIANO and self._with_voice and not self._capture:
            self._dac_time = dac_time
            self._capture = True

        # 1) eventi MIDI + suono dal vivo
        if synth.lock.acquire(False):
            try:
                # Registro anche le note suonate nell'ultimo mezzo battito del conto
                # alla rovescia (chi attacca un po' in anticipo): finiscono a t=0.
                recording = mode == REC_PIANO or (
                    mode == COUNT_IN
                    and self._session_frame >= self._rec_offset - self.metronome.beat_frames // 2)
                if recording:
                    sr = self.samplerate
                    base = self._session_frame - self._rec_offset
                    fallback = -self.output_latency * sr
                    max_back = -0.5 * sr
                    while q:
                        kind, a, b, when = q.popleft()
                        synth.handle(kind, a, b)
                        # Linea del tempo = quando il suono esce dalle cuffie (come per la voce).
                        # La nota è arrivata a «when»; questo blocco uscirà a «dac_time»:
                        # la differenza è la latenza dell'uscita più l'attesa della callback.
                        if when and dac_time:
                            dt = (when - dac_time) * sr
                            if not max_back <= dt <= 0:
                                dt = fallback
                        else:
                            dt = fallback
                        t = max(0.0, base + dt) / sr
                        self.rec_queue.append((t, kind, a, b))
                else:
                    while q:
                        kind, a, b, _when = q.popleft()
                        synth.handle(kind, a, b)
                piano = synth.generate(frames)
                if self.piano_reverb:
                    self.reverb.process(piano)
                np.multiply(piano, self.piano_volume, out=scratch)
                out += scratch
            finally:
                synth.lock.release()
        else:
            q.clear()  # render offline in corso: gli eventi live vengono scartati

        # 2) riproduzione (riascolto o piano sotto la voce)
        pb = self._playback
        if pb is not None and mode in (PLAYING, REC_VOICE, REC_PIANO):
            if mode == REC_VOICE and not self._capture:
                self._dac_time = dac_time
                self._capture = True
            pos = self._play_pos
            n = min(frames, pb.shape[0] - pos)
            if n > 0:
                np.multiply(pb[pos:pos + n], self.playback_gain, out=scratch[:n])
                out[:n] += scratch[:n]
            self._play_pos = pos + frames
            if mode == PLAYING and self._play_pos >= pb.shape[0]:
                self.mode = IDLE
                self._playback = None
        elif mode == REC_VOICE:
            if not self._capture:
                self._dac_time = dac_time
                self._capture = True
            self._play_pos += frames

        # 3) metronomo (mai registrato: il piano si salva come MIDI, la voce dal microfono)
        if mode == COUNT_IN or (self.metronome_enabled and mode in (REC_PIANO, REC_VOICE, PLAYING)):
            self.metronome.render_into(out, frames, self.metronome_gain)
        else:
            self.metronome.frame += frames
        if mode != IDLE:
            self._session_frame += frames

        # 4) ascolto del microfono in cuffia
        if self.monitor_enabled:
            ring = self.monitor_ring
            # latenza minima: tengo al massimo un blocco (più un margine che cresce
            # solo se l'ingresso arriva in ritardo e il suono si interromperebbe)
            excess = ring.available() - frames - self.monitor_extra
            if excess > 0:
                ring._read += excess  # noqa: SLF001
            m = self._mono[:frames]
            got = ring.read_into(m)
            if 0 < got < frames or (got == 0 and self._mon_had_data):
                self.monitor_underruns += 1
                if self.monitor_extra < 2 * frames:
                    self.monitor_extra += max(16, frames // 4)
            self._mon_had_data = got > 0
            if got:
                out[:got, 0] += m[:got, 0] * self.monitor_gain
                out[:got, 1] += m[:got, 0] * self.monitor_gain
        elif self.monitor_ring.available():
            self.monitor_ring.clear()

        np.clip(out, -1.0, 1.0, out=out)


class RecordingWriter(threading.Thread):
    """Thread che svuota le code del motore e scrive i file di recupero."""

    def __init__(self, engine: AudioEngine, piano_journal=None, voice_journal=None):
        super().__init__(daemon=True, name="wintry-writer")
        self.engine = engine
        self.piano_journal = piano_journal
        self.voice_journal = voice_journal
        self.events: list = []
        self.voice_chunks: list = []
        self._stop_evt = threading.Event()
        self.error: BaseException | None = None
        self._offset_written = False

    def run(self) -> None:
        while not self._stop_evt.is_set():
            self._drain()
            time.sleep(0.05)
        self._drain()

    def _drain(self) -> None:
        try:
            q = self.engine.rec_queue
            batch = []
            while q:
                batch.append(q.popleft())
            if batch:
                self.events.extend(batch)
                if self.piano_journal:
                    self.piano_journal.append(batch)
            if self.voice_journal is not None:
                data = self.engine.voice_ring.read_all()
                if data.shape[0]:
                    chunk = data[:, 0].copy()
                    self.voice_chunks.append(chunk)
                    self.voice_journal.append(chunk)
                    if not self._offset_written and self.engine._adc_time is not None:  # noqa: SLF001
                        self.voice_journal.set_offset(self.engine.voice_offset_ms())
                        self._offset_written = True
        except Exception as exc:  # disco pieno, ecc.
            self.error = exc
            log.exception("errore nel thread di scrittura")

    def finish(self) -> None:
        self._stop_evt.set()
        self.join(timeout=5)

    def voice_audio(self) -> np.ndarray:
        if not self.voice_chunks:
            return np.zeros(0, dtype=np.float32)
        return np.concatenate(self.voice_chunks)
