# ElfJamAlong

Plays a MIDI melody along with your guitar: it listens to the guitar input,
works out the chord and key, and sends an in-key melody to your DAW in time with
the session.

This is the plumbing prototype. The melody comes from rules (chord tones on
strong beats, scale steps between, four-bar phrases), not a trained model. The
generator sits behind a one-method interface (`MelodyGenerator.step` in
`src/elfjamalong/melody.py`) so a model can replace it later.

```
guitar audio ──> chord + key detection ──┐
                                         ├──> melody generator ──> virtual MIDI port "ElfJamAlong" ──> DAW instrument track
DAW tempo / bar position (Ableton Link) ─┘
```

Project documents: [PROJECT_TRUTH.md](PROJECT_TRUTH.md) (what it is and is not), [ARCHITECTURE.md](ARCHITECTURE.md), [STATUS.md](STATUS.md) (what is verified), [ROADMAP.md](ROADMAP.md).

## Try it without a guitar

```bash
uv run elfjamalong demo --chords "Am F C G"
```

This loops the typed progression and sends the melody over MIDI, which is the
quickest way to check the Ableton routing below.

```bash
uv run elfjamalong render --chords "Am F C G" --bars 16 -o jam.mid
```

writes the melody and the chords to a MIDI file you can drag into a DAW. Add
`--roles lead,bass,arp` for one track per role. Chord names with extensions are
accepted and land on their triad (`G7` plays as G, `Dm7` as Dm).

## Ableton Live setup

1. Start ElfJamAlong first (`demo` or `run`), so the `ElfJamAlong` MIDI port exists.
2. Live > Settings > Link, Tempo & MIDI:
   - turn **Link** on (ElfJamAlong then follows Live's tempo and bar position);
   - under MIDI input ports, tick **Track** for `ElfJamAlong`.
3. Create a MIDI track with any instrument. Set **MIDI From** to `ElfJamAlong`,
   and **Monitor** to **In**.
4. Put the guitar on an audio track as usual, start your drums, and play.

## Play along

```bash
uv run elfjamalong devices
```

lists audio inputs. Then, with your interface's index or name:

```bash
uv run elfjamalong run --device 2 --input-channel 1
```

macOS will ask to let the terminal use the microphone the first time. The
terminal prints the chord and key it hears. The melody starts on the next
downbeat after it hears a chord and stops a few seconds after you stop.

Useful options:

| Option | Effect |
|---|---|
| `--key "A minor"` | lock the key instead of detecting it |
| `--density 0.3` | sparser melody (0.05 to 1, default 0.5) |
| `--low 72 --high 96` | move the melody's range (MIDI note numbers) |
| `--offset-ms 20` | play early to cancel instrument latency |
| `--tail 2` | stop sooner after the guitar goes quiet |
| `--follow-transport` | only play while Live is playing (enable Start Stop Sync in Live's Link settings) |
| `--predict` | once your progression has repeated, play over the chord that comes next instead of waiting to hear it (new, not yet tried in Live) |
| `--gate-db -40` | ignore more background noise |
| `--no-link --bpm 96` | run on an internal clock without a DAW |

## Everyday use

Double-click `ElfJamAlong.command` (or run `uv run elfjamalong run`). Settings come from
`elfjamalong.toml`; any long option can be saved there without its dashes.

**Roles.** `--roles lead,bass,arp` adds a bass line and an arpeggio that follow
the same chords. By default every role plays on one MIDI channel, so a single
piano-like instrument plays all of them. `--split-channels` sends lead, bass and
arp on channels 1, 2 and 3, for one instrument track each (set each track's MIDI
From channel in Live).

**Capture.** Press Enter in the ElfJamAlong window, or run `uv run elfjamalong capture`
from another terminal, to keep the last 8 complete bars (`--capture-bars`). They
are written to `captures/` as a MIDI file with one track per role. If the
AbletonMCP remote script is running in Live, the same notes also go into the
first empty clip slot of the track named `ElfJamAlong` (`--live-track`).

## No interface: listen to the DAW directly

```bash
tools/livetap/build.sh
```

builds a small helper once (needs Xcode's command line tools, macOS 14.4+). Then

```bash
uv run elfjamalong run --source live
```

captures Ableton Live's own audio output with no loopback driver and no
microphone. macOS may ask once for permission to record system audio. Use
`--app <bundle id>` for another DAW, e.g. `--app com.apple.logic10`.

The tap hears everything Live plays, including what ElfJamAlong itself triggers.
ElfJamAlong knows which notes are its own: the lead's harmonics are treated as
unknown when judging the chord, and all of its notes are discounted when deciding
whether you are still playing. Drums and other tracks are still in the signal; a
guitar on its own input is cleaner.

For a guitar stand-in, put strummed chords in a MIDI clip on a track with a
guitar instrument (Live's "Guitar Acoustic" works) and loop it.

## Logic Pro

The MIDI side works the same: `ElfJamAlong` appears as a MIDI input, so a software
instrument track that is record-enabled will receive the notes. Tempo sync
depends on Logic joining the Ableton Link session; this has not been tried.
Without it, use `--no-link --bpm <project tempo>`, which matches the tempo but
not the bar position.

## What it detects

Major and minor triads only. Sevenths and suspended chords land on the nearest
triad; a bare power chord has no third, so major/minor is a guess there. The key
is estimated from the chords heard so far and appears after two different
chords; until then the melody stays on the current chord's pentatonic.

The chord is chosen by a small trained network (`src/elfjamalong/chord_model.npz`,
about 11 KB, plain numpy at run time). It reads pitch-class energy in three
registers and shares its weights across all 12 roots. `classifier="templates"`
on `ChordDetector` switches back to the untrained template matcher.

Accuracy on real guitar, measured live-style (causal, every 0.1 s) on GuitarSet
players the model did not train on:

| | trained model | templates |
|---|---|---|
| all styles | 68% | 38% |
| rock, singer-songwriter | 81-84% | |
| jazz, bossa nova | 59-68% | |
| funk | 45% | |

Half a second after a chord change the all-styles figure is 77% (rock 92%,
singer-songwriter 94%). The right chord appears a median 0.36 s after a change.
GuitarSet has only 15 chord progressions, which every player plays, so these
figures are for progressions the model has met; on a progression it has not met
they are a few points lower (see STATUS.md). The shipped model is trained on all
six players, so it has no held-out score of its own.

```bash
uv run python tools/train_chords.py data/guitarset          # train on 4 players, test on 2
uv run python tools/train_chords.py data/guitarset --hold-progression 3   # stricter: also an unseen progression
uv run python tools/train_chords.py data/guitarset --final  # train on all, write the model
uv run python tools/bench_guitarset.py data/guitarset       # live-pipeline accuracy, reaction time, stability
```

These need `annotation.zip` and `audio_mono-mic.zip` from GuitarSet in
`data/guitarset/` (not in git).

The model is derived from GuitarSet (Q. Xi, R. Bittner, J. Pauwels, X. Ye,
J. P. Bello, "GuitarSet: A Dataset for Guitar Transcription", ISMIR 2018),
licensed CC BY 4.0: https://zenodo.org/records/3371780

## Tests

```bash
uv run pytest
```

The tests feed synthesized strummed chords through the detector and check the
melody stays in key, in range and monophonic, that a loud melody note on top
of a chord does not change the detected chord, and that a repeating progression
is predicted. They do not cover a real guitar signal.
