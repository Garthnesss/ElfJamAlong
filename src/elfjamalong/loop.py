"""Know the loop: once a progression has gone round twice, say what comes next.

The detector reports a chord a moment after it is played, so the first notes of a
bar are otherwise chosen over the previous chord. When the chords heard repeat with
a period of whole bars, the tracker answers with what was heard at this point of
the previous round, shifted earlier by the detector's reaction time. The moment
what is heard no longer fits the loop it answers with what is heard instead, and
after a short run of such moments it forgets the loop.
"""

from __future__ import annotations

from typing import Callable

from .theory import Chord

STEPS_PER_BAR = 16
MAX_BARS = 8


class ProgressionTracker:
    def __init__(self, tempo: Callable[[], float] = lambda: 120.0, lag_s: float = 0.3,
                 agreement: float = 0.85, break_s: float = 0.35):
        self._tempo, self.lag_s, self.agreement, self.break_s = tempo, lag_s, agreement, break_s
        self.reset()

    def reset(self) -> None:
        self._heard: dict[int, Chord] = {}
        self._first: int | None = None
        self._last: int | None = None
        self._misses = 0
        self.loop_steps: int | None = None  # length of the loop being followed, if any

    def _steps(self, seconds: float) -> int:
        return round(seconds * self._tempo() / 60 * 4)

    def _find_loop(self, step: int) -> int | None:
        """The shortest whole-bar period over which the last round matches the one before."""
        for bars in range(1, MAX_BARS + 1):
            length = bars * STEPS_PER_BAR
            if step - self._first + 1 < 2 * length:
                return None
            same = sum(self._heard.get(s) == self._heard.get(s - length) for s in range(step - length + 1, step + 1))
            if same >= self.agreement * length:
                return length
        return None

    def _lag(self, step: int) -> int:
        """How many sixteenths late the detector reported the last round's chord changes.

        Chords change on the eighth-note grid, so a change heard on an odd sixteenth
        was an odd number late. Of the delays that fit, take the one nearest to the
        detector's usual reaction time (`lag_s`).
        """
        usual = self.lag_s * self._tempo() / 60 * 4
        lags = []
        for s in range(step - self.loop_steps + 1, step + 1):
            if s - 1 in self._heard and self._heard[s] != self._heard[s - 1]:
                lags.append(min((s % 2 + 2 * k for k in range(5)), key=lambda lag: abs(lag - usual)))
        return sorted(lags)[(len(lags) - 1) // 2] if lags else round(usual)

    def update(self, step: int, heard: Chord) -> tuple[Chord, Chord | None]:
        """Record the chord heard at `step`. Returns (chord to play over now, chord of the next bar or None)."""
        if self._last is not None and not (0 < step - self._last <= 4):
            self.reset()  # the clock jumped
        if self._first is None:
            self._first = step
        for s in range((self._last if self._last is not None else step - 1) + 1, step + 1):
            self._heard[s] = heard
        self._last = step
        for old in [s for s in self._heard if s < step - (2 * MAX_BARS + 1) * STEPS_PER_BAR]:
            del self._heard[old]

        if self.loop_steps is not None:
            # Still the loop? Changes may land a sixteenth early or late from round to round.
            before = step - self.loop_steps
            fits = heard in (self._heard.get(before - 1), self._heard.get(before), self._heard.get(before + 1))
            self._misses = 0 if fits else self._misses + 1
            if self._misses >= max(3, self._steps(self.break_s)):  # longer than a misread lasts: forget the loop
                self.reset()
                self._first = self._last = step
                self._heard[step] = heard
        if self.loop_steps is None:
            self.loop_steps = self._find_loop(step)
            self._misses = 0
        if self.loop_steps is None or self._misses:
            return heard, None  # no loop, or the player has just left it: follow what is heard

        lag = self._lag(step)
        now = self._heard.get(step - self.loop_steps + lag, heard)
        next_bar = (step // STEPS_PER_BAR + 1) * STEPS_PER_BAR
        return now, self._heard.get(next_bar - self.loop_steps + lag)
