"""Chord-detection accuracy on real guitar: GuitarSet comping excerpts (CC BY 4.0).

    uv run python tools/bench_guitarset.py data/guitarset [--limit N] [--set key=value ...]

Reads the two zips in place. Scores every 0.1 s against the lead-sheet chords,
reduced to root + major/minor (sevenths count as their triad; other qualities are
skipped). Reports three numbers:

  root+quality   the detector's chord has the right root and major/minor
  root           right root only
  settled        root+quality, ignoring the first 0.5 s after each chord change
"""

from __future__ import annotations

import argparse
import io
import json
import sys
import wave
import zipfile
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

from elfjamalong.chords import ChordDetector
from elfjamalong.theory import Chord, parse_note

MAJ = {"maj", "7", "maj7", "maj6", "6", "9", "maj9", ""}
MIN = {"min", "min7", "min6", "min9", "minmaj7"}


def reduce(label: str) -> Chord | None:
    """'A:min7' -> Am, 'D:7' -> D, anything else (N, dim, sus, aug, hdim7) -> None."""
    if ":" not in label:
        return None
    root, quality = label.split(":", 1)
    quality = quality.split("/")[0].split("(")[0]
    try:
        pc = parse_note(root)
    except ValueError:
        return None
    if quality in MAJ:
        return Chord(pc, "maj")
    if quality in MIN:
        return Chord(pc, "min")
    return None


def lead_sheet(jam: dict) -> list[tuple[float, float, str]]:
    chords = [a for a in jam["annotations"] if a["namespace"] == "chord"]
    data = chords[0]["data"]  # the first chord annotation is the instructed lead sheet
    return [(d["time"], d["time"] + d["duration"], d["value"]) for d in data]


def run_detector(audio: np.ndarray, sr: int, settings: dict, grid: np.ndarray) -> list[Chord | None]:
    now = [0.0]
    det = ChordDetector(sr, clock=lambda: now[0], **settings)
    out, g, block = [], 0, 441
    for i in range(0, len(audio), block):
        det.feed(audio[i : i + block])
        now[0] += block / sr
        while g < len(grid) and grid[g] <= now[0]:
            out.append(det.chord)
            g += 1
    out.extend([det.chord] * (len(grid) - len(out)))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("folder", type=Path)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--set", nargs="*", default=[], help="detector settings, e.g. stable_frames=5")
    ap.add_argument("--confusions", type=int, default=12)
    ap.add_argument("--players", default="", help="only these player numbers, e.g. 4,5")
    ap.add_argument("--model", type=Path, help="use this model file instead of the shipped one")
    args = ap.parse_args()
    settings = {k: json.loads(v) for k, v in (s.split("=", 1) for s in args.set)}

    notes = zipfile.ZipFile(args.folder / "annotation.zip")
    audio_zip = zipfile.ZipFile(args.folder / "audio_mono-mic.zip")
    wavs = {Path(n).name: n for n in audio_zip.namelist() if n.endswith(".wav")}
    jams = sorted(n for n in notes.namelist() if n.endswith("_comp.jams"))
    if args.players:
        keep = {int(p) for p in args.players.split(",")}
        jams = [n for n in jams if int(Path(n).name[:2]) in keep]
    if args.model:
        import elfjamalong.chords as chords_module

        chords_module.MODEL_PATH = args.model
        chords_module.ChordModel.__init__.__defaults__ = (args.model,)
    if args.limit:
        jams = jams[:: max(1, len(jams) // args.limit)][: args.limit]

    totals = Counter()
    by_style: dict[str, Counter] = defaultdict(Counter)
    confusion = Counter()
    for name in jams:
        stem = Path(name).stem
        wav_name = wavs.get(stem + "_mic.wav")
        if wav_name is None:
            continue
        sheet = lead_sheet(json.loads(notes.read(name)))
        with wave.open(io.BytesIO(audio_zip.read(wav_name))) as w:
            sr = w.getframerate()
            pcm = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(np.float32) / 32768
            if w.getnchannels() > 1:
                pcm = pcm.reshape(-1, w.getnchannels()).mean(axis=1)
        grid = np.arange(0.05, len(pcm) / sr, 0.1)
        heard = run_detector(pcm, sr, settings, grid)
        style = stem.split("_")[1].split("-")[0].rstrip("0123456789")  # BN, Funk, Jazz, Rock, SS
        for t, got in zip(grid, heard):
            seg = next((s for s in sheet if s[0] <= t < s[1]), None)
            want = reduce(seg[2]) if seg else None
            if want is None:
                continue
            c = by_style[style]
            for counter in (totals, c):
                counter["frames"] += 1
                counter["full"] += got == want
                counter["root"] += got is not None and got.root == want.root
                if t - seg[0] >= 0.5:
                    counter["settled_frames"] += 1
                    counter["settled"] += got == want
            if got != want and t - seg[0] >= 0.5:
                confusion[(str(want), str(got))] += 1

    def line(label: str, c: Counter) -> str:
        return (f"{label:8s} root+quality {100 * c['full'] / c['frames']:5.1f}%   root {100 * c['root'] / c['frames']:5.1f}%"
                f"   settled {100 * c['settled'] / max(1, c['settled_frames']):5.1f}%   ({c['frames'] / 10 / 60:.0f} min)")

    print(f"{len(jams)} excerpts, settings {settings or 'default'}")
    print(line("ALL", totals))
    for style in sorted(by_style):
        print(line(style, by_style[style]))
    if args.confusions:
        print("most common settled mistakes (wanted -> heard):")
        for (want, got), n in confusion.most_common(args.confusions):
            print(f"  {want:4s} -> {got:5s} {n / 10:6.1f} s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
