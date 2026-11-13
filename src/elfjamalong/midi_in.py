"""Chords from a MIDI keyboard (or any MIDI track): read from the held notes, no audio involved.

`MidiChords` offers what the engine needs from `ChordDetector`: `.chord`, `.key`,
`.active()`, `.energy`, `.since_onset()`.
"""

from __future__ import annotations

import time

import numpy as np

from .chords import estimate_key
from .theory import Chord, Key, TRIADS


def chord_from_notes(pitches) -> Chord | None:
    """The major or minor chord these MIDI notes spell, or None if they do not spell one.

    Needs the root and the third. Extra notes count against a candidate, the lowest
    note being the root counts for it, so C-E-G-A over a C bass is C and over an A bass is Am.
    """
    pitches = sorted(pitches)
    pcs = {p % 12 for p in pitches}
    if len(pcs) < 2:
        return None
    best, best_score = None, 0.0
    for quality, intervals in TRIADS.items():
        for root in range(12):
            tones = {(root + i) % 12 for i in intervals}
            third = (root + intervals[1]) % 12
            if root not in pcs or third not in pcs:
                continue
            flat7 = (root + 10) % 12
            extras = pcs - tones - {flat7}
            score = len(pcs & tones) - 0.5 * len(extras) + (0.75 if pitches[0] % 12 == root else 0.0)
            if score > best_score:
                best_score = score
                best = Chord(root, quality, seventh=quality == "maj" and flat7 in pcs)
    return best


class MidiChords:
    def __init__(self, fixed_key: Key | None = None, clock=time.monotonic):
        self._clock = clock
        self.fixed_key = fixed_key
        self._held: dict[int, int] = {}
        self._hist = np.zeros(12)
        self._distinct: set[Chord] = set()
        self._velocity_fast = self._velocity_slow = 80.0
        self.chord: Chord | None = None
        self.key: Key | None = fixed_key
        self.energy = 0.5
        self.last_onset = -1e9
        self.last_heard = -1e9

    def feed(self, message) -> None:
        """Takes mido messages (anything with .type, .note, .velocity)."""
        if message.type == "note_on" and message.velocity > 0:
            self._held[message.note] = message.velocity
            self.last_onset = self.last_heard = self._clock()
            self._velocity_fast += 0.4 * (message.velocity - self._velocity_fast)
            self._velocity_slow += 0.02 * (message.velocity - self._velocity_slow)
            self.energy = float(np.clip(0.5 + (self._velocity_fast - self._velocity_slow) / 50.0, 0.0, 1.0))
            chord = chord_from_notes(self._held)
            if chord is not None:
                changed = chord != self.chord
                self.chord = chord
                if changed:
                    self._hist *= 0.9
                    for pc in chord.pitch_classes:
                        self._hist[pc] += 1.0
                    self._distinct.add(chord)
                    if self.fixed_key is None and len(self._distinct) >= 2:
                        self.key = estimate_key(self._hist)
        elif message.type in ("note_off", "note_on"):
            self._held.pop(message.note, None)

    def since_onset(self) -> float:
        return self._clock() - self.last_onset

    def active(self, tail_s: float) -> bool:
        if self.chord is None:
            return False
        return bool(self._held) or (self._clock() - self.last_heard) <= tail_s

    # The engine reports its own notes to whoever listens; a keyboard does not hear them.
    def own_note_on(self, pitch: int, cancel: bool = True) -> None: ...

    def own_note_off(self, pitch: int) -> None: ...
