"""Live chord and key detection from a mono audio stream."""

from __future__ import annotations

import time
from pathlib import Path

import numpy as np

from .features import N_FEATURES, SMOOTH_S, ChromaBands, rotate
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
    12 transpositions of the input, so every root shares the same weights. The
    file may hold several such networks trained from different starting points;
    their log-probabilities are averaged.
    """

    def __init__(self, path: Path | None = None):
        d = np.load(path or MODEL_PATH)
        stacked = d["w1"].ndim == 3
        self.members = [
            tuple(d[k][i] if stacked else d[k] for k in ("w1", "b1", "w2", "b2"))
            for i in range(len(d["w1"]) if stacked else 1)
        ]
        self.mean, self.std = float(d["mean"]), float(d["std"])
        # Optional second network: is this major chord a dominant seventh?
        self.seventh_net = tuple(d[k] for k in ("s_w1", "s_b1", "s_w2", "s_b2")) if "s_w1" in d.files else None

    def seventh(self, features: np.ndarray, root: int) -> float:
        """Chance that the major chord on `root` is a dominant seventh (0.0 if the model cannot tell)."""
        if self.seventh_net is None:
            return 0.0
        w1, b1, w2, b2 = self.seventh_net
        x = (rotate(features, -root) - self.mean) / self.std
        z = float(np.maximum(0, x @ w1 + b1) @ w2 + b2)
        return 1 / (1 + np.exp(-z))

    def probabilities(self, features: np.ndarray) -> np.ndarray:
        x = (np.stack([rotate(features, -r) for r in range(12)]) - self.mean) / self.std
        total = np.zeros(24)
        for w1, b1, w2, b2 in self.members:
            out = np.maximum(0, x @ w1 + b1) @ w2 + b2  # (12, 2)
            logits = np.concatenate([out[:, 0], out[:, 1]])
            logits -= logits.max()
            total += logits - np.log(np.exp(logits).sum())
        total /= len(self.members)
        e = np.exp(total - total.max())
        return e / e.sum()


def _diatonic(key: Key) -> np.ndarray:
    """Which of the 24 chords belong to this key (minor keys include the major dominant)."""
    major_tonic = key.tonic if key.mode == "major" else (key.tonic + 3) % 12
    inside = np.zeros(24, dtype=bool)
    for interval in (0, 5, 7):
        inside[(major_tonic + interval) % 12] = True
    for interval in (2, 4, 9):
        inside[12 + (major_tonic + interval) % 12] = True
    if key.mode == "minor":
        inside[(key.tonic + 7) % 12] = True
    return inside


class ChordDetector:
    """Feed it audio blocks; read `.chord`, `.key` and `.active`.

    Thread model: `feed` is called from the audio thread, the properties are read
    from the engine thread. Everything shared is a single attribute write.

    `classifier` is "model" (the trained network), "templates" (triad templates,
    no training data involved) or "auto" (the model if its file is present).

    With the model, the chord is decided by a belief over the 24 chords that is
    carried from frame to frame: each frame it leaks a little toward the other
    chords (`stay`; `key_weight` times more toward chords of the key, once the
    key is known), is multiplied by the frame's probabilities (softened by
    `evidence_power`), and the reported chord changes when another chord's belief
    leads by `switch_margin`. The template matcher keeps the older rule: the same
    winner `stable_frames` analyses in a row.
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
        smooth_s: float | None = None,
        first_extra_frames: int = 3,
        stay: float = 0.9,
        evidence_power: float = 0.35,
        switch_margin: float = 0.3,
        key_weight: float = 4.0,
        seventh_on: float = 0.7,
        seventh_off: float = 0.5,
        own_mode: str = "weighted",  # "off" | "weighted"
        classifier: str = "auto",
        model_path: Path | str | None = None,
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
            classifier = "model" if model_path or MODEL_PATH.exists() else "templates"
        self.model = ChordModel(Path(model_path) if model_path else None) if classifier == "model" else None
        # Confidence is a probability for the model and a correlation for templates.
        self.min_confidence = min_confidence if min_confidence is not None else (0.3 if self.model else 0.75)
        self.incumbent_bonus = incumbent_bonus if incumbent_bonus is not None else 0.12
        self.stay, self.evidence_power, self.switch_margin = stay, evidence_power, switch_margin
        self.key_weight = key_weight
        self.seventh_on, self.seventh_off = seventh_on, seventh_off
        self._belief = np.full(24, 1 / 24)
        self._chord_prior = np.full(24, 1 / 24)
        self._seventh = 0.0
        self._seventh_alpha = 1 - np.exp(-(hop / sample_rate) / 0.5)
        self._frames_heard = 0
        if smooth_s is None:  # the templates were tuned with the longer smoothing
            smooth_s = SMOOTH_S if self.model else 0.15

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

        # How the player is playing: loudness against their own recent average, and strum onsets.
        self._level_fast: float | None = None
        self._level_slow: float | None = None
        self._fast_alpha = 1 - np.exp(-frame_s / 0.4)
        self._slow_alpha = 1 - np.exp(-frame_s / 20.0)
        self._recent_rms = [0.0, 0.0, 0.0]
        self.energy = 0.5  # 0 = much quieter than usual, 0.5 = usual, 1 = much louder
        self.last_onset = -1e9

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

    def since_onset(self) -> float:
        """Seconds since the player last struck the strings."""
        return self._clock() - self.last_onset

    def _feel(self, rms: float) -> None:
        if rms > 1.6 * (sum(self._recent_rms) / 3) and rms > 2 * self.gate:
            self.last_onset = self._clock()
        self._recent_rms = self._recent_rms[1:] + [rms]
        db = 20 * np.log10(max(rms, 1e-6))
        if self._level_fast is None:
            self._level_fast = self._level_slow = db
        self._level_fast += self._fast_alpha * (db - self._level_fast)
        self._level_slow += self._slow_alpha * (db - self._level_slow)
        self.energy = float(np.clip(0.5 + (self._level_fast - self._level_slow) / 12.0, 0.0, 1.0))

    def active(self, tail_s: float) -> bool:
        """True while the guitar has been heard within the last `tail_s` seconds."""
        return self.chord is not None and (self._clock() - self.last_heard) <= tail_s

    # --------------------------------------------------------------- analysis

    def _analyse(self) -> None:
        recent = self._buf[-self.hop :]
        rms = float(np.sqrt(np.mean(recent**2)))
        if rms < self.gate:
            self._recent_rms = self._recent_rms[1:] + [rms]
            # Silence: keep the last chord (the engine decides when to stop), but be
            # less sure of it, so whatever is played next is picked up quickly.
            self._candidate_count = 0
            self._belief = 0.8 * self._belief + 0.2 / 24
            return

        bands = self._bands
        spectrum = bands.spectrum(self._buf)
        ours = bands.harmonic_mask(self._own_pitches(every_voice=True))
        if ours is not None and (spectrum * ours).sum() < 0.2 * spectrum.sum():
            return  # nearly all of it is our own playing: no evidence about the player
        self._feel(rms)
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
        heard = self._by_templates(template_scores) if self.model is None else self._by_model(template_scores)
        if heard is None:
            return
        self.last_heard = self._clock()
        if self.chord is not None and self.chord == heard:
            self._key_hist *= self._key_decay
            for pc in self.chord.pitch_classes:
                self._key_hist[pc] += 1.0
            self._distinct.add(self.chord)
            if self.fixed_key is None and len(self._distinct) >= 2:
                self.key = estimate_key(self._key_hist)
            if self.key is not None and (self.fixed_key is not None or len(self._distinct) >= 2):
                prior = np.where(_diatonic(self.key), self.key_weight, 1.0)
                self._chord_prior = prior / prior.sum()

    def _by_model(self, template_scores: np.ndarray) -> Chord | None:
        """Update the belief with this frame; returns the frame's leading chord (None: not a chord)."""
        if template_scores.max() < self.tonal_min:
            return None
        probabilities = self.model.probabilities(self._smooth)
        if probabilities.max() < self.min_confidence:
            return None
        # Belief leaks toward the other chords, more of it toward chords of the key.
        b = self.stay * self._belief + (1 - self.stay) * self._chord_prior * 24 / 23 * (1 - self._belief)
        b *= np.maximum(probabilities, 0.02) ** self.evidence_power
        self._belief = b = b / b.sum()
        self._frames_heard += 1
        best = int(np.argmax(b))
        lead = self._chords[best]
        self.confidence = float(b[best])
        # The very first chord waits a few frames: the analysis window is still
        # filling and all it has heard is the attack of one strum.
        if self.chord is None:
            if self._frames_heard >= self.stable_frames + self.first_extra_frames - 2:
                self.chord, self._seventh = lead, 0.0
        elif lead != self.chord and b[best] > b[self._chords.index(self.chord)] + self.switch_margin:
            self.chord, self._seventh = lead, 0.0
        chord = self.chord
        if chord is not None and chord == lead and chord.quality == "maj":
            # Dominant seventh or plain major? Averaged over half a second, with a gap
            # between turning it on and off, so it does not flicker.
            self._seventh += self._seventh_alpha * (self.model.seventh(self._smooth, chord.root) - self._seventh)
            if (self._seventh > (self.seventh_off if chord.seventh else self.seventh_on)) != chord.seventh:
                self.chord = Chord(chord.root, "maj", seventh=not chord.seventh)
        return lead

    def _by_templates(self, scores: np.ndarray) -> Chord | None:
        if self.chord is not None:
            # The chord we already believe in wins near-ties (fewer false flips).
            scores = scores.copy()
            scores[self._chords.index(self.chord)] += self.incumbent_bonus
        best = int(np.argmax(scores))
        self.confidence = float(scores[best])
        if self.confidence < self.min_confidence:
            self._candidate_count = 0
            return None
        cand = self._chords[best]
        if cand == self._candidate:
            self._candidate_count += 1
        else:
            self._candidate, self._candidate_count = cand, 1
        needed = self.stable_frames + (self.first_extra_frames if self.chord is None else 0)
        if self._candidate_count >= needed and cand != self.chord:
            self.chord = cand
        return cand


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
