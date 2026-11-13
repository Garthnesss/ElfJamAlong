# ElfJamAlong — Status

_Last updated: 2026-11-13_

## Where it stands
A working terminal prototype. It follows chords played in Ableton Live and plays a lead and bass back through a virtual MIDI port. It has been heard working with a virtual guitar; it has **not** been played with a real guitar in the room.

## Verified
Heard or measured, not just built.

| What | How it was verified |
|---|---|
| MIDI reaches Live and plays an instrument | Garth heard the demo and the lead on the electric piano track (2026-11-09) |
| Note timing | Note-ons within 3 ms of the sixteenth-note grid, measured on the virtual port |
| Driverless tap of Live's output | Captured Live at a healthy level; chords read correctly from it |
| Follows a virtual guitar in Live | 8-bar strummed loop (Am Dm G C F Dm E Am), lead + bass on: one misread in three passes |
| Capture | 8 bars → MIDI file and a new clip on the Live track |
| Chord accuracy on real guitar | GuitarSet, players the model did not train on, scored live-style every 0.1 s (below) |
| Reaction on the recorded Live loop | Mean 0.27 s, worst 0.33 s, no wrong chords (before 2026-11-12: 0.29 s, worst 0.51 s) |
| Link Audio reception | `linktap` received its own test sender's 440 Hz channel on one machine (Linux): found by name, right sample rate, two seconds with no gaps. Not yet against Live |
| Learned lead predicts unseen players | Loss per sixteenth 1.08 on players 04–05 against 1.41 for bar position alone (trained on 00–03). Says nothing about how it sounds |
| Unit tests | 62 passing |

### Chord accuracy (GuitarSet players 04–05, model trained on 00–03)

Scored live-style every 0.1 s, all with the same script. 11-10: the detector as first trained. 11-12: belief filter. 11-13: five networks averaged, pickup recordings added to training, chords of the key favoured.

| | 11-10 | 11-12 | 11-13 | Templates |
|---|---|---|---|---|
| All styles, root + major/minor | 65.9% | 68.5% | **70.2%** | 38% |
| All styles, 0.5 s after a change | 75.1% | 77.4% | **78.7%** | 45% |
| Rock | 79.6% | 81.4% | 82.5% | |
| Singer-songwriter | 82.7% | 84.1% | 85.7% | |
| Bossa nova | 63.4% | 67.6% | 67.6% | |
| Jazz | 57.0% | 58.8% | 62.5% | |
| Funk | 41.6% | 45.3% | 48.0% | |
| Median time to the right chord after a change | 0.38 s | 0.36 s | 0.34 s | |
| Reported changes per real change (1.0 is ideal) | 2.15 | 2.00 | 1.95 | |
| Same takes through the pickup (closer to a guitar plugged into an interface) | | 68.5% | **71.1%** | |

Half a second after a change, rock is 91% and singer-songwriter 95%.

**Dominant sevenths.** When the chord itself is right, a seventh is shown as one 25% of the time and a plain major chord is wrongly shown as a seventh 2% of the time. The threshold is set cautiously on purpose, because a false seventh changes the scale. It cannot affect the figures above.

**These figures are optimistic for music the model has not met.** GuitarSet has 15 chord progressions (three per style) and every player plays all of them, so holding out players still tests on familiar progressions. With one progression of each style also held out:

| Players 04–05, unseen progression | 11-10 | 11-12 | 11-13 |
|---|---|---|---|
| Progression 2: all / settled | 53.6% / 61.0% | 54.5% / 61.3% | not re-run on the real pipeline; about +2 / +2 in simulation |
| Progression 3: all / settled | 64.3% / 76.4% | 66.8% / 78.1% | 69.2% / 80.1% |

`tools/train_chords.py --hold-progression N` and `tools/bench_guitarset.py --progressions N` run this split. Use it for any change that gives the model more context.

The shipped model is trained on all six players, so it has no held-out score of its own.

### What was tried on the classifier (2026-11-12)

Frame-level accuracy on players 04–05 unless stated. Run-to-run noise is about ±0.4.

| Change | Result | Kept |
|---|---|---|
| Baseline (as shipped 2026-11-10) | 66.8 | |
| Narrower pitch resolution (σ 0.25, 0.18 semitone) | 67.5, 66.8 | no |
| 4, 5 or 6 registers instead of 3 | 67.3, 66.8, 65.4 | no |
| Minor chords weighted ×2, ×3 | 66.1, 64.9 | no |
| Larger or deeper network | 65.9–67.1 | no |
| Random tone, level and tuning changes while training | 67.3 | no |
| Extra inputs smoothed over 0.5–2 s | 71–73 on seen progressions, **3–7 points worse on unseen ones** | no: it learns GuitarSet's progressions |
| 57 minutes of synthesized chords added | +2.7, +1.4, −1.1 on the three unseen-progression splits | no: not consistent |
| Five models averaged | +0.4 to +1.4 on four splits | **yes** (11-13) |
| Chords of the key favoured in the belief filter (×4) | +0.6 to +1.3 on four splits, never worse | **yes** (11-13) |
| Pickup recordings as extra training audio | no clear change on microphone audio (−2 to +1); about +3 on pickup audio | **yes** (11-13), for plugged-in guitars |
| Belief filter + 0.07 s smoothing (decision logic) | +2.6 live, also better on unseen progressions | **yes** |

Where the errors are (baseline, per frame): 67% right; 4% right root with the wrong quality; 3% still the previous chord; 5% the relative major or minor (Am heard as C, C as Em). Chords labelled minor are right 48% of the time, major 73%.

## BUILT NOT TESTED
- **Everything changed on 2026-11-12 and 11-13 has only been run on recordings and in tests, on Linux, without Live:** the belief filter and retrained model, `--predict`, cutting held notes on a chord change, `render --roles`, and everything in the next six items.
- **`--source link` (Link Audio).** Works against its own test sender. Not tried against Live, and whether Live can send one track on its own channel is still unknown. `tools/linktap/build.sh` has only been run on Linux; the macOS branch of the script is untested.
- **`--lead model` (learned lead).** Keeps the contract (in key, in range, monophonic) in tests. Nobody has listened to it. On paper it plays about as many notes as the solos it learned from, lands on chord tones on the beat 55% of the time (the solos: 51%; the rules: 93%), and sits in the lower half of the range.
- **`--feel follow` (now the default) and `--feel answer`.** Tested on synthetic contexts and synthesized strums. With the tap, the level it follows includes whatever else Live is playing.
- **`elfjamalong calibrate`.** The measuring is tested on made-up levels; the command has never sent a note to a real instrument.
- **`--source midi`.** Chord spelling is tested; no MIDI port has been opened.
- **Seventh chords** in a real jam (measured on GuitarSet only).
- **`--predict` (loop prediction).** Passes on synthesized strums end to end. Never tried on a real player, whose changes are less regular. Off by default.
- **Own-note handling with the notes audible.** In every live run the receiving track was un-armed, so nothing ElfJamAlong played was in the signal. Covered only by a simulation with synthesized notes.
- **Arpeggio role** in Live, and `--split-channels`.
- **`ElfJamAlong.command`** by double-click, and capture by pressing Enter (capture was triggered with `elfjamalong capture`).
- **Audio interface input** with a real guitar. The device path has only opened the MacBook microphone.
- **Link sync.** Link was off in Live for every run, so the bar alignment has never been heard.
- **Logic Pro.** Not tried at all.
- **After the rename (2026-11-10):** tests pass, but nothing has been run against Live under the new port name `ElfJamAlong`. The Live track must also be named `ElfJamAlong` for captures to land in it.

## Known problems
- **Minor chords** are the weak spot on real guitar: heard as the major on the same root (Fm as F) or as the relative major (F♯m as A).
- **Sevenths are mostly missed** (one in four shown), by choice of a cautious threshold.
- **The learned lead tends to repeat notes** when left to itself (40% of moves against 18% in the solos); a fixed damping factor corrects it. A sign the model is small for the job.
- **The benchmark flatters the model** on progressions it has met (see above).
- **Funk and jazz** are weak: muted strums, sparse voicings and seventh chords.
- **Reaction time** is about 0.27 s on the virtual guitar loop. A new chord's first two sixteenths at 120 BPM are still played over the old chord, unless `--predict` is on and the progression has repeated.
- **Early key estimates wander** for the first few bars.
- **Real excerpt through Live** (C–G–Am–Em–F–C–F–G) was mostly followed but reported chords that were not there (D, A). That player is in the training data, so this is a demonstration, not a test.
- **Creating a MIDI track in Live un-arms the ElfJamAlong track**, and the AbletonMCP bridge cannot re-arm it. Setting the track's Monitor to In avoids the problem.
- **macOS only**, and the tap needs 14.4+.

## Open decisions
1. **Sell, or personal use?** Decides whether Ableton Link can stay and how careful to be with training data. (Garth, 2026-11-09: "most likely sell", then "what if i just want it for personal".)
2. **Plugin form.** Max for Live device first, or straight to AU/VST3?
3. **What music trains the melody model.** Needs MIDI the owner has the right to use.
4. **Licence for the public GitHub repo.** None chosen yet.

## History
- **2026-11-09** — Research; first prototype (chord templates, rule-based lead, Link, virtual MIDI port). Demo heard in Live. Driverless Live tap. Own-note cancellation. Virtual guitar track.
- **2026-11-09** — Bass and arpeggio roles, capture to file and Live clip, saved settings, launcher. Cancellation reworked after it hurt detection with the bass on.
- **2026-11-11** — Research pass on May–November 2026 (docs/RESEARCH_2026-11.md): Link Audio in Live 12.4 may replace the tap; roadmap updated; session prompt written (docs/SESSION_PROMPT.md).
- **2026-11-13** — Detector: five networks averaged, pickup recordings in training, key-aware belief (68.5% → 70.2% on unseen players; 71.1% on pickup audio), dominant-seventh flag. Playing: energy following, answer mode, lead approaches the next chord, presets. Learned lead from GuitarSet solos (`--lead model`). New inputs: Link Audio (`--source link`, C++ helper) and MIDI keyboard (`--source midi`). `calibrate` command. Not done: the plugin (M6), anything needing Live or a guitar.
- **2026-11-12** — Code review and fixes (held notes cut on a chord change, all-notes-off on every channel, chord names like G7 accepted, unknown settings reported, `render --roles`). Classifier experiments: no feature or size change helped; found the benchmark shares progressions between train and test. Belief filter in the detector: 65.9% → 68.5% on unseen players. Loop prediction (`--predict`). Research additions in docs/RESEARCH_2026-11.md.
- **2026-11-10** — GuitarSet benchmark showed 41% on real guitar. Trained chord classifier: 38% → 67% on held-out players. Renamed JamAlong → ElfJamAlong. These four documents written.
