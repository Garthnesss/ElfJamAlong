"""Train the learned lead on GuitarSet's solo excerpts (CC BY 4.0, Xi et al. 2018).

    uv run python tools/train_melody.py data/guitarset [--final]

Each solo is improvised over one of the chord charts the comping excerpts use.
Its notes are put on a sixteenth-note grid (from the annotated beats) next to the
chart's chords and key. Without --final it trains on players 00-03 and reports how
well it predicts players 04-05; with --final it trains on everyone and writes
src/elfjamalong/melody_model.npz. Only annotation.zip is needed.
"""

from __future__ import annotations

import argparse
import json
import sys
import zipfile
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from bench_guitarset import lead_sheet, reduce  # noqa: E402

from elfjamalong.learned import DURATIONS, HISTORY, MAX_LEAP, N_CLASSES, N_FEATURES, NO_NOTE, features, forward  # noqa: E402
from elfjamalong.theory import Key  # noqa: E402


def steps_of(jam: dict):
    """One solo as a list of (bar position, pitch or None, length in steps, chord, key) per sixteenth."""
    notes = sorted(
        (d["time"], d["duration"], round(d["value"]))
        for a in jam["annotations"] if a["namespace"] == "note_midi" for d in a["data"]
    )
    beats = next(a for a in jam["annotations"] if a["namespace"] == "beat_position")["data"]
    key_label = next(a for a in jam["annotations"] if a["namespace"] == "key_mode")["data"][0]["value"]
    key = Key.parse(key_label.replace(":", " "))
    sheet = lead_sheet(jam)
    times, positions = [], []
    for i, b in enumerate(beats):
        nxt = beats[i + 1]["time"] if i + 1 < len(beats) else b["time"] + (b["time"] - beats[i - 1]["time"])
        for k in range(4):
            times.append(b["time"] + k * (nxt - b["time"]) / 4)
            positions.append(((b["value"]["position"] - 1) * 4 + k) % 16)
    step_s = float(np.median(np.diff(times)))
    grid = np.array(times)
    starts: dict[int, tuple[int, float]] = {}
    for t, dur, pitch in notes:
        i = int(np.argmin(np.abs(grid - t)))
        if abs(grid[i] - t) > step_s:
            continue
        if i not in starts or pitch > starts[i][0]:  # two strings at once: keep the top note
            starts[i] = (pitch, dur)
    out = []
    for i, (t, pos) in enumerate(zip(times, positions)):
        seg = next((s for s in sheet if s[0] <= t + 1e-6 < s[1]), None)
        chord = reduce(seg[2]) if seg else None
        pitch, length = None, 0
        if i in starts:
            pitch = starts[i][0]
            later = min((j for j in starts if j > i), default=i + 16)
            length = max(1, min(round(starts[i][1] / step_s), later - i, 16))
        out.append((pos, pitch, length, chord, key))
    return out


def examples(solo, rng):
    """(features, note class, length class or -1) for every sixteenth of one solo."""
    pitches = [s[1] for s in solo if s[1] is not None]
    if len(pitches) < 4:
        return []
    previous = int(np.median(pitches))
    history = [NO_NOTE] * HISTORY
    until, last_note, last_chord = -1, -99, None
    rows = []
    for i, (pos, pitch, length, chord, key) in enumerate(solo):
        if chord is None:
            history, last_chord = [NO_NOTE] * HISTORY, None
            continue
        bar_end = i + (16 - pos)
        next_chord = solo[bar_end][3] if bar_end < len(solo) else None
        # At run time the key and the next chord are often unknown: train for that too.
        x = features(pos, history, previous, i < until, i - last_note, chord,
                     last_chord is not None and chord != last_chord,
                     key if rng.random() > 0.2 else None, next_chord if rng.random() > 0.5 else None)
        last_chord = chord
        if pitch is None:
            token, length_class = NO_NOTE, -1
        else:
            token = int(np.clip(pitch - previous, -MAX_LEAP, MAX_LEAP)) + MAX_LEAP
            length_class = int(np.argmin([abs(d - length) for d in DURATIONS]))
            previous, last_note, until = pitch, i, i + length
        rows.append((x, token, length_class))
        history = history[1:] + [token]
    return rows


def train(x, y, yl, hidden=96, epochs=15, batch=256, lr=1e-3, wd=1e-4, seed=0, log=print):
    rng = np.random.default_rng(seed)
    p = {
        "w1": rng.normal(0, np.sqrt(2 / N_FEATURES), (N_FEATURES, hidden)), "b1": np.zeros(hidden),
        "w_note": rng.normal(0, np.sqrt(1 / hidden), (hidden, N_CLASSES)), "b_note": np.zeros(N_CLASSES),
        "w_len": rng.normal(0, np.sqrt(1 / hidden), (hidden, len(DURATIONS))), "b_len": np.zeros(len(DURATIONS)),
    }
    m = {k: np.zeros_like(v) for k, v in p.items()}
    v = {k: np.zeros_like(v) for k, v in p.items()}
    step = 0
    for epoch in range(epochs):
        order = rng.permutation(len(x))
        for i in range(0, len(order), batch):
            idx = order[i : i + batch]
            n = len(idx)
            h, note, length = forward(p, x[idx])
            dn = np.exp(note - note.max(axis=1, keepdims=True))
            dn /= dn.sum(axis=1, keepdims=True)
            dn[np.arange(n), y[idx]] -= 1
            dl = np.exp(length - length.max(axis=1, keepdims=True))
            dl /= dl.sum(axis=1, keepdims=True)
            has = yl[idx] >= 0
            dl[np.arange(n)[has], yl[idx][has]] -= 1
            dl[~has] = 0
            dn /= n
            dl /= n
            dh = (dn @ p["w_note"].T + dl @ p["w_len"].T) * (h > 0)
            g = {"w_note": h.T @ dn, "b_note": dn.sum(0), "w_len": h.T @ dl, "b_len": dl.sum(0),
                 "w1": x[idx].T @ dh, "b1": dh.sum(0)}
            step += 1
            for k in p:
                gk = g[k] + (wd * p[k] if k.startswith("w") else 0)
                m[k] = 0.9 * m[k] + 0.1 * gk
                v[k] = 0.999 * v[k] + 0.001 * gk**2
                p[k] -= lr * (m[k] / (1 - 0.9**step)) / (np.sqrt(v[k] / (1 - 0.999**step)) + 1e-8)
        if log and epoch % 5 == 4:
            log(f"  epoch {epoch + 1:3d}  held-in loss {loss(p, x, y):.3f}")
    return p


def loss(p, x, y):
    note = forward(p, x)[1]
    note = note - note.max(axis=1, keepdims=True)
    logp = note - np.log(np.exp(note).sum(axis=1, keepdims=True))
    return float(-logp[np.arange(len(y)), y].mean())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("folder", type=Path)
    ap.add_argument("--final", action="store_true")
    ap.add_argument("--hidden", type=int, default=96)
    ap.add_argument("--epochs", type=int, default=15)
    args = ap.parse_args()

    notes = zipfile.ZipFile(args.folder / "annotation.zip")
    rng = np.random.default_rng(0)
    xs, ys, yls, players = [], [], [], []
    for name in sorted(n for n in notes.namelist() if n.endswith("_solo.jams")):
        rows = examples(steps_of(json.loads(notes.read(name))), rng)
        xs += [r[0] for r in rows]
        ys += [r[1] for r in rows]
        yls += [r[2] for r in rows]
        players += [int(Path(name).name[:2])] * len(rows)
    x, y, yl, player = np.array(xs), np.array(ys), np.array(yls), np.array(players)
    rate = float((y != NO_NOTE).mean())
    print(f"{len(x)} sixteenths, {int((y != NO_NOTE).sum())} notes ({100 * rate:.0f}% of steps start a note)")

    if args.final:
        p = train(x, y, yl, args.hidden, args.epochs)
        p["note_rate"] = np.array(rate)
        out = Path(__file__).resolve().parents[1] / "src" / "elfjamalong" / "melody_model.npz"
        np.savez(out, **{k: v.astype(np.float32) for k, v in p.items()})
        print(f"wrote {out}")
        return 0

    test = player >= 4
    p = train(x[~test], y[~test], yl[~test], args.hidden, args.epochs)
    # Baselines on the unseen players: how often a note starts at each bar position, and which interval overall.
    pos = x[:, :16].argmax(axis=1)
    table = np.ones((16, N_CLASSES))
    for a, b in zip(pos[~test], y[~test]):
        table[a, b] += 1
    table /= table.sum(axis=1, keepdims=True)
    baseline = float(-np.log(table[pos[test], y[test]]).mean())
    print(f"unseen players 04-05: loss per sixteenth {loss(p, x[test], y[test]):.3f} "
          f"(bar position alone: {baseline:.3f}; seen players: {loss(p, x[~test], y[~test]):.3f})")
    pred = forward(p, x[test])[1].argmax(axis=1)
    on = y[test] != NO_NOTE
    print(f"  right about whether a note starts: {100 * ((pred != NO_NOTE) == on).mean():.1f}%   "
          f"right interval when one does: {100 * (pred[on] == y[test][on]).mean():.1f}%")
    return 0


if __name__ == "__main__":
    sys.exit(main())
