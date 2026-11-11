# ElfJamAlong — Status

_Last updated: 2026-11-10_

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
| Unit tests | 38 passing |

### Chord accuracy (GuitarSet players 04–05, model trained on 00–03)

| | Trained model | Templates |
|---|---|---|
| All styles, root + major/minor | 67% | 38% |
| All styles, 0.5 s after a change | 76% | 45% |
| Rock | 80% | |
| Singer-songwriter | 83% | |
| Bossa nova | 65% | |
| Jazz | 58% | |
| Funk | 43% | |

The shipped model is trained on all six players, so it has no held-out score of its own.

## BUILT NOT TESTED
- **Own-note handling with the notes audible.** In every live run the receiving track was un-armed, so nothing ElfJamAlong played was in the signal. Covered only by a simulation with synthesized notes.
- **Arpeggio role** in Live, and `--split-channels`.
- **`ElfJamAlong.command`** by double-click, and capture by pressing Enter (capture was triggered with `elfjamalong capture`).
- **Audio interface input** with a real guitar. The device path has only opened the MacBook microphone.
- **Link sync.** Link was off in Live for every run, so the bar alignment has never been heard.
- **Logic Pro.** Not tried at all.
- **After the rename (2026-11-10):** tests pass, but nothing has been run against Live under the new port name `ElfJamAlong`. The Live track must also be named `ElfJamAlong` for captures to land in it.

## Known problems
- **Major/minor on the same root** is the most common mistake on real guitar (Fm heard as F, and so on).
- **Funk and jazz** are weak: muted strums, sparse voicings and seventh chords.
- **Reaction time** is about 0.3 s on the virtual guitar loop. A new chord's first two sixteenths at 120 BPM are still played over the old chord.
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
- **2026-11-10** — GuitarSet benchmark showed 41% on real guitar. Trained chord classifier: 38% → 67% on held-out players. Renamed JamAlong → ElfJamAlong. These four documents written.
