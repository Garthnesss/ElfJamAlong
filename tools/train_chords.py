"""Train the chord classifier on GuitarSet comping excerpts (CC BY 4.0, Xi et al. 2018).

    uv run python tools/train_chords.py data/guitarset [--final]

A small network scores "is this a major / minor chord on C?" and is applied to all
12 transpositions of the features, so every root shares the same weights. Without
--final it trains on players 00-03 and reports accuracy on players 04-05, whom it
has never heard. --hold-progression N also keeps one of each style's three chord
progressions out of training and tests on that one only (the stricter score). With --final it trains on everyone and writes
src/elfjamalong/chord_model.npz.
"""

from __future__ import annotations

import argparse
import io
import json
import sys
import wave
import zipfile
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from bench_guitarset import lead_sheet, reduce  # noqa: E402

from elfjamalong.features import N_FEATURES, SMOOTH_S, ChromaBands, rotate  # noqa: E402

HOP = 2048


def extract(folder: Path, cache: Path):
    if cache.exists():
        d = np.load(cache)
        return d["x"], d["xm"], d["y"], d["player"], d["since"], d["progression"]
    notes = zipfile.ZipFile(folder / "annotation.zip")
    audio = zipfile.ZipFile(folder / "audio_mono-mic.zip")
    wavs = {Path(n).name: n for n in audio.namelist() if n.endswith(".wav")}
    xs, xms, ys, players, sinces, progressions = [], [], [], [], [], []
    rng = np.random.default_rng(0)
    for name in sorted(n for n in notes.namelist() if n.endswith("_comp.jams")):
        stem = Path(name).stem
        sheet = lead_sheet(json.loads(notes.read(name)))
        with wave.open(io.BytesIO(audio.read(wavs[stem + "_mic.wav"]))) as w:
            sr = w.getframerate()
            pcm = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(np.float32) / 32768
        bands = ChromaBands(sr)
        alpha = 1 - np.exp(-(HOP / sr) / SMOOTH_S)
        smooth = np.zeros(N_FEATURES)
        smooth_m = np.zeros(N_FEATURES)  # the same audio with a pretend lead note hidden
        keep = None
        for k, end in enumerate(range(bands.n_fft, len(pcm), HOP)):
            frame = pcm[end - bands.n_fft : end]
            spec = bands.spectrum(frame)
            f = bands.features(spec)
            n = np.linalg.norm(f)
            if n > 0:
                smooth += alpha * (f / n - smooth)
            if k % 8 == 0:  # a new pretend melody note every ~0.37 s, sometimes two overlapping
                keep = bands.harmonic_mask(rng.integers(55, 88, size=rng.choice([1, 1, 2])))
            fm = bands.features(spec, keep)
            n = np.linalg.norm(fm)
            if n > 0:
                smooth_m += alpha * (fm / n - smooth_m)
            t = end / sr  # what a live detector knows at time t
            seg = next((s for s in sheet if s[0] <= t < s[1]), None)
            want = reduce(seg[2]) if seg else None
            if want is None or float(np.sqrt(np.mean(frame[-HOP:] ** 2))) < 1e-3:
                continue
            xs.append(smooth.copy())
            xms.append(smooth_m.copy())
            ys.append(want.root + (12 if want.quality == "min" else 0))
            players.append(int(stem[:2]))
            sinces.append(t - seg[0])
            progressions.append(stem.split("_")[1].split("-")[0])  # e.g. 'Rock2'
    x, xm, y = np.array(xs, dtype=np.float32), np.array(xms, dtype=np.float32), np.array(ys)
    player, since = np.array(players), np.array(sinces, dtype=np.float32)
    progression = np.array(progressions)
    np.savez_compressed(cache, x=x, xm=xm, y=y, player=player, since=since, progression=progression)
    return x, xm, y, player, since, progression


def all_rotations(x: np.ndarray) -> np.ndarray:
    """(N, 36) -> (N, 12, 36): row r is the features transposed so root r sits on C."""
    return np.stack([rotate(x, -r) for r in range(12)], axis=1)


def forward(p, xr):
    h = np.maximum(0, xr @ p["w1"] + p["b1"])  # (N, 12, H)
    out = h @ p["w2"] + p["b2"]  # (N, 12, 2): [major, minor] for each root
    return h, np.concatenate([out[:, :, 0], out[:, :, 1]], axis=1)  # logits (N, 24)


def train(x, y, hidden=64, epochs=40, batch=512, lr=2e-3, seed=0, log=print):
    rng = np.random.default_rng(seed)
    mean, std = x.mean(), x.std()
    p = {
        "w1": rng.normal(0, np.sqrt(2 / N_FEATURES), (N_FEATURES, hidden)),
        "b1": np.zeros(hidden),
        "w2": rng.normal(0, np.sqrt(1 / hidden), (hidden, 2)),
        "b2": np.zeros(2),
    }
    m = {k: np.zeros_like(v) for k, v in p.items()}
    v = {k: np.zeros_like(v) for k, v in p.items()}
    step = 0
    for epoch in range(epochs):
        order = rng.permutation(len(x))
        total = 0.0
        for i in range(0, len(order), batch):
            idx = order[i : i + batch]
            # Random transposition: every key is as common as every other.
            shift = rng.integers(0, 12, len(idx))
            xb = np.stack([rotate(x[j], s) for j, s in zip(idx, shift)])
            yb = (y[idx] % 12 + shift) % 12 + 12 * (y[idx] // 12)
            xr = (all_rotations(xb) - mean) / std
            h, logits = forward(p, xr)
            logits -= logits.max(axis=1, keepdims=True)
            prob = np.exp(logits)
            prob /= prob.sum(axis=1, keepdims=True)
            total += -np.log(prob[np.arange(len(idx)), yb] + 1e-12).sum()
            d = prob
            d[np.arange(len(idx)), yb] -= 1
            d /= len(idx)
            dout = np.stack([d[:, :12], d[:, 12:]], axis=2)  # (N, 12, 2)
            g = {"w2": np.einsum("nrh,nrk->hk", h, dout), "b2": dout.sum(axis=(0, 1))}
            dh = (dout @ p["w2"].T) * (h > 0)
            g["w1"] = np.einsum("nrf,nrh->fh", xr, dh)
            g["b1"] = dh.sum(axis=(0, 1))
            step += 1
            for k in p:
                m[k] = 0.9 * m[k] + 0.1 * g[k]
                v[k] = 0.999 * v[k] + 0.001 * g[k] ** 2
                p[k] -= lr * (m[k] / (1 - 0.9**step)) / (np.sqrt(v[k] / (1 - 0.999**step)) + 1e-8)
        if epoch % 5 == 4 or epoch == epochs - 1:
            log(f"  epoch {epoch + 1:3d}  loss {total / len(x):.3f}")
    p["mean"], p["std"] = np.array(mean), np.array(std)
    return p


def predict(p, x, chunk=20000):
    out = []
    for i in range(0, len(x), chunk):
        out.append(forward(p, (all_rotations(x[i : i + chunk]) - p["mean"]) / p["std"])[1].argmax(axis=1))
    return np.concatenate(out)


def report(label, pred, y, since):
    full = (pred == y).mean()
    root = (pred % 12 == y % 12).mean()
    settled = (pred == y)[since >= 0.5].mean()
    print(f"{label:28s} root+quality {100 * full:5.1f}%   root {100 * root:5.1f}%   settled {100 * settled:5.1f}%")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("folder", type=Path)
    ap.add_argument("--final", action="store_true")
    ap.add_argument("--hidden", type=int, default=32)
    ap.add_argument("--epochs", type=int, default=25)
    ap.add_argument("--hold-progression", type=int, choices=[1, 2, 3],
                    help="also keep this progression number of every style out of training, and test only on it")
    args = ap.parse_args()
    x, xm, y, player, since, progression = extract(args.folder, args.folder / "features_v3.npz")
    print(f"{len(x)} frames ({len(x) * HOP / 44100 / 60:.0f} min), players {sorted(set(player.tolist()))}")

    if args.final:
        p = train(np.concatenate([x, xm]), np.concatenate([y, y]), args.hidden, args.epochs)
        out = Path(__file__).resolve().parents[1] / "src" / "elfjamalong" / "chord_model.npz"
        np.savez(out, **p)
        print(f"wrote {out}")
        return 0

    test = player >= 4
    keep = np.ones(len(x), dtype=bool)
    if args.hold_progression:
        # GuitarSet has 15 progressions (3 per style) that every player plays. A model
        # can learn them; this split scores chords in an order it has never met.
        held = np.char.endswith(progression, str(args.hold_progression))
        keep = test & held | ~test & ~held
        x, xm, y, player, since, test = x[keep], xm[keep], y[keep], player[keep], since[keep], test[keep]
        print(f"holding out progression {args.hold_progression}: {int((~test).sum())} training frames, {int(test.sum())} test frames")
    # Baseline on the same frames: harmonic triad templates on the summed registers.
    from elfjamalong.chords import _chord_templates

    _, templates = _chord_templates()
    summed = x[test].reshape(-1, 3, 12).sum(axis=1)
    c = summed - summed.mean(axis=1, keepdims=True)
    t = templates - templates.mean(axis=1, keepdims=True)
    scores = (c @ t.T) / (np.linalg.norm(c, axis=1, keepdims=True) * np.linalg.norm(t, axis=1) + 1e-12)
    report("templates (players 04-05)", scores.argmax(axis=1), y[test], since[test])

    p = train(np.concatenate([x[~test], xm[~test]]), np.concatenate([y[~test], y[~test]]), args.hidden, args.epochs)
    suffix = f"_p{args.hold_progression}" if args.hold_progression else ""
    np.savez(args.folder / f"model_holdout{suffix}.npz", **p)  # for an honest live benchmark on players 04-05
    report("learned, seen players 00-03", predict(p, x[~test]), y[~test], since[~test])
    report("learned, new players 04-05", predict(p, x[test]), y[test], since[test])
    report("  same, lead note hidden", predict(p, xm[test]), y[test], since[test])
    return 0


if __name__ == "__main__":
    sys.exit(main())
