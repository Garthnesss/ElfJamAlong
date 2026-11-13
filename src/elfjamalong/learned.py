"""A lead learned from guitar solos (see tools/train_melody.py), behind the same interface as the rules.

Each sixteenth the network sees where it is in the bar, what it played over the
last half bar, and the harmony, and gives the chance of starting a note at each
interval from its previous note (or of starting nothing). A second output gives
the note's length. Everything is relative to the chord and key, so one model
serves all keys. Notes outside the allowed scale or range are never chosen.
"""

from __future__ import annotations

import random
from collections import deque
from pathlib import Path

import numpy as np

from .melody import STEPS_PER_BAR, Context, NoteEvent
from .theory import Chord, Key, scale_for

MODEL_PATH = Path(__file__).with_name("melody_model.npz")
HISTORY = 8
MAX_LEAP = 12
NO_NOTE = 2 * MAX_LEAP + 1  # class index: nothing starts on this step
N_CLASSES = NO_NOTE + 1
DURATIONS = (1, 2, 3, 4, 6, 8, 12, 16)
N_FEATURES = 16 + HISTORY * N_CLASSES + 1 + 12 + 2 + 12 + 2 + 1 + 1 + 15 + 1


def features(pos: int, history, previous: int, sounding: bool, since_note: int, chord: Chord, changed: bool,
             key: Key | None, next_chord: Chord | None) -> np.ndarray:
    f = np.zeros(N_FEATURES, dtype=np.float32)
    f[pos] = 1
    at = 16
    for token in history:  # oldest first, exactly HISTORY of them
        f[at + token] = 1
        at += N_CLASSES
    f[at] = sounding
    at += 1
    f[at + (previous - chord.root) % 12] = 1
    at += 12
    f[at + (chord.quality == "min")] = 1
    at += 2
    if key is not None:
        f[at + (previous - key.tonic) % 12] = 1
        f[at + 12 + (key.mode == "minor")] = 1
    at += 14
    f[at] = (previous - 72) / 12
    f[at + 1] = changed
    at += 2
    if next_chord is not None:
        f[at + (next_chord.root - chord.root) % 12] = 1
        f[at + 12 + (next_chord.quality == "min")] = 1
        f[at + 14] = 1
    at += 15
    f[at] = min(since_note, 16) / 16
    return f


def forward(p, x):
    h = np.maximum(0, x @ p["w1"] + p["b1"])
    return h, h @ p["w_note"] + p["b_note"], h @ p["w_len"] + p["b_len"]


def _softmax(z):
    e = np.exp(z - z.max())
    return e / e.sum()


class LearnedMelody:
    def __init__(self, low: int = 60, high: int = 84, density: float = 0.5, seed: int | None = None,
                 temperature: float = 0.9, repeat_weight: float = 0.4, path: Path | None = None):
        self.low, self.high = low, high
        self.density = max(0.05, min(1.0, density))
        self.temperature = temperature
        # Left to itself the model repeats a note far more often than the solos do (one
        # repeat makes the next more likely); this brings it back to their one in five.
        self.repeat_weight = repeat_weight
        self.rng = random.Random(seed)
        d = np.load(path or MODEL_PATH)
        self.p = {k: d[k] for k in d.files}
        # The solos start a note on this share of sixteenths; `density` 0.5 keeps that.
        self.usual_rate = float(d["note_rate"])
        self.reset()

    def reset(self) -> None:
        self._history = deque([NO_NOTE] * HISTORY, maxlen=HISTORY)
        self._previous = (self.low + self.high) // 2
        self._until = -1
        self._last_note = -99
        self._chord: Chord | None = None
        self._step: int | None = None

    def step(self, ctx: Context) -> NoteEvent | None:
        if self._step is not None and ctx.step - self._step > 1:
            for _ in range(min(ctx.step - self._step - 1, HISTORY)):  # steps we were not asked about
                self._history.append(NO_NOTE)
        self._step = ctx.step
        pos = ctx.step % STEPS_PER_BAR
        changed = self._chord is not None and ctx.chord != self._chord
        self._chord = ctx.chord
        x = features(pos, self._history, self._previous, ctx.step < self._until, ctx.step - self._last_note,
                     ctx.chord, changed, ctx.key, ctx.next_chord)
        _, note_logits, length_logits = forward(self.p, x)
        prob = _softmax(note_logits / self.temperature)

        natural = prob[:NO_NOTE].sum()  # the model's own chance that a note starts here
        prob[MAX_LEAP] *= self.repeat_weight
        # Solo guitar sits lower than this range: lean toward its middle, as the rules do.
        centre, span = (self.low + self.high) / 2, (self.high - self.low) / 2
        for k in range(NO_NOTE):
            prob[k] *= np.exp(-0.7 * ((self._previous + k - MAX_LEAP - centre) / span) ** 2)
        # A note the scale or the range does not allow gives its chance to the nearest allowed
        # note further along in the same direction (else the nearest at all), so a semitone
        # step the scale lacks becomes a whole-tone step, not a repeated note.
        allowed = scale_for(ctx.chord, ctx.key)
        ok = [self.low <= self._previous + k - MAX_LEAP <= self.high and (self._previous + k - MAX_LEAP) % 12 in allowed
              for k in range(NO_NOTE)]
        for k in range(NO_NOTE):
            if ok[k] or prob[k] == 0.0:
                continue
            away = 1 if k >= MAX_LEAP else -1
            targets = [j for j in (k + away, k + 2 * away, k - away, k - 2 * away) if 0 <= j < NO_NOTE and ok[j]]
            if targets:
                prob[targets[0]] += prob[k]
            prob[k] = 0.0
        # Busier or sparser than the solos it learned from, as asked and as the player plays.
        start = prob[:NO_NOTE].sum()
        if start <= 0:
            self._history.append(NO_NOTE)
            return None
        want = min(0.97, natural * (self.density / 0.5) * (0.6 + 0.8 * ctx.energy))
        prob[:NO_NOTE] *= want / start
        prob[NO_NOTE] = 1 - want
        token = self.rng.choices(range(N_CLASSES), prob)[0]
        self._history.append(token)
        if token == NO_NOTE:
            return None

        pitch = self._previous + token - MAX_LEAP
        length = DURATIONS[self.rng.choices(range(len(DURATIONS)), _softmax(length_logits / self.temperature))[0]]
        self._previous, self._last_note, self._until = pitch, ctx.step, ctx.step + length
        base = 100 if pos == 0 else 88 if pos % 4 == 0 else 76
        velocity = max(1, min(127, base + round((ctx.energy - 0.5) * 30) + self.rng.randint(-6, 6)))
        return NoteEvent(pitch, velocity, length * 0.9)
