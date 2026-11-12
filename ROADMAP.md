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
- ☐ **Link Audio input.** Check in Live 12.4 whether one track can be sent over Link Audio. If so, add a receiver helper and a `--source link` input: the guitar alone, beat-aligned, with none of our own notes in it. This would retire the tap for Live users.
- ☐ Play it with a real guitar through an interface. Record the session as a new test fixture.
- ☐ Hear it with its own notes audible and Link on. Close out every BUILT NOT TESTED item in STATUS.md.
- ✅ Steadier, quicker decisions: a belief filter replaced "four frames in a row" (+2.6 points on unseen players, 2026-11-12).
- ☐ **More varied training audio.** The classifier is limited by data, not by its features or size (see STATUS.md, "What was tried"). GuitarSet has 15 progressions; minor chords are right 48% of the time against 73% for major. Candidates: GuitarSet's pickup recordings of the same takes, and any other chord-labelled guitar audio whose licence allows it.
- ☐ Faster reaction. Now 0.27 s on the Live loop; the 0.19 s analysis window is the floor. Loop prediction (M3) hides the delay when the progression repeats.
- ☐ Sevenths, sus chords and power chords as their own classes, so the scale choice can use them.
- ☐ Latency calibration for `--offset-ms`.

**Done when:** on held-out GuitarSet rock and singer-songwriter excerpts, 90% correct half a second after a change, and a real-guitar session through Live has been heard and recorded. (The first half is met on unseen players: 92% and 94%. It is not yet shown on unseen progressions.)

## M3 — Know the loop
Guitar loops repeat. Once a progression has gone round twice, predict the next chord before it is played.

- ✅ Detect the loop length and remember the progression (`--predict`, off by default until heard in Live).
- ◐ Give generators the next chord: the bass walks into it; the lead does not use it yet.
- ✅ Fall back to pure following the moment the player leaves the loop.
- ☐ Hear it in Live, then make it the default.
- ☐ Generate ahead of the clock with overlap, so a late decision still has notes to play (the StreamMUSE approach).

**Done when:** on a looping progression, the first note of each bar is over the new chord, not the old one.

## M4 — A trained melody model
Replace the rule-based lead behind the same `MelodyGenerator` interface.

- ☐ Decide the training music (see STATUS.md open decisions). Build the dataset: melodies paired with chords, per sixteenth.
- ☐ First dataset: GuitarSet's solo excerpts (CC BY 4.0), which are improvised over the same charts as the comping we already use. Check POP909's licence before adding it.
- ☐ Hold out players, as for the chord model.
- ☐ Try predicting the bass before the lead; one 2025 study found that ordering best.
- ☐ Small transformer: context = key, current and next chord, bar position, its own recent notes. Runs on CPU in under a few milliseconds per step.
- ☐ Listening test against the rule-based lead on the same progressions.
- ☐ Style selection; later, "play like these MIDI files of mine".

**Done when:** in a blind comparison on ten progressions, the owner prefers the model.

## M5 — Play like a band
- ☐ React to how the player plays: louder and busier guitar → busier lead; space → fills.
- ☐ Call and response: play in the gaps the player leaves (LK Jam is a working example in a VST3).
- ☐ Optional sound source: send the detected chords to Magenta RealTime 2 as MIDI and let it play the band as audio.
- ☐ Role presets (solo lead, lead + bass, full trio) and per-role instruments.
- ☐ Drums: follow ElfBeats over ElfSync, or leave drums to it entirely.

## M6 — A plugin
A terminal program is not something others will install.

- ☐ **Max for Live device** on the guitar track: audio in from the track (no tap, no own-note problem), tempo from Live (no Link), MIDI out to any track.
- ☐ Then **AU / VST3** for Logic and other hosts. This is a rewrite of the real-time path (C++ or Rust); the Python stays as the research bench. The chord model is ~1,200 parameters and ports by hand; for the melody model use RTNeural or anira.
- ☐ Consider starting this milestone before M4: a plugin removes the tap, own-note handling and the Link licence question in one step.
- ☐ Capture as a drag-out MIDI clip.

**Done when:** a musician who has never seen a terminal can drop it on a track and jam.

## Later, maybe
- Other harmonic instruments as input: piano, MIDI keyboard (chords read directly, no audio).
- Windows.
- Logic Pro verified end to end.
- A standalone app with a small window instead of a terminal.

## Not planned
- Generating audio.
- Generating whole songs from a text prompt.
- Cloud inference. It has to run locally, in real time.
