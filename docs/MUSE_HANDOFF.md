# Hand-off to Muse: hear ElfJamAlong in Live (no guitar needed)

Written 2026-11-13 by the cloud session that built the features below. It could run tests and benchmarks but had no Mac, no Live and no sound. You have all three. Garth has no guitar to hand, so use the virtual guitar track in Live as the player.

Repo: `~/Projects/ElfJamAlong` (GitHub `Garthnesss/ElfJamAlong`). Branch: **`claude/fervent-feynman-ij4rja`**. Work on that branch, commit after each task, push to it, and do not merge to `main` or open a pull request; Garth decides that.

## Before you start
1. `git fetch origin && git checkout claude/fervent-feynman-ij4rja && git pull`
2. `uv sync && uv run pytest -q` — expect 61 passed, 1 skipped (62 passed once `linktap` is built).
3. Read `STATUS.md`, section "BUILT NOT TESTED". That list is your work. `PROJECT_TRUTH.md` has the rules; rule 8 matters most here: nothing is verified until it has been run, and you write down exactly what happened, including failures.
4. Live set: a track named `ElfJamAlong` (MIDI From: the `ElfJamAlong` port, Monitor **In**, any instrument with a sharp attack), and a guitar stand-in: a MIDI clip of strummed chords on Live's "Guitar Acoustic", looping. The fixture `tests/fixtures/virtual-guitar-am-dm-g-c-f-dm-e-am.wav` was recorded from such a loop (Am Dm G C F Dm E Am, one bar each, 120 BPM). The AbletonMCP bridge on localhost:9877 can create clips and add notes; it cannot arm tracks or change routing. Where a step needs a click you cannot make, ask Garth for that one click and carry on with the next task.

## Running this with subagents

One lead agent owns the branch, `STATUS.md` and Live. Subagents do the pieces below and report back; they do not push, and they do not touch Live unless they are the one agent holding it.

**Only one agent may drive Live at a time.** There is one Live set, one `ElfJamAlong` MIDI port and one pid file, so two `elfjamalong run` processes or two agents editing clips will corrupt each other's results. Tasks 1, 2 (the Live half), 3, 4, 5 and 7 are a single queue, in that order, run by the lead or by one subagent at a time.

These need no Live and can run in parallel from the start, each in its own git worktree of the branch:

| Subagent | Does | Hands back |
|---|---|---|
| **Build** | Task 2, first half: get `tools/linktap/build.sh` working on macOS, pass the `link_audio` test against `--send-tone` | a patch to the build script, the test output |
| **Blind test** | Task 6, the rendering half: ten progressions, twenty MIDI files, the shuffled A/B key | the files and the key; the lead puts them into Live later |
| **Fixture test** | Task 7, the code half: write the test that loads a WAV plus its capture MIDI and checks the chords, using the existing fixture until the new recording exists | a patch; the lead swaps in the real recording |
| **Reviewer** | Read the diff of the last two commits on the branch (`git diff ac57a92..HEAD -- src tools`) for bugs, with fresh eyes. The code was written without ever running against Live or CoreMIDI | a list of findings with file and line, most serious first; no edits |

The lead merges patches in the order they arrive, runs `uv run pytest -q` after each, and only then starts the Live queue. Every subagent's report must separate what it ran and saw from what it expects.

## Tasks, in order

### 1. The basics that have never been heard
Run `uv run elfjamalong run --preset trio --split-channels` with the tap (`source = "live"` is the saved default; `tools/livetap/build.sh` first if the helper is missing), **Link on in Live**, and the ElfJamAlong track audible, so its own notes are in what it hears.
- Does it follow the loop? Note every wrong chord and how long it lasts.
- Stop the guitar clip: do the voices stop within `--tail` seconds, or do they keep themselves going?
- Are note starts on Live's grid (record the ElfJamAlong track for 8 bars and look at the note positions)?
- Capture: `uv run elfjamalong capture` from a second terminal. Did the file and the Live clip appear?
- `ElfJamAlong.command` by double-click, if you can; otherwise leave it listed as untested.

### 2. Link Audio
`tools/linktap/build.sh` has only run on Linux. Build it on the Mac and fix the script if it fails (keep the Linux branch working). Then `tools/linktap/linktap --send-tone` in one terminal and `uv run pytest -q -k link_audio` in another should pass.
Turn on Link Audio in Live (Settings, Link/Link Audio page). Find out **whether Live can send one track on its own channel** or only the main mix; this is the open question in `ROADMAP.md` M2. `uv run elfjamalong devices` lists what Live offers. If the guitar track can be sent: `uv run elfjamalong run --source link --link-channel <part of its name>` and repeat the checks of task 1. Record the answer either way in `STATUS.md`, `ROADMAP.md` and `docs/RESEARCH_2026-11.md`.

### 3. Loop prediction
Same loop, `--predict` added. The terminal shows `loop 8 bars` once the progression has gone round twice. Record the ElfJamAlong track for 8 bars before that point and 8 bars after it, and compare the first bass note of each bar with that bar's chord: without prediction it should often be the previous bar's root, with prediction the new one. Then change one chord in the guitar clip while it plays: how long until it follows what it hears? Does the loop come back after two rounds?
If it holds up, set `predict = true` in `elfjamalong.toml`.

### 4. Feel
`--feel follow` is the default: raise and lower the guitar clip's velocities (or the track's volume) and check the lead and bass velocities move with it. With the tap, the level includes ElfJamAlong's own instruments; say whether that makes it chase itself. Then `--feel answer` on a clip that strums on beats 1 and 2 and rests on 3 and 4: does the lead move into the rests?

### 5. Calibrate
`uv run elfjamalong calibrate --source live`. Report the number, run it three times to see how steady it is, and try the suggested `--offset-ms`.

### 6. The learned lead: prepare a blind test for Garth
Nobody has listened to `--lead model`. Render both leads over the same progressions:
`uv run elfjamalong render --chords "<progression>" --bars 8 --seed <n> --lead rules -o rules_<k>.mid` and the same with `--lead model`.
Use ten progressions in different keys and feels. Put each pair into Live as clips named only `A` and `B` (coin-flip which is which, keep the key in a file Garth does not need to open), on a track with the same instrument, each over a chord track. Tell Garth the set is ready; his preference per pair goes into `STATUS.md`. This is ROADMAP M4's "done when".

### 7. New fixtures
Record 16 bars of the tap's audio with the trio audible (own notes in the signal) as a WAV under `tests/fixtures/`, and add a test like `test_recorded_virtual_guitar_loop_has_no_wrong_chords` for it, telling the detector which notes were its own (the capture MIDI has them). This turns "own-note handling with the notes audible" from simulation into a test.

### 8. Write it down
After each task: move the item in `STATUS.md` from BUILT NOT TESTED to Verified (with how) or to Known problems (with what happened), add a History line, commit, push. If you fix code, the detector benchmark must not get worse: see `docs/SESSION_PROMPT.md` for the commands (GuitarSet is about 1.4 GB with the pickup recordings; ask Garth before downloading it).

## Not for this hand-off
- Anything needing a real guitar or Garth's ears beyond task 6.
- The plugin (ROADMAP M6), new training data, merging to `main`.
- `--source midi` needs a MIDI keyboard or a MIDI track routed to an IAC port; do it only if that is quick.
