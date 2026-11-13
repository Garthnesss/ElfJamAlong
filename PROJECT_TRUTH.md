# ElfJamAlong — Project Truth

## One line
A jam partner that listens to the chords you play and answers in real time with MIDI — a lead, a bass line, an arpeggio — in key and on the grid, inside your DAW.

## What it is
- A **listener**: it hears a guitar (an audio input, or the DAW's own output through a driverless tap), and works out the current **chord** and the **key**.
- A **player**: per sixteenth-note it decides what each voice plays over that chord. Today the voices are rule-based (lead, bass, arpeggio); the interface is one method, so a trained model can replace any of them.
- **MIDI out only.** It makes no sound. Notes go to a virtual MIDI port; the instrument is whatever the user loads on the receiving track.
- **In time with the session.** Tempo and bar position come from Ableton Link.
- **A capture tool.** It remembers what it played; one key keeps the last bars as a MIDI file and as a clip in Live.
- Written in **Python** (numpy at run time, no ML framework), with two small helpers: **Swift** for the audio tap (macOS) and **C++** for Link Audio (macOS and Linux).

## What it is not
- Not a song generator. It does not write a track from a prompt; it reacts to a person playing.
- Not an audio effect or a synth. No audio is generated, processed or passed on.
- Not a transcription tool. It needs the chord and key, not every note.
- Not a plugin yet. It is a terminal program beside the DAW (see ROADMAP.md).

## Non-negotiables
1. **The player leads.** ElfJamAlong follows the chords it hears. It never imposes a progression, and it goes quiet when the player stops.
2. **Never fights the grid.** Tempo and bar position come from the session clock (Link today, the host once it is a plugin). No free-running clock when a session exists.
3. **In key, always.** Every note is drawn from the key's scale, bent to include the current chord's tones. A wrong note is a bug, not a flavour.
4. **MIDI-out contract.** Monophonic per voice, every note-on gets its note-off, all notes released on stop. Stuck notes are a bug.
5. **Listening must survive its own playing.** When its output is fed back into what it hears, it knows which notes are its own and discounts them.
6. **Generators are swappable.** Listening, timing, MIDI and capture never depend on how notes are chosen. A model replaces a generator, nothing else.
7. **Measure on real guitar.** Detector changes are judged on recorded guitarists it has not trained on (GuitarSet held-out players), not on synthetic audio alone.
8. **Honest status.** BUILT NOT TESTED is always labelled as such. Nothing is "done" until it has been heard working in the DAW.

## Scope boundaries
- **Chords:** major and minor triads, plus a dominant-seventh flag on major chords. Other sevenths and suspensions resolve to the nearest triad; power chords are a major/minor guess.
- **Input:** one harmonic instrument at a time. Drums and other tracks in the same signal are tolerated, not separated.
- **Host:** Ableton Live is the primary target. Logic Pro works as a MIDI destination; tempo sync there is untried.
- **Platform:** macOS 14.4+ (the audio tap needs it). An audio interface works on any macOS that runs the Python stack.

## Licensing facts that constrain choices
- **`tools/linktap`** is built on the Link SDK, so it is GPLv2+ as well. It is a separate program that the Python side talks to over a pipe, and it is optional.
- **Ableton Link** is GPLv2+ (or a paid proprietary licence). Fine for personal use; a closed-source release must drop or license it. A plugin gets tempo from the host and needs neither.
- **GuitarSet** (the training data of the chord model and of the learned lead) is CC BY 4.0: commercial use is allowed with attribution, which the README carries.
- Selling versus personal use is **undecided** (2026-11-10). Until it is decided, any new dependency, dataset or pretrained model must be usable commercially, or be clearly marked as personal-only.
