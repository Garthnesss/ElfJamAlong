# Prompt for a new working session

Paste everything below the line into a new session opened in `/Users/gerth/Projects/ElfJamAlong`.

---

You are continuing work on **ElfJamAlong**, in `/Users/gerth/Projects/ElfJamAlong` (GitHub: Garthnesss/ElfJamAlong, branch `main`). It listens to guitar chords and plays an in-key MIDI lead, bass and arpeggio into Ableton Live in real time. It is a Python terminal program (numpy only at run time) with one Swift helper.

## Read first, and only these
1. `STATUS.md` — what is verified, what is BUILT NOT TESTED, known problems.
2. `ROADMAP.md` — milestones; you are working on **M2 — Real guitar**.
3. `PROJECT_TRUTH.md` — the non-negotiables. Follow them.
4. `ARCHITECTURE.md` — read the section for the module you are about to change, not the whole file.

`docs/RESEARCH_2026-11.md` holds outside research. The planning is done; do not redo it or run new web research unless a task below needs one specific fact.

## Ground rules
- **Keep token use low.** Read only the files a task touches. Do not re-read a file you just edited. Do not paste large outputs; pipe through `tail` or `grep`. No subagents unless I ask.
- **Measure, do not guess.** Any detector change is judged with the benchmark on held-out players:
  `uv run python -I tools/train_chords.py data/guitarset` (trains on players 00–03, writes `data/guitarset/model_holdout.npz`), then
  `uv run python -I tools/bench_guitarset.py data/guitarset --players 4,5 --model data/guitarset/model_holdout.npz`
  Baseline to beat: **66–67% root+quality, 75–76% settled** overall; rock 80%, singer-songwriter 83%, jazz 58%, funk 43%.
- Only after a change wins on held-out players, retrain the shipped model with `--final`.
- **Tests must pass:** `uv run pytest -q` (38 tests today). Add a test for each behaviour you add.
- **Honest status.** After each task, update `STATUS.md`: move items between Verified, BUILT NOT TESTED and Known problems, and add a History line. Never call something verified that you have not run.
- **Ask before** downloading anything, pushing to GitHub, or adding a dependency. Selling versus personal use is undecided, so any new dependency or dataset must allow commercial use or be flagged.
- Commit after each finished task with a clear message. Do not push unless I say so.
- You cannot click in Ableton's window. When a step needs me (arming a track, a setting in Live, playing guitar), stop and tell me exactly what to click, then carry on with the next task that does not need me.

## Tasks, in order

### A. Major versus minor on the same root (no help from me needed)
The most common real-guitar mistake is the right root with the wrong quality (Fm heard as F). Ideas, cheapest first: give the classifier finer pitch resolution around the third (narrower Gaussian than σ = 0.35 semitone in `features.py`, or a 24-bin-per-octave variant); add a longer-smoothed copy of the features as extra inputs; weight minor chords in training (the data is about 3:1 major). Change one thing at a time and record each result in a short table in `STATUS.md`.
**Done when** held-out root+quality improves by at least 3 points with no style getting worse by more than 1.

### B. Faster reaction (no help needed)
Reaction is about 0.3 s. Add a short analysis window (about 2048 samples) to detect strum onsets, and let a new chord be accepted sooner right after an onset while keeping the long window for pitch. Measure with the fixture test `test_recorded_virtual_guitar_loop_has_no_wrong_chords` (its latencies) and the held-out benchmark.
**Done when** mean latency on the fixture is under 0.2 s with still no wrong chords, and held-out accuracy does not drop.

### C. Seventh, sus and power chords (no help needed)
Today everything is reduced to major/minor. Extend the label set (maj, min, 7, maj7, min7, sus4, 5) where GuitarSet has enough examples (check counts first: it is mostly maj, min, 7 and hdim7), keep reporting root + major/minor accuracy for comparison, and make `scale_for` in `theory.py` use the richer chord (a dominant 7 adds its ♭7 to the allowed notes).
**Done when** the old metric is no worse and the new classes are reported separately.

### D. Link Audio input (needs me for one check)
Live here is 12.4.16, which has Link Audio. First ask me to look in Live (Settings → Link, and a track's output chooser) and tell you whether a single track can be sent over Link Audio. If yes: write a small C++ helper next to `tools/livetap/` that joins the Link session, receives that channel and writes mono float32 PCM to stdout (same contract as `livetap`), and add `--source link` in `cli.py`. The SDK is `LinkAudio.hpp` in https://github.com/Ableton/link (GPLv2+; note that in `PROJECT_TRUTH.md`).
**Done when** `elfjamalong run --source link` follows a guitar track in Live with the ElfJamAlong track audible, and no own-note handling is needed.

### E. Close out BUILT NOT TESTED (needs me)
Walk me through each item in that section of `STATUS.md`, one at a time: Link on, track armed (or Monitor set to In), own notes audible, arpeggio, `ElfJamAlong.command`, capture with Enter. After each, record what happened.

## Useful facts
- Run: `uv run elfjamalong run` (settings in `elfjamalong.toml`: listens to Live through the tap, lead + bass). Demo without audio: `uv run elfjamalong demo`.
- Tap helper: `tools/livetap/build.sh` builds `tools/livetap/livetap` (not in git).
- GuitarSet lives in `data/guitarset/` (not in git, about 700 MB). If it is missing, ask me before downloading; the links and checksums are in `README.md` and `tools/train_chords.py`.
- The AbletonMCP bridge answers on localhost:9877 when Live is open; `src/elfjamalong/capture.py` shows how to call it. It cannot arm tracks or change routing.
- In Live, the receiving track must be named `ElfJamAlong` for captures to land in it.

Start with task A. Tell me in two or three lines what you are about to try before you change code.
