"""Musical time: where are we in the bar right now?"""

from __future__ import annotations

import time


class InternalClock:
    """Free-running clock at a fixed tempo, for use without a DAW."""

    def __init__(self, bpm: float = 120.0):
        self.tempo = bpm
        self._t0 = time.monotonic()

    def beat(self) -> float:
        return (time.monotonic() - self._t0) * self.tempo / 60.0

    @property
    def playing(self) -> bool:
        return True

    @property
    def peers(self) -> int:
        return 0


class LinkClock:
    """Ableton Link session clock: shares tempo and bar phase with Live (or Logic)."""

    def __init__(self, bpm: float = 120.0, quantum: float = 4.0):
        import link  # LinkPython-extern

        self.quantum = quantum
        self._link = link.Link(bpm)
        self._link.startStopSyncEnabled = True
        self._link.enabled = True

    def _state(self):
        return self._link.captureSessionState()

    def beat(self) -> float:
        return self._state().beatAtTime(self._link.clock().micros(), self.quantum)

    @property
    def tempo(self) -> float:
        return self._state().tempo()

    @property
    def playing(self) -> bool:
        return self._state().isPlaying()

    @property
    def peers(self) -> int:
        return self._link.numPeers()
