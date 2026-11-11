"""Melody generators.

A generator is asked once per 16th-note step what (if anything) to play, given
the chord and key heard so far. That is the whole interface, so a trained model
can replace `RuleBasedMelody` later without touching audio, timing or MIDI.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import Protocol

from .theory import Chord, Key, scale_for

STEPS_PER_BAR = 16
PHRASE_BARS = 4


@dataclass(frozen=True)
class Context:
    step: int  # global 16th-note index; step % 16 == 0 is a downbeat
    chord: Chord
    key: Key | None


@dataclass(frozen=True)
class NoteEvent:
    pitch: int
    velocity: int
    length_steps: float


class MelodyGenerator(Protocol):
    def step(self, ctx: Context) -> NoteEvent | None: ...
    def reset(self) -> None: ...


# Chance of a note starting on each 16th of the bar at density 0.5.
_ONSET_BASE = [0.9, 0.1, 0.45, 0.12, 0.6, 0.1, 0.45, 0.15, 0.65, 0.1, 0.45, 0.12, 0.55, 0.1, 0.4, 0.15]
# Preference by distance in scale steps from the previous note.
_STEP_WEIGHT = {0: 0.5, 1: 3.0, 2: 1.6, 3: 0.6, 4: 0.4, 5: 0.15, 6: 0.1, 7: 0.1}


class RuleBasedMelody:
    """Chord tones on strong beats, stepwise scale motion between them.

    Phrases are four bars: a rhythmic motif, a variation, the motif again with
    its contour, then a sparse ending that leaves room to breathe.
    """

    def __init__(self, low: int = 60, high: int = 84, density: float = 0.5, seed: int | None = None):
        self.low, self.high = low, high
        self.density = max(0.05, min(1.0, density))
        self.rng = random.Random(seed)
        self.reset()

    def reset(self) -> None:
        self._last: int | None = None
        self._last_move = 0
        self._direction = 1
        self._motif: list[int] = []
        self._onsets: list[int] = []
        self._contour: dict[int, int] = {}
        self._bar_seen = -1
        self._phrase_start: int | None = None

    # ---------------------------------------------------------------- rhythm

    def _new_rhythm(self) -> list[int]:
        scale = self.density / 0.5
        onsets = [s for s, p in enumerate(_ONSET_BASE) if self.rng.random() < min(0.97, p * scale)]
        while len(onsets) < 2:
            onsets = sorted(set(onsets) | {self.rng.choice([0, 4, 8, 12])})
        return onsets

    def _plan_bar(self, bar_in_phrase: int) -> list[int]:
        if bar_in_phrase == 0 or not self._motif:
            self._motif = self._new_rhythm()
            self._contour = {}
            return list(self._motif)
        if bar_in_phrase == 1:
            varied = set(self._motif)
            for _ in range(self.rng.choice([1, 2])):
                if varied and self.rng.random() < 0.5:
                    varied.discard(self.rng.choice(sorted(varied)))
                else:
                    varied.add(self.rng.choice([2, 6, 10, 12, 14]))
            return sorted(varied) or [0]
        if bar_in_phrase == 2:
            return list(self._motif)
        ending = [s for s in self._motif if s < 8]
        return ending if ending else [0]

    # ----------------------------------------------------------------- pitch

    def _choose(self, pool: list[int], chord: Chord, strong: bool, downbeat: bool, final: bool,
                target: int | None) -> int:
        chord_pcs = chord.pitch_classes
        if self._last is None:
            centre = (self.low + self.high) / 2
            tones = [p for p in pool if p % 12 in chord_pcs]
            return min(tones or pool, key=lambda p: abs(p - centre))

        last_idx = min(range(len(pool)), key=lambda i: abs(pool[i] - self._last))
        if target is not None:
            idx = max(0, min(len(pool) - 1, last_idx + target))
            if strong and pool[idx] % 12 not in chord_pcs:
                tones = [i for i, p in enumerate(pool) if p % 12 in chord_pcs]
                if tones:
                    idx = min(tones, key=lambda i: abs(i - idx))
            return pool[idx]

        centre = (self.low + self.high) / 2
        span = (self.high - self.low) / 2
        weights = []
        for i, p in enumerate(pool):
            d = i - last_idx
            w = _STEP_WEIGHT.get(abs(d), 0.0)
            if w == 0.0:
                weights.append(0.0)
                continue
            is_tone = p % 12 in chord_pcs
            if downbeat or final:
                w *= 8.0 if is_tone else 0.1
            elif strong:
                w *= 4.0 if is_tone else 0.35
            elif is_tone:
                w *= 1.3
            if d * self._direction > 0:
                w *= 1.4
            if abs(self._last_move) >= 3 and d * self._last_move < 0 and abs(d) <= 2:
                w *= 2.0  # step back after a leap
            w *= math.exp(-(((p - centre) / span) ** 2))
            weights.append(w)
        if not any(weights):
            return pool[last_idx]
        return self.rng.choices(pool, weights)[0]

    # ------------------------------------------------------------------ step

    def step(self, ctx: Context) -> NoteEvent | None:
        if self._phrase_start is None:
            # Phrases begin on the first downbeat after the generator wakes up.
            if ctx.step % STEPS_PER_BAR != 0:
                return None
            self._phrase_start = ctx.step
        rel = ctx.step - self._phrase_start
        bar, pos = divmod(rel, STEPS_PER_BAR)
        bar_in_phrase = bar % PHRASE_BARS
        if bar != self._bar_seen:
            self._bar_seen = bar
            self._onsets = self._plan_bar(bar_in_phrase)
        if pos not in self._onsets:
            return None

        later = [s for s in self._onsets if s > pos]
        final = bar_in_phrase == PHRASE_BARS - 1 and not later
        length = (later[0] - pos) if later else (STEPS_PER_BAR - pos)
        length = min(length, 6 if final else 8)

        allowed = scale_for(ctx.chord, ctx.key)
        pool = [p for p in range(self.low, self.high + 1) if p % 12 in allowed]
        if not pool:
            return None
        strong = pos % 4 == 0 or length >= 4
        target = None
        if bar_in_phrase == 2 and pos in self._contour and self.rng.random() < 0.75:
            target = self._contour[pos]
        pitch = self._choose(pool, ctx.chord, strong, pos == 0, final, target)

        if self._last is not None:
            move = pool.index(pitch) - min(range(len(pool)), key=lambda i: abs(pool[i] - self._last))
            if bar_in_phrase == 0:
                self._contour[pos] = move
            self._last_move = move
        self._last = pitch
        if pitch >= self.high - 2:
            self._direction = -1
        elif pitch <= self.low + 2:
            self._direction = 1
        elif self.rng.random() < 0.25:
            self._direction = -self._direction

        base = 100 if pos == 0 else 88 if pos % 4 == 0 else 76
        velocity = max(1, min(127, base + self.rng.randint(-6, 6)))
        return NoteEvent(pitch, velocity, length * 0.9)
