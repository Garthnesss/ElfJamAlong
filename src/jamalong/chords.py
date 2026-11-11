"""Live chord and key detection from a mono audio stream."""

from __future__ import annotations

import time
from pathlib import Path

import numpy as np

from .features import N_FEATURES, ChromaBands, rotate
from .theory import Chord, Key, TRIADS

# Krumhansl-Kessler key profiles.
_KK_MAJOR = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
_KK_MINOR = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])

# Pitch-class offset of harmonics 1..6 of a note, and how much each counts.
_HARMONIC_OFFSETS = (0, 0, 7, 0, 4, 7)
_HARMONIC_DECAY = 0.6

MODEL_PATH = Path(__file__).with_name("chord_model.npz")


def _chord_templates() -> tuple[list[Chord], np.ndarray]:
    chords, rows = [], []
    for quality, intervals in TRIADS.items():
        for root in range(12):
            t = np.zeros(12)
            for iv in intervals:
                for h, off in enumerate(_HARMONIC_OFFSETS):
                    t[(root + iv + off) % 12] += _HARMONIC_DECAY**h
            chords.append(Chord(root, quality))
            rows.append(t / np.linalg.norm(t))
    return chords, np.array(rows)


class ChordModel:
    """The trained classifier (see tools/train_chords.py): 36 features -> 24 chord scores.

    One small network answers "major or minor chord on C?" and is applied to all
    12 transpositions of the input, so every root shares the same weights.
    """

    def __init__(self, path: Path = MODEL_PATH):
        d = np.load(path)
        self.w1, self.b1, self.w2, self.b2 = d["w1"], d["b1"], d["w2"], d["b2"]
        self.mean, self.std = float(d["mean"]), float(d["std"])

    def probabilities(self, features: np.ndarray) -> np.ndarray:
        x = (np.stack([rotate(features, -r) for r in range(12)]) - self.mean) / self.std
        out = np.maximum(0, x @ self.w1 + self.b1) @ self.w2 + self.b2  # (12, 2)
        logits = np.concatenate([out[:, 0], out[:, 1]])
        e = np.exp(logits - logits.max())
        return e / e.sum()


class ChordDetector:
    """Feed it audio blocks; read `.chord`, `.key` and `.active`.

    Thread model: `feed` is called from the audio thread, the properties are read
    from the engine thread. Everything shared is a single attribute write.

    `classifier` is "model" (the trained network), "templates" (triad templates,
    no training data involved) or "auto" (the model if its file is present).
    """

    def __init__(
        self,
        sample_rate: float,
        n_fft: int = 8192,
        hop: int = 2048,
        gate_db: float = -50.0,
        stable_frames: int = 4,
        min_confidence: float | None = None,
        tonal_min: float = 0.3,
        key_half_life_s: float = 45.0,
        fixed_key: Key | None = None,
        incumbent_bonus: float | None = None,
        smooth_s: float = 0.15,
        first_extra_frames: int = 3,
        own_mode: str = "weighted",  # "off" | "weighted"
        classifier: str = "auto",
        clock=time.monotonic,
    ):
        self.sr = sample_rate
        self.n_fft = n_fft
        self.hop = hop
        self.gate = 10 ** (gate_db / 20)
        self.stable_frames = stable_frames
        self.tonal_min = tonal_min
        self.first_extra_frames = first_extra_frames
        self.fixed_key = fixed_key
        self.own_mode = own_mode
        self._clock = clock

        if classifier == "auto":
            classifier = "model" if MODEL_PATH.exists() else "templates"
        self.model = ChordModel() if classifier == "model" else None
        # Confidence is a probability for the model and a correlation for templates.
        self.min_confidence = min_confidence if min_confidence is not None else (0.3 if self.model else 0.75)
        self.incumbent_bonus = incumbent_bonus if incumbent_bonus is not None else (0.15 if self.model else 0.12)

        self._buf = np.zeros(n_fft, dtype=np.float32)
        self._pending = 0
        self._bands = ChromaBands(sample_rate, n_fft)
        self._chords, self._templates = _chord_templates()
        self._centred_templates = self._templates - self._templates.mean(axis=1, keepdims=True)
        self._centred_templates /= np.linalg.norm(self._centred_templates, axis=1, keepdims=True)

        self._smooth = np.zeros(N_FEATURES)
        frame_s = hop / sample_rate
        self._smooth_alpha = 1 - np.exp(-frame_s / smooth_s)
        self._key_decay = 0.5 ** (frame_s / key_half_life_s)
        self._key_hist = np.zeros(12)
        self._distinct: set[Chord] = set()

        self._candidate: Chord | None = None
        self._candidate_count = 0
        # Our own notes: MIDI pitch -> (time it stopped, inf while held; cancel when scoring).
        self._own: dict[int, tuple[float, bool]] = {}
        self.own_tail_s = 0.4

        self.chord: Chord | None = None
        self.key: Key | None = fixed_key
        self.confidence = 0.0
        self.last_heard = -1e9

    # ------------------------------------------------------------------ input

    def feed(self, block: np.ndarray) -> None:
        block = np.asarray(block, dtype=np.float32).reshape(-1)
        while len(block):
            take = min(len(block), self.hop - self._pending)
            self._buf = np.concatenate([self._buf[take:], block[:take]])
            self._pending += take
            block = block[take:]
            if self._pending >= self.hop:
                self._pending = 0
                self._analyse()

    # The notes we play can leak back into what we hear (same DAW output, or a
    # speaker near a microphone). We know exactly which notes are ours.
    #
    # Only the lead is hidden when judging the chord: bass and arpeggio notes are
    # chord tones with dense harmonics, and hiding them hides the guitar too
    # (measured: it triples reaction time). All of our notes are still discounted
    # when deciding whether the player is playing at all.

    def own_note_on(self, pitch: int, cancel: bool = True) -> None:
        self._own[pitch] = (float("inf"), cancel)

    def own_note_off(self, pitch: int) -> None:
        if pitch in self._own:
            self._own[pitch] = (self._clock(), self._own[pitch][1])

    def _own_pitches(self, every_voice: bool) -> list[int]:
        if self.own_mode == "off":
            return []
        now = self._clock()
        pitches = []
        for pitch, (ended, cancel) in list(self._own.items()):
            if now - ended > self.own_tail_s:
                self._own.pop(pitch, None)
            elif cancel or every_voice:
                pitches.append(pitch)
        return pitches

    def active(self, tail_s: float) -> bool:
        """True while the guitar has been heard within the last `tail_s` seconds."""
        return self.chord is not None and (self._clock() - self.last_heard) <= tail_s

    # --------------------------------------------------------------- analysis

    def _analyse(self) -> None:
        recent = self._buf[-self.hop :]
        if float(np.sqrt(np.mean(recent**2))) < self.gate:
            # Silence: keep the last chord (the engine decides when to stop).
            self._candidate_count = 0
            return

        bands = self._bands
        spectrum = bands.spectrum(self._buf)
        ours = bands.harmonic_mask(self._own_pitches(every_voice=True))
        if ours is not None and (spectrum * ours).sum() < 0.2 * spectrum.sum():
            return  # nearly all of it is our own playing: no evidence about the player
        features = bands.features(spectrum, bands.harmonic_mask(self._own_pitches(every_voice=False)))
        norm = np.linalg.norm(features)
        if norm == 0:
            return
        self._smooth += self._smooth_alpha * (features / norm - self._smooth)

        # Is this pitched, chord-like sound at all? (Noise and drums are not.)
        chroma = self._smooth.reshape(-1, 12).sum(axis=0)
        v = chroma - chroma.mean()
        vn = np.linalg.norm(v)
        if vn == 0:
            return
        template_scores = (self._centred_templates @ v) / vn
        if self.model is None:
            scores = template_scores
        else:
            if template_scores.max() < self.tonal_min:
                self._candidate_count = 0
                return
            scores = self.model.probabilities(self._smooth)
        if self.chord is not None:
            # The chord we already believe in wins near-ties (fewer false flips).
            scores = scores.copy()
            scores[self._chords.index(self.chord)] += self.incumbent_bonus
        best = int(np.argmax(scores))
        self.confidence = float(scores[best])
        if self.confidence < self.min_confidence:
            self._candidate_count = 0
            return

        self.last_heard = self._clock()
        cand = self._chords[best]
        if cand == self._candidate:
            self._candidate_count += 1
        else:
            self._candidate, self._candidate_count = cand, 1
        # The very first chord needs longer to settle: the analysis window is still
        # filling and all it has heard is the attack of one strum.
        needed = self.stable_frames + (self.first_extra_frames if self.chord is None else 0)
        if self._candidate_count >= needed and cand != self.chord:
            self.chord = cand

        if self.chord is not None and self.chord == cand:
            self._key_hist *= self._key_decay
            for pc in self.chord.pitch_classes:
                self._key_hist[pc] += 1.0
            self._distinct.add(self.chord)
            if self.fixed_key is None and len(self._distinct) >= 2:
                self.key = estimate_key(self._key_hist)


def estimate_key(histogram: np.ndarray) -> Key | None:
    """Krumhansl-Schmuckler: correlate a pitch-class histogram with 24 key profiles."""
    if not np.any(histogram):
        return None
    best, best_r = None, -2.0
    for mode, profile in (("major", _KK_MAJOR), ("minor", _KK_MINOR)):
        for tonic in range(12):
            r = np.corrcoef(histogram, np.roll(profile, tonic))[0, 1]
            if r > best_r:
                best, best_r = Key(tonic, mode), r
    return best
