"""Audio features for chord recognition: pitch-class energy in three registers.

The low register mostly carries the root, the upper ones the rest of the chord, so
keeping them apart lets a classifier tell a chord from its fifth-related neighbours.
"""

from __future__ import annotations

import numpy as np

BANDS = ((75.0, 220.0), (220.0, 660.0), (660.0, 2000.0))
N_FEATURES = 12 * len(BANDS)
SMOOTH_S = 0.07  # time constant of the feature smoothing; the classifier is trained with the same value


class ChromaBands:
    def __init__(self, sample_rate: float, n_fft: int = 8192):
        self.n_fft = n_fft
        self.window = np.hanning(n_fft).astype(np.float32)
        freqs = np.fft.rfftfreq(n_fft, 1 / sample_rate)
        band = (freqs >= BANDS[0][0]) & (freqs <= BANDS[-1][1])
        self.band = band
        self.freqs = freqs[band]
        self.bin_hz = sample_rate / n_fft
        midi = 69 + 12 * np.log2(self.freqs / 440.0)
        dist = ((midi[None, :] - np.arange(12)[:, None] + 6) % 12) - 6
        to_chroma = np.exp(-0.5 * (dist / 0.35) ** 2)
        self.matrix = np.concatenate(
            [to_chroma * ((self.freqs >= lo) & (self.freqs < hi + (hi == BANDS[-1][1]))) for lo, hi in BANDS]
        )  # (36, bins)
        self.row_total = self.matrix.sum(axis=1)

    def spectrum(self, frame: np.ndarray) -> np.ndarray:
        """Log-compressed magnitude spectrum of one n_fft-long frame, band-limited."""
        mag = np.abs(np.fft.rfft(frame * self.window))[self.band]
        return np.log1p(50 * mag / (self.n_fft / 4))


    def features(self, log_spectrum: np.ndarray, keep: np.ndarray | None = None) -> np.ndarray:
        """36 values: 12 pitch classes x 3 registers (not normalised).

        `keep` (1 = usable bin, 0 = hidden) marks bins covered by notes we are
        playing ourselves. A hidden bin is unknown, not silent, so each feature is
        scaled back up from the bins that are left.
        """
        if keep is None:
            return self.matrix @ log_spectrum
        available = (self.matrix @ keep) / self.row_total
        return (self.matrix @ (log_spectrum * keep)) / np.maximum(available, 0.25)

    def harmonic_mask(self, pitches) -> np.ndarray | None:
        """Bins free of the harmonics of these MIDI pitches (None if there are none)."""
        keep = None
        for pitch in pitches:
            if keep is None:
                keep = np.ones(len(self.freqs))
            f0 = 440.0 * 2 ** ((pitch - 69) / 12)
            for h in range(1, 13):
                f = f0 * h
                if f > self.freqs[-1] + 50:
                    break
                half = max(2.5 * self.bin_hz, f * (2 ** (0.4 / 12) - 1))
                keep[np.abs(self.freqs - f) <= half] = 0.0
        return keep


def rotate(features: np.ndarray, semitones: int) -> np.ndarray:
    """Transpose features by rolling every register's 12 pitch classes (last axis = 36)."""
    shape = features.shape
    return np.roll(features.reshape(*shape[:-1], len(BANDS), 12), semitones, axis=-1).reshape(shape)
