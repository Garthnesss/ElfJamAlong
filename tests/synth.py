"""Synthetic strummed-guitar audio for tests."""
import numpy as np

VOICINGS = {
    "C": [48, 52, 55, 60, 64], "G": [43, 47, 50, 55, 59, 67], "Am": [45, 52, 57, 60, 64],
    "F": [41, 48, 53, 57, 60, 65], "Em": [40, 47, 52, 55, 59, 64], "D": [50, 57, 62, 66],
    "Dm": [50, 57, 62, 65], "E": [40, 47, 52, 56, 59, 64], "A": [45, 52, 57, 61, 64],
    "Bm": [47, 54, 59, 62, 66], "F#m": [42, 49, 54, 57, 61, 66],
}


def strum(name, seconds, sr=44100, strums=2, rng=None):
    rng = rng or np.random.default_rng(0)
    n = int(seconds * sr)
    out = np.zeros(n)
    for s in range(strums):
        start = int(s * n / strums)
        t = np.arange(n - start) / sr
        for i, note in enumerate(VOICINGS[name]):
            f0 = 440 * 2 ** ((note - 69) / 12) * (1 + rng.normal(0, 0.0015))
            delay = int(i * 0.012 * sr)  # strings are struck one after another
            tt = t[: len(t) - delay]
            tone = sum(np.sin(2 * np.pi * f0 * h * tt * (1 + 0.0004 * h * h)) / h * np.exp(-tt * (1.5 + 0.6 * h))
                       for h in range(1, 9))
            out[start + delay :] += tone
    out += rng.normal(0, 0.01, n)  # pickup hiss
    return (0.2 * out / np.max(np.abs(out))).astype(np.float32)
