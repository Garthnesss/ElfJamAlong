# ElfJamAlong — Architecture

## Big picture

```
 guitar ──► audio input ─────────┐
                                 ├─► ChordDetector ──► chord, key, "is anyone playing?"
 DAW output ──► livetap (Swift) ─┘         ▲                     │
                                           │ own notes           ▼
 Ableton Link ──► Clock ──► Engine ◄───────┴──── Voices: lead / bass / arp
                              │                    (MelodyGenerator.step)
                              ├─► virtual MIDI port "ElfJamAlong" ──► DAW instrument track
                              └─► history ──► capture ──► .mid file + Live clip
```

One Python package, `src/elfjamalong/`. Dependencies point one way: `cli` → `engine` → generators → `theory`; `chords` → `features` → numpy. Nothing below `cli` does I/O except `midi_out`, `clock` and `capture`.

| Module | Job |
|---|---|
| `theory.py` | `Chord`, `Key`, scales, and `scale_for(chord, key)`: the notes allowed right now |
| `features.py` | `ChromaBands`: FFT frame → 36 features (12 pitch classes × 3 registers), with hidden-bin handling |
| `chords.py` | `ChordDetector` (streaming) and `ChordModel` (the trained classifier) |
| `melody.py` | `MelodyGenerator` protocol, `Context`, `NoteEvent`, and the rule-based lead |
| `roles.py` | `BassLine`, `Arpeggio` |
| `engine.py` | `Engine`, `Voice`: clock ticks → notes; keeps the note history |
| `loop.py` | `ProgressionTracker`: notices a repeating progression and says which chord comes next |
| `clock.py` | `LinkClock` (Ableton Link), `InternalClock` |
| `midi_out.py` | virtual MIDI port, one sink per channel |
| `capture.py` | history → MIDI file; optional clip in Live through the AbletonMCP remote script |
| `cli.py` | commands, audio sources, saved settings (`elfjamalong.toml`) |
| `tools/livetap/` | Swift: Core Audio process tap of one app → mono float32 PCM on stdout |
| `tools/train_chords.py`, `tools/bench_guitarset.py` | train and measure the chord model on GuitarSet |

## Listening

### Audio sources
- **Device** (`--source device`): any input through `sounddevice`. The clean case: a guitar on its own channel.
- **Live tap** (`--source live`): `livetap` creates a private Core Audio process tap on one app (default `com.ableton.live`) and an aggregate device to read it, then streams mono PCM to the Python process over a pipe. No loopback driver, no microphone. It hears the whole app output, including ElfJamAlong's own notes.

### Features
Window 8192 samples (≈170 ms at 48 kHz), hop 2048 (≈43 ms). Magnitude spectrum, log-compressed, 75–2000 Hz. Each bin votes for nearby pitch classes with a Gaussian (σ 0.35 semitone). Votes are kept per register — 75–220, 220–660, 660–2000 Hz — because the low register mostly carries the root. The 36 values are L2-normalised and smoothed with a 0.07 s time constant (`SMOOTH_S`; the classifier is trained with the same value).

### Chord classifier
`ChordModel` is a two-layer network (36 → 32 → 2) that answers "major or minor chord on C?". It is applied to all 12 transpositions of the features, so every root shares the same weights; the 24 outputs go through a softmax. About 1,200 parameters, stored in `chord_model.npz`, evaluated in numpy.

Training (`tools/train_chords.py`): GuitarSet comping excerpts, lead-sheet chords reduced to root + major/minor, random transposition every batch so all keys are equally common, and a copy of every frame with a pretend lead note hidden (see below). A template matcher (harmonic-weighted triads, correlation) remains as `classifier="templates"` and as the "is this pitched at all?" gate that keeps noise and drums from being called chords.

### Decision logic
- The detector carries a **belief** over the 24 chords from frame to frame. Each frame the belief leaks slightly toward the other chords (`stay` 0.9), then is multiplied by the classifier's probabilities raised to `evidence_power` (0.35), so one odd frame cannot overturn it. The reported chord changes when another chord's belief leads the current one by `switch_margin` (0.3).
- The first chord waits 5 frames, because the window is still filling. During silence the belief relaxes toward "no idea", so the next chord played is picked up quickly.
- Frames that do not look pitched (template gate) or where the classifier is unsure (below 0.3) do not count as hearing the player.
- With `classifier="templates"` the older rule applies: the same winner 4 analyses in a row, with a bonus for the current chord.
- Below the level gate (`--gate-db`) nothing is analysed; the last chord is held and `active()` goes false after `--tail` seconds, which stops the voices.

### Key
Each stable frame adds the chord's triad to a pitch-class histogram with a 45 s half-life. Krumhansl–Schmuckler correlation against 24 key profiles picks the key once two different chords have been heard. Relative major/minor are often confused; they share a scale, which is all the generators need.

### Hearing its own notes
The engine tells the detector every note-on and note-off.
- **Lead notes** are hidden when judging the chord: bins within ±0.4 semitone of the note's first 12 harmonics are marked unknown, and each feature is rescaled from the bins that remain. The classifier is trained on frames treated the same way, so a hidden note costs about 1.5 points of accuracy.
- **Bass and arpeggio notes** are not hidden for chord judgement. They are chord tones with dense harmonics; hiding them hides the guitar's own notes and roughly tripled reaction time in measurement.
- **All voices** are discounted for activity: if less than 20% of the spectrum's energy lies outside our own notes' harmonics, the frame is not evidence that the player is playing. This prevents the voices keeping themselves going after the guitar stops.

## Playing

### Engine
`Engine.tick(beat)` is called every 2 ms by `run_realtime`. On each new sixteenth it asks `harmony()` for `(chord, key)` or `None`, then asks every `Voice`'s generator for a `NoteEvent`. Voices are monophonic: a new note releases the previous one; notes also end at their scheduled beat, and a held note that the new chord's scale does not allow is cut when the chord changes. A jump in the clock (loop, relocate) releases everything and resets the generators. Every note played is appended to a history (last 64 bars).

### Knowing the loop (`--predict`)
`ProgressionTracker` records the chord heard on every sixteenth. When the last round matches the one before it over a whole number of bars (1 to 8, at least 85% of sixteenths), it answers with what was heard at this point of the previous round, moved earlier by the detector's lag. The lag is worked out from where the changes were heard: chords change on the eighth-note grid, so of the delays that fit, the one nearest 0.3 s is taken. If what is heard does not fit the loop (within a sixteenth either way) the tracker answers with what is heard, at once; after about 0.35 s of that it forgets the loop. It also passes the next bar's chord to the generators (`Context.next_chord`); the bass uses it for its passing note.

### Generators
One protocol: `step(Context(step, chord, key)) -> NoteEvent | None`, plus `reset()`.
- **Lead** (`RuleBasedMelody`): per-bar onset pattern from beat-weighted probabilities, in four-bar phrases (motif, variation, motif with its contour, sparse ending). Pitch by weighted choice: chord tones on strong beats, stepwise scale motion, step back after a leap, pull toward the middle of the range.
- **Bass** (`BassLine`): root on beat one, fifth/octave patterns, a scale passing note into the next bar.
- **Arpeggio** (`Arpeggio`): eighth notes through root–third–fifth–octave in one of three shapes.

`scale_for` gives the allowed notes: the key's scale with any out-of-key chord tone swapped in for its neighbour (E major in A minor turns G into G♯). Before the key is known, the chord's own pentatonic.

### Clock
`LinkClock` joins the Ableton Link session with a 4-beat quantum, so step 0 of each 16 is the session's downbeat. `--offset-ms` plays early to cancel instrument latency. Measured jitter of note-ons against the grid: under 3 ms.

### MIDI
One virtual port, `ElfJamAlong`. All roles share a channel by default; `--split-channels` gives lead, bass and arp channels N, N+1, N+2.

### Capture
`Engine.last_bars(n)` returns the notes of the last n complete bars, re-timed to start at beat 0, leading empty bars dropped. `capture()` writes a type-1 MIDI file (one track per role) and, if the AbletonMCP remote script answers on localhost:9877, creates a clip in the first empty slot of the track named `ElfJamAlong`. Triggered by Enter in the terminal or `elfjamalong capture` (SIGUSR1 to the running process).

## Tests
`uv run pytest` — 48 tests: detection on synthesized strums and on a loop recorded from Live, own-note handling, generator invariants (in key, in range, monophonic, chord tones on downbeats), loop prediction (alone and end to end on audio), capture round-trip, render. GuitarSet accuracy is a benchmark, not a test, because it needs the 700 MB dataset.
