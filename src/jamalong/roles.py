"""Supporting roles that follow the same chord: a bass line and an arpeggio."""

from __future__ import annotations

import random

from .melody import STEPS_PER_BAR, Context, NoteEvent
from .theory import Chord, scale_for


def _nearest(pitch_class: int, target: int, low: int, high: int) -> int:
    """The pitch with this pitch class closest to `target`, kept inside [low, high]."""
    options = [p for p in range(low, high + 1) if p % 12 == pitch_class % 12]
    return min(options, key=lambda p: abs(p - target)) if options else target


# (step in bar, what to play): "r" root, "5" fifth, "8" octave, "w" walk toward the root.
_BASS_PATTERNS = [
    [(0, "r"), (6, "r"), (8, "5"), (14, "w")],
    [(0, "r"), (4, "r"), (8, "5"), (12, "r")],
    [(0, "r"), (3, "r"), (6, "8"), (10, "5"), (14, "w")],
    [(0, "r"), (8, "r"), (12, "5"), (14, "w")],
]


class BassLine:
    """Root on the downbeat, fifths and octaves after it, a passing note into the next bar."""

    def __init__(self, low: int = 33, high: int = 52, seed: int | None = None):
        self.low, self.high = low, high
        self.rng = random.Random(seed)
        self.reset()

    def reset(self) -> None:
        self._pattern = self.rng.choice(_BASS_PATTERNS)
        self._bar = -1
        self._last: int | None = None

    def step(self, ctx: Context) -> NoteEvent | None:
        bar, pos = divmod(ctx.step, STEPS_PER_BAR)
        if bar != self._bar:
            self._bar = bar
            if bar % 4 == 0 and self.rng.random() < 0.5:
                self._pattern = self.rng.choice(_BASS_PATTERNS)
        hit = next((i for i, (s, _) in enumerate(self._pattern) if s == pos), None)
        if hit is None:
            return None
        kind = self._pattern[hit][1]
        later = [s for s, _ in self._pattern[hit + 1 :]]
        length = (later[0] if later else STEPS_PER_BAR) - pos

        centre = (self.low + self.high) // 2
        root = _nearest(ctx.chord.root, centre - 3, self.low, self.high)
        if kind == "r":
            pitch = root
        elif kind == "5":
            pitch = _nearest(ctx.chord.root + 7, root, self.low, self.high)
        elif kind == "8":
            pitch = root + 12 if root + 12 <= self.high else root
        else:  # a scale tone one step below or above the root, leading back to it
            allowed = scale_for(ctx.chord, ctx.key)
            near = [p for p in (root - 2, root - 1, root + 1, root + 2) if p % 12 in allowed and p >= self.low]
            pitch = self.rng.choice(near) if near else root
        self._last = pitch
        velocity = max(1, min(127, (104 if pos == 0 else 90) + self.rng.randint(-5, 5)))
        return NoteEvent(pitch, velocity, length * 0.85)


_ARP_SHAPES = {
    "up": [0, 1, 2, 3, 0, 1, 2, 3],
    "updown": [0, 1, 2, 3, 2, 1, 0, 1],
    "broken": [0, 2, 1, 2, 0, 2, 1, 3],
}


class Arpeggio:
    """Even eighth notes through the chord's tones."""

    def __init__(self, low: int = 52, high: int = 76, seed: int | None = None):
        self.low, self.high = low, high
        self.rng = random.Random(seed)
        self.reset()

    def reset(self) -> None:
        self._shape = self.rng.choice(list(_ARP_SHAPES))
        self._bar = -1

    def _tones(self, chord: Chord) -> list[int]:
        centre = (self.low + self.high) // 2
        root = _nearest(chord.root, centre - 7, self.low, self.high)
        third = root + (4 if chord.quality == "maj" else 3)
        return [p for p in (root, third, root + 7, root + 12) if p <= self.high] or [root]

    def step(self, ctx: Context) -> NoteEvent | None:
        bar, pos = divmod(ctx.step, STEPS_PER_BAR)
        if bar != self._bar:
            self._bar = bar
            if bar % 4 == 0 and self.rng.random() < 0.4:
                self._shape = self.rng.choice(list(_ARP_SHAPES))
        if pos % 2:
            return None
        tones = self._tones(ctx.chord)
        index = _ARP_SHAPES[self._shape][pos // 2]
        pitch = tones[min(index, len(tones) - 1)]
        velocity = max(1, min(127, (78 if pos % 8 == 0 else 64) + self.rng.randint(-4, 4)))
        return NoteEvent(pitch, velocity, 1.8)
