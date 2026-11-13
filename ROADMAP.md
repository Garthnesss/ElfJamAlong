# ElfJamAlong — Roadmap

Order matters: each milestone makes the next one worth doing. Nothing here is a date.
Recent outside work that shaped this plan is in [docs/RESEARCH_2026-11.md](docs/RESEARCH_2026-11.md).

## M0 — Prototype ✅
Terminal program: chord and key detection, rule-based lead, Link clock, virtual MIDI port, demo and render commands.

## M1 — Hear the DAW, keep the good bits ✅
Driverless tap of Live's output, own-note handling, bass and arpeggio roles, capture to MIDI file and Live clip, saved settings, launcher.

## M2 — Real guitar (in progress)
The detector must be trusted before anything is built on it.

- ✅ GuitarSet benchmark and a trained chord classifier (67% on unseen players, 80–83% on strummed styles).
- ◐ **Link Audio input.** Receiver helper and `--source link` are built and pass against a test sender. Still to do in Live 12.4: check that one track can be sent on its own channel, and hear it. This would retire the tap for Live users.
- ☐ Play it with a real guitar through an interface. Record the session as a new test fixture.
- ☐ Hear it with its own notes audible and Link on. Close out every BUILT NOT TESTED item in STATUS.md.
- ✅ Steadier, quicker decisions: a belief filter replaced "four frames in a row" (+2.6 points on unseen players, 2026-11-12).
- ✅ Pickup recordings added to training, five networks averaged, chords of the key favoured (2026-11-13).
- ☐ **More varied training audio.** The classifier is limited by data, not by its features or size (see STATUS.md, "What was tried"). GuitarSet has 15 progressions. Any other chord-labelled guitar audio whose licence allows it would help more than further tuning.
- ☐ Faster reaction. Now 0.27 s on the Live loop; the 0.19 s analysis window is the floor. Loop prediction (M3) hides the delay when the progression repeats.
- ◐ Dominant sevenths are detected and used for the scale. GuitarSet's lead sheets have no sus or power chords to learn from, so those wait for other data.
- ✅ Latency calibration for `--offset-ms` (`elfjamalong calibrate`; not yet run against Live).

**Done when:** on held-out GuitarSet rock and singer-songwriter excerpts, 90% correct half a second after a change, and a real-guitar session through Live has been heard and recorded. (The first half is met on unseen players: 92% and 94%. It is not yet shown on unseen progressions.)

## M3 — Know the loop
Guitar loops repeat. Once a progression has gone round twice, predict the next chord before it is played.

- ✅ Detect the loop length and remember the progression (`--predict`, off by default until heard in Live).
- ✅ Give generators the next chord: the bass walks into it and the lead approaches it.
- ✅ Fall back to pure following the moment the player leaves the loop.
- ☐ Hear it in Live, then make it the default.
- ☐ Generate ahead of the clock with overlap, so a late decision still has notes to play (the StreamMUSE approach).

**Done when:** on a looping progression, the first note of each bar is over the new chord, not the old one.

## M4 — A trained melody model
Replace the rule-based lead behind the same `MelodyGenerator` interface.

- ✅ First dataset and first model: GuitarSet's solo excerpts (CC BY 4.0), 40,000 sixteenths, players held out. A small network, available as `--lead model`. It predicts unseen players' solos better than a bar-position baseline (loss 1.08 against 1.41) and keeps the in-key, in-range, monophonic contract.
- ☐ **Listen to it.** Nothing above says it sounds better than the rules. That is the test that counts.
- ☐ More music (see STATUS.md open decisions). POP909 is MIT-licensed but its songs are commercial pop.
- ☐ Try predicting the bass before the lead; one 2025 study found that ordering best.
- ☐ A larger model (a small transformer) once there is more data than 90 minutes of solos; the present network is as big as that data supports.
- ☐ Listening test against the rule-based lead on the same progressions.
- ☐ Style selection; later, "play like these MIDI files of mine".

**Done when:** in a blind comparison on ten progressions, the owner prefers the model.

## M5 — Play like a band
- ✅ React to how the player plays: louder guitar → louder, busier lead and bass (`--feel follow`, the default).
- ✅ Call and response: keep off the strums, fill the gaps (`--feel answer`). Works at the level of sixteenths, not whole phrases; trading four-bar phrases is still open.
- ☐ Optional sound source: send the detected chords to Magenta RealTime 2 as MIDI and let it play the band as audio.
- ✅ Role presets (`--preset solo|duo|trio`). Per-role instruments are chosen in the DAW (`--split-channels`).
- ☐ Drums: follow ElfBeats over ElfSync, or leave drums to it entirely.

## M6 — A plugin
A terminal program is not something others will install.

- ☐ **Max for Live device** on the guitar track: audio in from the track (no tap, no own-note problem), tempo from Live (no Link), MIDI out to any track.
- ☐ Then **AU / VST3** for Logic and other hosts. This is a rewrite of the real-time path (C++ or Rust); the Python stays as the research bench. The chord model is ~1,200 parameters and ports by hand; for the melody model use RTNeural or anira.
- ☐ Consider starting this milestone before M4: a plugin removes the tap, own-note handling and the Link licence question in one step.
- ☐ Capture as a drag-out MIDI clip.

**Done when:** a musician who has never seen a terminal can drop it on a track and jam.

## Later, maybe
- ✅ MIDI keyboard as input (`--source midi`). Piano audio would need its own training data.
- Windows.
- Logic Pro verified end to end.
- A standalone app with a small window instead of a terminal.

## Not planned
- Generating audio.
- Generating whole songs from a text prompt.
- Cloud inference. It has to run locally, in real time.
