"""Turns clock time + heard harmony into MIDI notes, one monophonic line per voice."""

from __future__ import annotations

import math
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Callable, Protocol

from .melody import Context, MelodyGenerator
from .theory import Chord, Key, scale_for

Harmony = tuple[Chord, Key | None]


class NoteSink(Protocol):
    def note_on(self, pitch: int, velocity: int) -> None: ...
    def note_off(self, pitch: int) -> None: ...


@dataclass
class Voice:
    """One role (lead, bass, arp): a generator and where its notes go."""

    name: str
    generator: MelodyGenerator
    sink: NoteSink
    _sounding: int | None = field(default=None, repr=False)
    _off_beat: float = field(default=0.0, repr=False)

    def release(self) -> None:
        if self._sounding is not None:
            self.sink.note_off(self._sounding)
            self._sounding = None


@dataclass(frozen=True)
class PlayedNote:
    voice: str
    start_beat: float
    pitch: int
    velocity: int
    length_beats: float


class Engine:
    """Call `tick(beat)` often. `harmony()` returns None while nobody is playing."""

    def __init__(
        self,
        voices: list[Voice] | MelodyGenerator,
        sink_or_harmony,
        harmony: Callable[[], Harmony | None] | None = None,
        history_bars: int = 64,
        tracker=None,  # a loop.ProgressionTracker: predicts the chord of a repeating progression
        feel: Callable[[], tuple[float, float | None]] | None = None,  # -> (energy 0-1, sixteenths since a strum)
    ):
        if harmony is None:  # Engine(voices, harmony)
            self.voices, self.harmony = voices, sink_or_harmony
        else:  # Engine(generator, sink, harmony): a single lead voice
            self.voices, self.harmony = [Voice("lead", voices, sink_or_harmony)], harmony
        self.tracker = tracker
        self.feel = feel
        self._step: int | None = None
        self._idle = True
        self.history: deque[PlayedNote] = deque()
        self._history_beats = history_bars * 4
        self._lock = threading.Lock()

    def _reset(self) -> None:
        for v in self.voices:
            v.release()
            v.generator.reset()
        if self.tracker is not None:
            self.tracker.reset()

    def tick(self, beat: float) -> None:
        for v in self.voices:
            if v._sounding is not None and beat >= v._off_beat:
                v.release()
        step = math.floor(beat * 4)
        if step == self._step:
            return
        if self._step is not None and not (0 < step - self._step <= 4):
            # Transport jumped (loop, relocate, tempo-sync correction): start clean.
            self._reset()
        self._step = step

        state = self.harmony()
        if state is None:
            if not self._idle:
                self._reset()
                self._idle = True
            return
        self._idle = False
        chord, key = state
        next_chord = None
        if self.tracker is not None:
            chord, next_chord = self.tracker.update(step, chord)
        energy, since_onset = self.feel() if self.feel is not None else (0.5, None)
        ctx = Context(step, chord, key, next_chord, energy, since_onset)
        allowed = scale_for(chord, key)
        for v in self.voices:
            # A note held from the previous chord that the new harmony does not allow is cut.
            if v._sounding is not None and v._sounding % 12 not in allowed:
                v.release()
                self._shorten_last(v.name, step / 4)
            event = v.generator.step(ctx)
            if event is None:
                continue
            v.release()
            v.sink.note_on(event.pitch, event.velocity)
            v._sounding = event.pitch
            v._off_beat = step / 4 + event.length_steps / 4
            with self._lock:
                self.history.append(PlayedNote(v.name, step / 4, event.pitch, event.velocity, event.length_steps / 4))
                while self.history and self.history[0].start_beat < step / 4 - self._history_beats:
                    self.history.popleft()

    def _shorten_last(self, voice: str, end_beat: float) -> None:
        """Record that `voice`'s most recent note was cut off at `end_beat`."""
        with self._lock:
            for i in range(len(self.history) - 1, -1, -1):
                n = self.history[i]
                if n.voice == voice:
                    length = max(0.0, min(n.length_beats, end_beat - n.start_beat))
                    self.history[i] = PlayedNote(n.voice, n.start_beat, n.pitch, n.velocity, length)
                    return

    def last_bars(self, bars: int) -> tuple[list[PlayedNote], int]:
        """Notes from the last `bars` complete bars, re-timed to start at beat 0.

        Leading empty bars are dropped. Returns (notes, number of bars kept).
        """
        if self._step is None:
            return [], 0
        end = (self._step // 16) * 4  # beat where the current bar began
        start = end - bars * 4
        with self._lock:
            notes = [n for n in self.history if start <= n.start_beat < end]
        if not notes:
            return [], 0
        first_bar = int((min(n.start_beat for n in notes) - start) // 4)
        start += first_bar * 4
        out = [
            PlayedNote(n.voice, n.start_beat - start, n.pitch, n.velocity, min(n.length_beats, end - n.start_beat))
            for n in notes
        ]
        return out, int((end - start) // 4)

    def stop(self) -> None:
        for v in self.voices:
            v.release()


def run_realtime(engine: Engine, clock, stop: threading.Event, offset_ms: float = 0.0) -> None:
    """Drive the engine from a live clock until `stop` is set.

    `offset_ms` > 0 plays early by that much, to cancel instrument/audio latency.
    """
    try:
        while not stop.is_set():
            ahead = offset_ms / 1000.0 * clock.tempo / 60.0
            engine.tick(clock.beat() + ahead)
            time.sleep(0.002)
    finally:
        engine.stop()
