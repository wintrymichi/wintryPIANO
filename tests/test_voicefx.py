import numpy as np

from wintrypiano.core.voicefx import VoiceFx, compress, process_voice

SR = 48000


def _db(x):
    return 20 * np.log10(np.sqrt(np.mean(x.astype(np.float64) ** 2)) + 1e-12)


def _voice_like(seconds=4.0, seed=0):
    rng = np.random.default_rng(seed)
    t = np.arange(int(SR * seconds)) / SR
    tone = sum(np.sin(2 * np.pi * f * t) / (i + 1) for i, f in enumerate((220, 440, 660, 880, 1320)))
    env = ((t % 1.0) < 0.6).astype(np.float32)   # 0.6 s of "singing", 0.4 s of pause
    noise = rng.standard_normal(t.size) * 0.01
    return (0.2 * tone * env).astype(np.float32), noise.astype(np.float32), env


def test_disabled_is_identity():
    v, n, _ = _voice_like(1)
    x = v + n
    assert process_voice(x, SR, VoiceFx(enhance=False, denoise=False)) is x


def test_denoise_lowers_noise_in_pauses_and_keeps_voice():
    v, n, env = _voice_like()
    x = v + n
    y = process_voice(x, SR, VoiceFx(enhance=False, denoise=True, denoise_amount=0.7))
    assert y.shape == x.shape and np.isfinite(y).all()
    pauses = (env == 0)
    pauses[:SR // 10] = False
    assert _db(y[pauses]) < _db(x[pauses]) - 10       # noise in the pauses: at least -10 dB
    sing = env == 1
    assert abs(_db(y[sing]) - _db(x[sing])) < 2.0     # the voice stays almost the same
    # the voice waveform is preserved
    c = np.corrcoef(y[sing], v[sing])[0, 1]
    assert c > 0.97


def test_compressor_reduces_dynamics():
    t = np.arange(SR * 2) / SR
    tone = np.sin(2 * np.pi * 300 * t).astype(np.float32)
    x = np.concatenate([tone * 0.05, tone * 0.5])
    y = compress(x, SR)
    before = _db(x[SR * 2 + SR // 2:]) - _db(x[SR // 2:SR * 2])
    after = _db(y[SR * 2 + SR // 2:]) - _db(y[SR // 2:SR * 2])
    assert before > 19 and after < before - 4


def test_full_chain_is_safe_on_silence_and_short():
    for x in (np.zeros(SR, np.float32), np.zeros(100, np.float32), np.ones(10, np.float32) * 0.1):
        y = process_voice(x, SR, VoiceFx())
        assert y.shape == x.shape and np.isfinite(y).all()
