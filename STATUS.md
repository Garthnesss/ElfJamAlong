# ElfJamAlong — Status

_Last updated: 2026-11-12_

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
| Unit tests | 48 passing |

### Chord accuracy (GuitarSet players 04–05, model trained on 00–03)

Scored live-style every 0.1 s. "Before" is the detector as of 2026-11-10, re-run on 2026-11-12 with the same script.

| | Before | Now | Templates |
|---|---|---|---|
| All styles, root + major/minor | 65.9% | **68.5%** | 38% |
| All styles, 0.5 s after a change | 75.1% | **77.4%** | 45% |
| Rock | 79.6% | 81.4% | |
| Singer-songwriter | 82.7% | 84.1% | |
| Bossa nova | 63.4% | 67.6% | |
| Jazz | 57.0% | 58.8% | |
| Funk | 41.6% | 45.3% | |
| Median time to the right chord after a change | 0.38 s | 0.36 s | |
| Reported changes per real change (1.0 is ideal) | 2.15 | 2.00 | |

Half a second after a change, rock is 92% and singer-songwriter 94%.

**These figures are optimistic for music the model has not met.** GuitarSet has 15 chord progressions (three per style) and every player plays all of them, so holding out players still tests on familiar progressions. With one progression of each style also held out:

| Players 04–05, unseen progression | Before | Now |
|---|---|---|
| Progression 2: all / settled | 53.6% / 61.0% | 54.5% / 61.3% |
| Progression 3: all / settled | 64.3% / 76.4% | 66.8% / 78.1% |

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
| Five models averaged | +1 to +1.5 on every split | not yet: small; worth taking with the next retrain |
| Belief filter + 0.07 s smoothing (decision logic) | +2.6 live, also better on unseen progressions | **yes** |

Where the errors are (baseline, per frame): 67% right; 4% right root with the wrong quality; 3% still the previous chord; 5% the relative major or minor (Am heard as C, C as Em). Chords labelled minor are right 48% of the time, major 73%.

## BUILT NOT TESTED
- **Everything changed on 2026-11-12 has only been run on recordings and in tests, on Linux, without Live:** the belief filter and retrained model, `--predict`, cutting held notes on a chord change, `render --roles`.
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
- **2026-11-12** — Code review and fixes (held notes cut on a chord change, all-notes-off on every channel, chord names like G7 accepted, unknown settings reported, `render --roles`). Classifier experiments: no feature or size change helped; found the benchmark shares progressions between train and test. Belief filter in the detector: 65.9% → 68.5% on unseen players. Loop prediction (`--predict`). Research additions in docs/RESEARCH_2026-11.md.
- **2026-11-10** — GuitarSet benchmark showed 41% on real guitar. Trained chord classifier: 38% → 67% on held-out players. Renamed JamAlong → ElfJamAlong. These four documents written.
