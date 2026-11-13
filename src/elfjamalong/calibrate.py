"""Measure how long a note takes to come back as sound, to choose `--offset-ms`."""

from __future__ import annotations

import statistics


def onset_delays(blocks: list[tuple[float, float]], sent: list[float], window_s: float = 0.4) -> list[float]:
    """Delay from each note sent to the first jump in level after it.

    `blocks` is (arrival time, RMS level) for each audio block heard; `sent` is when
    each note was sent, on the same clock. Notes that produced no clear jump are
    left out.
    """
    if not blocks:
        return []
    floor = statistics.median(level for _, level in blocks)
    peak = max(level for _, level in blocks)
    if peak < 4 * max(floor, 1e-6):
        return []  # nothing stood out from the background
    threshold = floor + 0.25 * (peak - floor)
    delays = []
    for t0 in sent:
        hit = next((t for t, level in blocks if t0 <= t <= t0 + window_s and level >= threshold), None)
        if hit is not None:
            delays.append(hit - t0)
    return delays


def summary(delays: list[float], notes: int) -> list[str]:
    if len(delays) < max(3, notes // 2):
        return [f"heard only {len(delays)} of {notes} test notes. Is the instrument track armed (or Monitor set to In), "
                "audible, and is this the input that hears it?"]
    ms = sorted(1000 * d for d in delays)
    middle = statistics.median(ms)
    return [
        f"heard {len(delays)} of {notes} notes: {ms[0]:.0f} to {ms[-1]:.0f} ms after they were sent, median {middle:.0f} ms",
        f"try  --offset-ms {round(middle)}  (or offset-ms = {round(middle)} in elfjamalong.toml)",
        "this includes the time the sound takes to come back in through the input, so it is an upper limit",
    ]
