"""Train the chord classifier on GuitarSet comping excerpts (CC BY 4.0, Xi et al. 2018).

    uv run python tools/train_chords.py data/guitarset [--final]

A small network scores "is this a major / minor chord on C?" and is applied to all
12 transpositions of the features, so every root shares the same weights. Without
--final it trains on players 00-03 and reports accuracy on players 04-05, whom it
has never heard. If audio_mono-pickup_mix.zip is in the folder too, the pickup
recordings of the same takes are used as well (a guitar plugged into an interface
sounds like those, not like a microphone). --hold-progression N also keeps one of each style's three chord
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
from multiprocessing import Pool
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from bench_guitarset import lead_sheet, reduce  # noqa: E402

from elfjamalong.features import N_FEATURES, SMOOTH_S, ChromaBands, rotate  # noqa: E402

HOP = 2048


SOURCES = (("audio_mono-mic.zip", "_mic.wav"), ("audio_mono-pickup_mix.zip", "_mix.wav"))


def extract_file(job):
    folder, name, zip_name, suffix, seed = job
    notes = zipfile.ZipFile(folder / "annotation.zip")
    audio = zipfile.ZipFile(folder / zip_name)
    wavs = {Path(n).name: n for n in audio.namelist() if n.endswith(".wav")}
    stem = Path(name).stem
    sheet = lead_sheet(json.loads(notes.read(name)))
    with wave.open(io.BytesIO(audio.read(wavs[stem + suffix]))) as w:
        sr = w.getframerate()
        pcm = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(np.float32) / 32768
    rng = np.random.default_rng(seed)
    bands = ChromaBands(sr)
    alpha = 1 - np.exp(-(HOP / sr) / SMOOTH_S)
    smooth = np.zeros(N_FEATURES)
    smooth_m = np.zeros(N_FEATURES)  # the same audio with a pretend lead note hidden
    keep = None
    xs, xms, ys, sinces, sevenths = [], [], [], [], []
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
        sinces.append(t - seg[0])
        sevenths.append(seg[2].split(":")[-1].split("/")[0] == "7")
    return stem, xs, xms, ys, sinces, sevenths


def extract(folder: Path, cache: Path):
    """Features for every comping excerpt, from the microphone and (if present) the pickup recordings."""
    if cache.exists():
        d = np.load(cache)
        return tuple(d[k] for k in ("x", "xm", "y", "player", "since", "progression", "source", "seventh"))
    notes = zipfile.ZipFile(folder / "annotation.zip")
    names = sorted(n for n in notes.namelist() if n.endswith("_comp.jams"))
    jobs = [(folder, name, zip_name, suffix, i)
            for zip_name, suffix in SOURCES if (folder / zip_name).exists()
            for i, name in enumerate(names)]
    with Pool() as pool:
        results = pool.map(extract_file, jobs)
    xs, xms, ys, players, sinces, progressions, sources, sevenths = [], [], [], [], [], [], [], []
    for job, (stem, fx, fxm, fy, fsince, fseventh) in zip(jobs, results):
        sevenths += fseventh
        xs += fx
        xms += fxm
        ys += fy
        sinces += fsince
        players += [int(stem[:2])] * len(fy)
        progressions += [stem.split("_")[1].split("-")[0]] * len(fy)  # e.g. 'Rock2'
        sources += [job[3][1:4]] * len(fy)  # 'mic' or 'mix'
    out = dict(x=np.array(xs, dtype=np.float32), xm=np.array(xms, dtype=np.float32), y=np.array(ys),
               player=np.array(players), since=np.array(sinces, dtype=np.float32),
               progression=np.array(progressions), source=np.array(sources), seventh=np.array(sevenths))
    np.savez_compressed(cache, **out)
    return tuple(out[k] for k in ("x", "xm", "y", "player", "since", "progression", "source", "seventh"))


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
    xr_all = ((all_rotations(x) - mean) / std).astype(np.float32)  # (N, 12, 36)
    p = {
        "w1": rng.normal(0, np.sqrt(2 / N_FEATURES), (N_FEATURES, hidden)),
        "b1": np.zeros(hidden),
        "w2": rng.normal(0, np.sqrt(1 / hidden), (hidden, 2)),
        "b2": np.zeros(2),
    }
    m = {k: np.zeros_like(v) for k, v in p.items()}
    v = {k: np.zeros_like(v) for k, v in p.items()}
    step = 0
    roots = np.arange(12)
    for epoch in range(epochs):
        order = rng.permutation(len(x))
        total = 0.0
        for i in range(0, len(order), batch):
            idx = order[i : i + batch]
            # Random transposition: every key is as common as every other. Transposing
            # the input up by `shift` only reorders its 12 rotations.
            shift = rng.integers(0, 12, len(idx))
            xr = xr_all[idx[:, None], (roots[None, :] - shift[:, None]) % 12]
            yb = (y[idx] % 12 + shift) % 12 + 12 * (y[idx] // 12)
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
        if log and (epoch % 5 == 4 or epoch == epochs - 1):
            log(f"  epoch {epoch + 1:3d}  loss {total / len(x):.3f}")
    p["mean"], p["std"] = np.array(mean), np.array(std)
    return p


def _train_member(job):
    x, y, hidden, epochs, seed = job
    return train(x, y, hidden, epochs, seed=seed, log=print if seed == 0 else None)


def train_ensemble(x, y, hidden, epochs, members):
    """Several networks from different starting points; the detector averages them."""
    with Pool(members) as pool:
        ps = pool.map(_train_member, [(x, y, hidden, epochs, seed) for seed in range(members)])
    out = {k: np.stack([p[k] for p in ps]) for k in ("w1", "b1", "w2", "b2")}
    out["mean"], out["std"] = ps[0]["mean"], ps[0]["std"]
    return out


def seventh_inputs(x, y, mean, std):
    """Features of major-chord frames, transposed so the chord's root sits on C."""
    major = y < 12
    rows = np.stack([rotate(f, -int(r)) for f, r in zip(x[major], y[major])]) if major.any() else np.zeros((0, N_FEATURES))
    return (rows - mean) / std, major


def train_seventh(x, y, seventh, mean, std, hidden=16, epochs=12, batch=512, lr=2e-3, seed=0):
    """A second small network: is this major chord a dominant seventh? (About one major frame in eight is.)"""
    rng = np.random.default_rng(seed)
    xs, major = seventh_inputs(x, y, mean, std)
    t = seventh[major].astype(float)
    weight = np.where(t == 1, (1 - t.mean()) / max(t.mean(), 1e-6), 1.0)  # both answers count equally
    p = {"s_w1": rng.normal(0, np.sqrt(2 / N_FEATURES), (N_FEATURES, hidden)), "s_b1": np.zeros(hidden),
         "s_w2": rng.normal(0, np.sqrt(1 / hidden), hidden), "s_b2": np.zeros(())}
    m = {k: np.zeros_like(v) for k, v in p.items()}
    v = {k: np.zeros_like(v) for k, v in p.items()}
    step = 0
    for _ in range(epochs):
        order = rng.permutation(len(xs))
        for i in range(0, len(order), batch):
            idx = order[i : i + batch]
            h = np.maximum(0, xs[idx] @ p["s_w1"] + p["s_b1"])
            d = (1 / (1 + np.exp(-(h @ p["s_w2"] + p["s_b2"]))) - t[idx]) * weight[idx] / weight[idx].sum()
            dh = np.outer(d, p["s_w2"]) * (h > 0)
            g = {"s_w2": h.T @ d, "s_b2": d.sum(), "s_w1": xs[idx].T @ dh, "s_b1": dh.sum(0)}
            step += 1
            for k in p:
                m[k] = 0.9 * m[k] + 0.1 * g[k]
                v[k] = 0.999 * v[k] + 0.001 * g[k] ** 2
                p[k] -= lr * (m[k] / (1 - 0.9**step)) / (np.sqrt(v[k] / (1 - 0.999**step)) + 1e-8)
    return p


def report_seventh(label, p, x, y, seventh):
    xs, major = seventh_inputs(x, y, p["mean"], p["std"])
    said = (np.maximum(0, xs @ p["s_w1"] + p["s_b1"]) @ p["s_w2"] + p["s_b2"]) > 0
    t = seventh[major]
    print(f"{label:28s} sevenths recognised {100 * said[t].mean():5.1f}%   plain majors left alone {100 * (~said[~t]).mean():5.1f}%"
          f"   ({int(t.sum())} seventh frames, {int((~t).sum())} major)")


def log_probabilities(p, x, chunk=20000):
    stacked = p["w1"].ndim == 3
    total = 0
    for i in range(len(p["w1"]) if stacked else 1):
        member = {k: (p[k][i] if stacked else p[k]) for k in ("w1", "b1", "w2", "b2")}
        parts = []
        for j in range(0, len(x), chunk):
            logits = forward(member, (all_rotations(x[j : j + chunk]) - p["mean"]) / p["std"])[1]
            logits -= logits.max(axis=1, keepdims=True)
            parts.append(logits - np.log(np.exp(logits).sum(axis=1, keepdims=True)))
        total = total + np.concatenate(parts)
    return total


def predict(p, x):
    return log_probabilities(p, x).argmax(axis=1)


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
    ap.add_argument("--members", type=int, default=5, help="networks averaged in the model (default 5)")
    ap.add_argument("--hold-progression", type=int, choices=[1, 2, 3],
                    help="also keep this progression number of every style out of training, and test only on it")
    args = ap.parse_args()
    x, xm, y, player, since, progression, source, seventh = extract(args.folder, args.folder / "features_v5.npz")
    print(f"{len(x)} frames ({len(x) * HOP / 44100 / 60:.0f} min), players {sorted(set(player.tolist()))}, "
          f"recordings {sorted(set(source.tolist()))}")

    if args.final:
        p = train_ensemble(np.concatenate([x, xm]), np.concatenate([y, y]), args.hidden, args.epochs, args.members)
        p.update(train_seventh(x, y, seventh, p["mean"], p["std"]))
        out = Path(__file__).resolve().parents[1] / "src" / "elfjamalong" / "chord_model.npz"
        np.savez(out, **p)
        print(f"wrote {out}")
        return 0

    test = player >= 4
    if args.hold_progression:
        # GuitarSet has 15 progressions (3 per style) that every player plays. A model
        # can learn them; this split scores chords in an order it has never met.
        held = np.char.endswith(progression, str(args.hold_progression))
        keep = test & held | ~test & ~held
        x, xm, y, player, since, source, seventh, test = (a[keep] for a in (x, xm, y, player, since, source, seventh, test))
        print(f"holding out progression {args.hold_progression}: {int((~test).sum())} training frames, {int(test.sum())} test frames")
    mic = source == "mic"

    # Baseline on the same frames: harmonic triad templates on the summed registers.
    from elfjamalong.chords import _chord_templates

    _, templates = _chord_templates()
    summed = x[test & mic].reshape(-1, 3, 12).sum(axis=1)
    c = summed - summed.mean(axis=1, keepdims=True)
    t = templates - templates.mean(axis=1, keepdims=True)
    scores = (c @ t.T) / (np.linalg.norm(c, axis=1, keepdims=True) * np.linalg.norm(t, axis=1) + 1e-12)
    report("templates (players 04-05)", scores.argmax(axis=1), y[test & mic], since[test & mic])

    p = train_ensemble(np.concatenate([x[~test], xm[~test]]), np.concatenate([y[~test], y[~test]]),
                       args.hidden, args.epochs, args.members)
    p.update(train_seventh(x[~test], y[~test], seventh[~test], p["mean"], p["std"]))
    suffix = f"_p{args.hold_progression}" if args.hold_progression else ""
    np.savez(args.folder / f"model_holdout{suffix}.npz", **p)  # for an honest live benchmark on players 04-05
    report("learned, seen players 00-03", predict(p, x[~test & mic]), y[~test & mic], since[~test & mic])
    report("learned, new players 04-05", predict(p, x[test & mic]), y[test & mic], since[test & mic])
    report("  same, lead note hidden", predict(p, xm[test & mic]), y[test & mic], since[test & mic])
    report_seventh("seventh or plain major, new", p, x[test & mic], y[test & mic], seventh[test & mic])
    if (~mic).any():
        report("  new players, pickup audio", predict(p, x[test & ~mic]), y[test & ~mic], since[test & ~mic])
    return 0


if __name__ == "__main__":
    sys.exit(main())
