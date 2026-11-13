# Prompt for a new working session

Paste everything below the line into a new session opened in `/Users/gerth/Projects/ElfJamAlong`.

---

You are continuing work on **ElfJamAlong**, in `/Users/gerth/Projects/ElfJamAlong` (GitHub: Garthnesss/ElfJamAlong, branch `main`). It listens to guitar chords and plays an in-key MIDI lead, bass and arpeggio into Ableton Live in real time. It is a Python terminal program (numpy only at run time) with one Swift helper.

## Read first, and only these
1. `STATUS.md` — what is verified, what is BUILT NOT TESTED, known problems.
2. `ROADMAP.md` — milestones; most of what can be built without Live is built, and the work now is hearing it.
3. `PROJECT_TRUTH.md` — the non-negotiables. Follow them.
4. `ARCHITECTURE.md` — read the section for the module you are about to change, not the whole file.

`docs/RESEARCH_2026-11.md` holds outside research. The planning is done; do not redo it or run new web research unless a task below needs one specific fact.

## Ground rules
- **Keep token use low.** Read only the files a task touches. Do not re-read a file you just edited. Do not paste large outputs; pipe through `tail` or `grep`. No subagents unless I ask.
- **Measure, do not guess.** Any detector change is judged with the benchmark on held-out players:
  `uv run python -I tools/train_chords.py data/guitarset` (trains on players 00–03, writes `data/guitarset/model_holdout.npz`), then
  `uv run python -I tools/bench_guitarset.py data/guitarset --players 4,5 --model data/guitarset/model_holdout.npz`
  Baseline to beat: **70.2% root+quality, 78.7% settled** overall; rock 83%, singer-songwriter 86%, bossa nova 68%, jazz 63%, funk 48%; median reaction 0.34 s; 1.95 reported changes per real change. Training takes about seven minutes (five networks) and uses `audio_mono-pickup_mix.zip` too if it is in the folder.
  GuitarSet's 15 progressions are shared by every player. For any change that gives the model more context, also run the stricter split: add `--hold-progression 3` to the training command (writes `model_holdout_p3.npz`) and `--progressions 3 --model data/guitarset/model_holdout_p3.npz` to the benchmark. Baseline there: 69.2% / 80.1% (progression 3).
- Only after a change wins on held-out players, retrain the shipped model with `--final`.
- **Tests must pass:** `uv run pytest -q` (62 tests today; build `tools/linktap/build.sh` first or one is skipped). Add a test for each behaviour you add.
- **Honest status.** After each task, update `STATUS.md`: move items between Verified, BUILT NOT TESTED and Known problems, and add a History line. Never call something verified that you have not run.
- **Ask before** downloading anything, pushing to GitHub, or adding a dependency. Selling versus personal use is undecided, so any new dependency or dataset must allow commercial use or be flagged.
- Commit after each finished task with a clear message. Do not push unless I say so.
- You cannot click in Ableton's window. When a step needs me (arming a track, a setting in Live, playing guitar), stop and tell me exactly what to click, then carry on with the next task that does not need me.

## Tasks, in order

Everything below needs me at the computer with Live open. `STATUS.md`, "BUILT NOT TESTED", is the full list; take the items in this order and record what happened after each.

### A. The basics, never yet heard
Link on, the ElfJamAlong track armed (or Monitor set to In) so its own notes are audible, arpeggio, `ElfJamAlong.command` by double-click, capture with Enter.

### B. Link Audio (`--source link`)
Run `tools/linktap/build.sh` (first time on macOS: fix the script if it fails). Ask me to turn on Link Audio in Live's settings and look for a way to send one track. Then `uv run elfjamalong devices` should list Live's channels, and `run --source link --link-channel <name>` should follow the guitar. If Live can only send the master, say so in `STATUS.md` and `ROADMAP.md`.

### C. Loop prediction, feel and the learned lead
`--predict` on a four-chord loop, then on a loop I break out of. `--feel answer` against the default. `--lead model` against the rules on the same progression: ask me which I prefer and why, and write that down; it is the only test of the model that counts. Then `elfjamalong calibrate`.

### D. If I am not there: minor chords
Right 48% of the time against 73% for major. `STATUS.md` ("What was tried on the classifier") lists what did not help; do not repeat it. The classifier needs more varied chord-labelled guitar audio; look for some whose licence allows commercial use and ask me before downloading.

## Useful facts
- Run: `uv run elfjamalong run` (settings in `elfjamalong.toml`: listens to Live through the tap, lead + bass). Demo without audio: `uv run elfjamalong demo`.
- Tap helper: `tools/livetap/build.sh` builds `tools/livetap/livetap` (not in git).
- GuitarSet lives in `data/guitarset/` (not in git, about 700 MB). If it is missing, ask me before downloading; the links and checksums are in `README.md` and `tools/train_chords.py`.
- The AbletonMCP bridge answers on localhost:9877 when Live is open; `src/elfjamalong/capture.py` shows how to call it. It cannot arm tracks or change routing.
- In Live, the receiving track must be named `ElfJamAlong` for captures to land in it.

Start with task A if I am at the computer with Live open, otherwise task D. Tell me in two or three lines what you are about to try before you change code.
