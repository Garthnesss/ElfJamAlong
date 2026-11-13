import numpy as np
import pytest

from elfjamalong.chords import ChordDetector
from elfjamalong.engine import Engine
from elfjamalong.melody import RuleBasedMelody
from elfjamalong.theory import Chord, Key, scale_for

from synth import VOICINGS, strum

SR = 44100


def detect(progression, seconds=2.0, block=512):
    """Play a progression into the detector; return the chord reported at the end of each bar."""
    now = [0.0]
    det = ChordDetector(SR, clock=lambda: now[0])
    rng = np.random.default_rng(1)
    heard = []
    for name in progression:
        audio = strum(name, seconds, SR, rng=rng)
        for i in range(0, len(audio), block):
            det.feed(audio[i : i + block])
            now[0] += block / SR
        heard.append(str(det.chord))
    return det, heard


@pytest.mark.parametrize("name", sorted(VOICINGS))
def test_single_chords(name):
    _, heard = detect([name])
    assert heard == [name]


@pytest.mark.parametrize("progression,scale_of", [
    (["Am", "F", "C", "G"] * 2, "C major"),
    (["G", "D", "Em", "C"] * 2, "G major"),
    (["D", "A", "Bm", "G"] * 2, "D major"),
    (["Am", "Dm", "E", "Am"] * 2, "A minor"),
])
def test_progression_and_key(progression, scale_of):
    det, heard = detect(progression)
    assert heard == progression
    # Relative major/minor share a scale, which is all the melody needs.
    assert det.key is not None
    expected = Key.parse(scale_of).pitch_classes
    if scale_of == "A minor":  # E major borrows G#, so allow either minor flavour
        assert det.key.tonic in (9, 0)
    else:
        assert det.key.pitch_classes == expected


def test_change_latency_under_half_second():
    now = [0.0]
    det = ChordDetector(SR, clock=lambda: now[0])
    audio = np.concatenate([strum("C", 2.0, SR), strum("G", 2.0, SR)])
    switched = None
    for i in range(0, len(audio), 256):
        det.feed(audio[i : i + 256])
        now[0] += 256 / SR
        if switched is None and now[0] > 2.0 and str(det.chord) == "G":
            switched = now[0] - 2.0
    assert switched is not None and switched < 0.5, switched


def test_silence_goes_inactive_and_noise_is_not_a_chord():
    now = [0.0]
    det = ChordDetector(SR, clock=lambda: now[0])
    noise = np.random.default_rng(3).normal(0, 0.05, SR * 2).astype(np.float32)
    det.feed(noise)
    assert det.chord is None
    det.feed(strum("Em", 2.0, SR))
    now[0] += 2.0
    assert det.active(4.0)
    det.feed(np.zeros(SR * 5, dtype=np.float32))
    now[0] += 5.0
    assert not det.active(4.0)


class Sink:
    def __init__(self):
        self.on, self.sounding, self.max_poly, self.t = [], set(), 0, 0.0

    def note_on(self, pitch, velocity):
        self.on.append((self.t, pitch, velocity))
        self.sounding.add(pitch)
        self.max_poly = max(self.max_poly, len(self.sounding))

    def note_off(self, pitch):
        self.sounding.discard(pitch)


def play(chords, key, bars, seed, **kw):
    sink = Sink()
    bar = [0]
    eng = Engine(RuleBasedMelody(seed=seed, **kw), sink, lambda: (chords[bar[0] % len(chords)], key))
    beat = 0.0
    while beat < bars * 4:
        bar[0] = int(beat // 4)
        sink.t = beat
        eng.tick(beat)
        beat += 0.01
    eng.stop()
    return sink


@pytest.mark.parametrize("seed", range(8))
def test_melody_in_key_in_range_monophonic(seed):
    chords = [Chord.parse(c) for c in "Am F C G".split()]
    key = Key.parse("C major")
    sink = play(chords, key, 32, seed)
    assert len(sink.on) > 60
    assert sink.max_poly == 1 and not sink.sounding
    assert all(60 <= p <= 84 for _, p, _ in sink.on)
    assert all(p % 12 in key.pitch_classes for _, p, _ in sink.on)
    downbeats = [(t, p) for t, p, _ in sink.on if round(t * 4) % 16 == 0]
    hits = sum(p % 12 in chords[int(t // 4) % 4].pitch_classes for t, p in downbeats)
    assert hits / len(downbeats) > 0.9
    leaps = [abs(b[1] - a[1]) for a, b in zip(sink.on, sink.on[1:])]
    assert np.mean(leaps) < 4.5 and max(leaps) <= 12
    assert len({p for _, p, _ in sink.on}) >= 6  # it actually moves around


def test_borrowed_chord_bends_the_scale():
    key = Key.parse("A minor")
    allowed = scale_for(Chord.parse("E"), key)
    assert 8 in allowed and 7 not in allowed  # G# in, G out
    sink = play([Chord.parse("E")], key, 16, seed=1)
    assert all(p % 12 != 7 for _, p, _ in sink.on)


def test_unknown_key_uses_chord_pentatonic():
    sink = play([Chord.parse("Em")], None, 16, seed=2)
    assert {p % 12 for _, p, _ in sink.on} <= {4, 7, 9, 11, 2}


def test_engine_silent_without_harmony_and_density_scales():
    sink = Sink()
    eng = Engine(RuleBasedMelody(seed=0), sink, lambda: None)
    for i in range(2000):
        eng.tick(i * 0.01)
    assert sink.on == []
    c = [Chord.parse("C")]
    sparse = len(play(c, None, 32, 0, density=0.2).on)
    busy = len(play(c, None, 32, 0, density=0.9).on)
    assert busy > sparse * 1.5


def _with_melody(chord, note, seconds=3.0, level=0.5):
    """A strummed chord with a loud sustained synth note on top (our own melody leaking back)."""
    audio = strum(chord, seconds, SR, strums=3)
    t = np.arange(len(audio)) / SR
    f = 440 * 2 ** ((note - 69) / 12)
    lead = sum(np.sin(2 * np.pi * f * h * t) / h for h in (1, 2, 3, 4))
    return (audio + level * lead / np.max(np.abs(lead))).astype(np.float32)


# (An A held over C major is left out: C-E-G-A is as much Am7 as C6, and both share a scale.)
@pytest.mark.parametrize("chord,note", [("C", 74), ("G", 76), ("Am", 77), ("Em", 72), ("D", 71)])
def test_own_melody_does_not_change_the_chord(chord, note):
    """A loud non-chord melody note fools a naive detector; telling it the note is ours fixes that."""
    now = [0.0]
    det = ChordDetector(SR, clock=lambda: now[0])
    det.own_note_on(note)
    audio = _with_melody(chord, note)
    for i in range(0, len(audio), 512):
        det.feed(audio[i : i + 512])
        now[0] += 512 / SR
    assert str(det.chord) == chord


def test_own_melody_alone_is_not_heard_as_playing():
    now = [0.0]
    det = ChordDetector(SR, clock=lambda: now[0])
    t = np.arange(SR * 3) / SR
    lead = (0.3 * sum(np.sin(2 * np.pi * 440 * h * t) / h for h in (1, 2, 3, 4, 5))).astype(np.float32)
    det.own_note_on(69)
    for i in range(0, len(lead), 512):
        det.feed(lead[i : i + 512])
        now[0] += 512 / SR
    assert det.chord is None and not det.active(4.0)


def test_recorded_virtual_guitar_loop_has_no_wrong_chords():
    """Two passes of a strummed loop recorded from Live: only the true chord (or the previous
    one, while the change is being confirmed) may ever be reported."""
    import wave
    from pathlib import Path

    w = wave.open(str(Path(__file__).parent / "fixtures" / "virtual-guitar-am-dm-g-c-f-dm-e-am.wav"))
    sr = w.getframerate()
    x = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(np.float32) / 32768
    truth = ["Am", "Dm", "G", "C", "F", "Dm", "E", "Am"]
    now = [0.0]
    det = ChordDetector(sr, clock=lambda: now[0])
    latencies, bar_seen = [], -1
    for i in range(0, len(x), 256):
        det.feed(x[i : i + 256])
        now[0] += 256 / sr
        t = now[0] - 0.05
        if t < 0 or det.chord is None:
            continue
        bar, into = divmod(t, 2.0)
        bar = int(bar)
        assert str(det.chord) in (truth[bar % 8], truth[(bar - 1) % 8]), (t, str(det.chord))
        if str(det.chord) == truth[bar % 8] and bar != bar_seen:
            bar_seen = bar
            latencies.append(into)
    assert len(latencies) >= 16 and max(latencies) < 0.7
    assert det.key is not None and det.key.pitch_classes == Key.parse("A minor").pitch_classes


# ------------------------------------------------- own notes from a capture MIDI

from pathlib import Path

_FIXTURES = Path(__file__).parent / "fixtures"
_EXISTING_STEM = "virtual-guitar-am-dm-g-c-f-dm-e-am"
_EXPECTED_TRIO_STEM = "trio-own-notes-am-dm-g-c-f-dm-e-am"
# Any real trio fixture already recorded is picked up automatically; the expected
# one is always listed so that, while it is absent, it skips with a clear reason.
_TRIO_STEMS = sorted(q.stem for q in _FIXTURES.glob("trio-own-notes-*.wav"))
_FIXTURE_STEMS = [_EXISTING_STEM] + (_TRIO_STEMS if _EXPECTED_TRIO_STEM in _TRIO_STEMS
                                      else [_EXPECTED_TRIO_STEM] + _TRIO_STEMS)


def _own_note_events(midi_path):
    """(time_s, is_on, pitch, cancel) for every ElfJamAlong voice in a capture/render MIDI.

    Only tracks named ``ElfJamAlong <voice>`` count: a render file also carries a
    ``Chords`` track (the progression itself), which is the player, not us.
    Mirrors ``cli._TellDetector``: the lead is told to the detector with
    ``cancel=True`` (its pitch is hidden when scoring chords), bass and arp with
    ``cancel=False`` (registered, so they do not count as the player playing, but
    their chord tones are not hidden -- see ChordDetector.own_note_on).
    Returns (events, bar_seconds); tempo is the file's single set_tempo (120 BPM
    if it has none), as written by capture.midi_file and by ``render``.
    """
    import mido

    mid = mido.MidiFile(midi_path)
    tempo = 500000  # mido default, 120 BPM
    for track in mid.tracks:
        found = [m.tempo for m in track if m.type == "set_tempo"]
        if found:
            tempo = found[0]
            break
    sec_per_tick = tempo / 1_000_000 / mid.ticks_per_beat
    events = []
    for track in mid.tracks:
        name, tick, pending = "", 0, []
        for msg in track:
            tick += msg.time
            if msg.type == "track_name":
                name = msg.name
            elif msg.type in ("note_on", "note_off"):
                pending.append((tick, msg))
        if not name.startswith("ElfJamAlong"):
            continue
        cancel = "lead" in name.lower()
        for tick, msg in pending:
            is_on = msg.type == "note_on" and msg.velocity > 0
            events.append((tick * sec_per_tick, is_on, msg.note, cancel))
    events.sort(key=lambda e: (e[0], e[1]))  # note-offs before note-ons at the same instant
    return events, 4 * tempo / 1_000_000  # seconds per bar (4 beats)


def _load_wav_mono(path):
    """Mono float audio from a WAV of 8/16/32-bit PCM, any channel count (downmixed)."""
    import wave

    w = wave.open(str(path))
    sr, channels, width = w.getframerate(), w.getnchannels(), w.getsampwidth()
    raw = w.readframes(w.getnframes())
    if width == 2:
        x = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768
    elif width == 4:
        x = np.frombuffer(raw, dtype="<i4").astype(np.float32) / 2147483648
    elif width == 1:
        x = (np.frombuffer(raw, dtype=np.uint8).astype(np.float32) - 128) / 128
    else:
        raise ValueError(f"unsupported WAV sample width: {width} bytes")
    return sr, x.reshape(-1, channels).mean(axis=1) if channels > 1 else x


def _detect_with_own_notes(wav_path, midi_path, truth):
    """Feed a recording to the detector, telling it (from the capture MIDI, in time
    with the audio) which notes were ElfJamAlong's own. Same discipline as
    test_recorded_virtual_guitar_loop_has_no_wrong_chords: only the true chord (or
    the previous one, while the change is being confirmed) may ever be reported.
    Returns (detector, latencies, full_bars): the per-bar reaction times and how
    many whole bars the recording holds."""
    sr, x = _load_wav_mono(wav_path)
    events, bar_s = _own_note_events(midi_path)
    now = [0.0]
    det = ChordDetector(sr, clock=lambda: now[0])
    latencies, bar_seen, nxt = [], -1, 0
    for i in range(0, len(x), 256):
        while nxt < len(events) and events[nxt][0] <= now[0]:
            _, is_on, pitch, cancel = events[nxt]
            if is_on:
                det.own_note_on(pitch, cancel=cancel)
            else:
                det.own_note_off(pitch)
            nxt += 1
        det.feed(x[i : i + 256])
        now[0] += 256 / sr
        t = now[0] - 0.05
        if t < 0 or det.chord is None:
            continue
        bar, into = divmod(t, bar_s)
        bar = int(bar)
        assert str(det.chord) in (truth[bar % len(truth)], truth[(bar - 1) % len(truth)]), (t, str(det.chord))
        if str(det.chord) == truth[bar % len(truth)] and bar != bar_seen:
            bar_seen = bar
            latencies.append(into)
    return det, latencies, int(len(x) / sr // bar_s)


@pytest.mark.parametrize("stem", _FIXTURE_STEMS)
def test_recorded_loop_with_own_notes_has_no_wrong_chords(stem, tmp_path):
    """Task 7, code half: a recorded loop plus the capture MIDI of what ElfJamAlong
    itself played over it, with the detector told which notes were its own.

    The existing virtual-guitar WAV runs today against a SYNTHESIZED capture (a trio
    rendered over the same progression, length and tempo). A real fixture
    tests/fixtures/trio-own-notes-<progression>.wav + .mid is picked up as soon as
    it exists; until then that parameter skips. To swap the real recording in, the
    lead only has to drop the two files in tests/fixtures/ -- no code change.

    One assertion differs for the stand-in, deliberately: the reaction bound is
    1.0 s there, not 0.7 s. In the stand-in the trio's notes are not actually in
    the audio, so registering them makes the detector discard every frame whose
    spectrum lies mostly under the trio's harmonic masks (measured: 321 of 758
    frames, seed 1; worst bar reaction 0.84 s, no wrong chords). The real fixture,
    where the notes really are in the signal, keeps the faithful 0.7 s bound."""
    from elfjamalong.cli import main

    wav = _FIXTURES / f"{stem}.wav"
    if stem == _EXISTING_STEM:
        truth = ["Am", "Dm", "G", "C", "F", "Dm", "E", "Am"]
        midi = tmp_path / "synthesized-trio-capture.mid"
        max_latency = 1.0  # stand-in only; see docstring
        assert main(["render", "--chords", " ".join(truth), "--preset", "trio",
                     "--bars", "16", "--seed", "1", "-o", str(midi)]) == 0
    else:
        midi = _FIXTURES / f"{stem}.mid"
        max_latency = 0.7  # the existing test's bound, unchanged for the real recording
        if not wav.exists() or not midi.exists():
            pytest.skip(f"real trio fixture not recorded yet: need {wav.name} and {midi.name} "
                        "in tests/fixtures (docs/MUSE_HANDOFF.md task 7)")
        truth = [tok.capitalize() for tok in stem[len("trio-own-notes-"):].split("-")]
    det, latencies, full_bars = _detect_with_own_notes(wav, midi, truth)
    assert len(latencies) >= full_bars and max(latencies) < max_latency
    if truth == ["Am", "Dm", "G", "C", "F", "Dm", "E", "Am"]:
        assert det.key is not None and det.key.pitch_classes == Key.parse("A minor").pitch_classes


def _play_voices(chords, key, bars, roles):
    from elfjamalong.engine import Voice
    from elfjamalong.roles import Arpeggio, BassLine

    makers = {"lead": lambda: RuleBasedMelody(seed=1), "bass": lambda: BassLine(seed=1), "arp": lambda: Arpeggio(seed=1)}
    sinks = {r: Sink() for r in roles}
    bar = [0]
    eng = Engine([Voice(r, makers[r](), sinks[r]) for r in roles], lambda: (chords[bar[0] % len(chords)], key))
    beat = 0.0
    while beat < bars * 4:
        bar[0] = int(beat // 4)
        for s in sinks.values():
            s.t = beat
        eng.tick(beat)
        beat += 0.01
    return eng, sinks


def test_bass_and_arp_follow_the_chord():
    chords = [Chord.parse(c) for c in "Am F C G".split()]
    key = Key.parse("C major")
    eng, sinks = _play_voices(chords, key, 16, ["lead", "bass", "arp"])
    for s in sinks.values():
        assert s.max_poly == 1 and len(s.on) > 30
    bass, arp = sinks["bass"].on, sinks["arp"].on
    assert all(33 <= p <= 52 for _, p, _ in bass)
    downbeats = [(t, p) for t, p, _ in bass if round(t * 4) % 16 == 0]
    assert len(downbeats) == 16
    assert all(p % 12 == chords[int(t // 4) % 4].root for t, p in downbeats)  # root on beat one
    assert all(p % 12 in key.pitch_classes for _, p, _ in bass)
    assert all(p % 12 in chords[int(t // 4) % 4].pitch_classes for t, p, _ in arp)
    assert len(arp) == 16 * 8  # steady eighths
    eng.stop()
    assert not any(s.sounding for s in sinks.values())


def test_capture_last_bars_to_midi_file(tmp_path):
    import mido

    from elfjamalong.capture import capture

    chords = [Chord.parse(c) for c in "Am F C G".split()]
    eng, sinks = _play_voices(chords, Key.parse("C major"), 12.5, ["lead", "bass"])
    notes, bars = eng.last_bars(4)  # stopped mid-bar 13 -> bars 9..12
    assert bars == 4
    assert all(0 <= n.start_beat < 16 and n.start_beat + n.length_beats <= 16 + 1e-9 for n in notes)
    expected = [(t, p) for t, p, _ in sinks["lead"].on if 32 <= t < 48]
    got = [(n.start_beat + 32, n.pitch) for n in notes if n.voice == "lead"]
    assert [p for _, p in got] == [p for _, p in expected]
    assert all(abs(a[0] - b[0]) < 0.011 for a, b in zip(got, expected))

    lines = capture(notes, bars, 120.0, "C major", tmp_path, live_track=None)
    files = list(tmp_path.glob("*.mid"))
    assert len(files) == 1 and "saved" in lines[0]
    mid = mido.MidiFile(files[0])
    assert [t.name for t in mid.tracks[1:]] == ["ElfJamAlong bass", "ElfJamAlong lead"]
    ons = sum(1 for t in mid.tracks for m in t if m.type == "note_on")
    assert ons == len(notes)
    assert capture([], 0, 120.0, "", tmp_path, live_track=None) == ["nothing to capture yet"]


def test_own_bass_and_arp_alone_do_not_count_as_the_player():
    """With the guitar silent, our own bass and arpeggio must not keep the jam going."""
    now = [0.0]
    det = ChordDetector(SR, clock=lambda: now[0])
    t = np.arange(SR * 3) / SR
    audio = np.zeros(len(t))
    for pitch in (45, 57, 60, 64):  # A minor, as a bass note plus arpeggio tones
        f = 440 * 2 ** ((pitch - 69) / 12)
        audio += sum(np.sin(2 * np.pi * f * h * t) / h for h in range(1, 7))
        det.own_note_on(pitch, cancel=False)
    audio = (0.2 * audio / np.max(np.abs(audio))).astype(np.float32)
    for i in range(0, len(audio), 512):
        det.feed(audio[i : i + 512])
        now[0] += 512 / SR
    assert det.chord is None and not det.active(4.0)


# ------------------------------------------------------------ changes of 2026-11-12


def test_chord_names_with_extensions_land_on_their_triad():
    assert [str(Chord.parse(c)) for c in ["G7", "Dm7", "Cmaj7", "Bb", "F#m", "Asus4", "Ebm"]] == \
        ["G7", "Dm", "C", "A#", "F#m", "A", "D#m"]
    assert Chord.parse("G7") == Chord.parse("G")  # still the G chord to everything that follows chords
    with pytest.raises(ValueError):
        Chord.parse("Bdim")


def test_held_note_is_cut_when_the_new_chord_does_not_allow_it():
    """A long note from the previous bar must not ring on over a chord whose scale excludes it."""
    from elfjamalong.engine import Voice
    from elfjamalong.melody import NoteEvent

    class OneLongNote:
        def step(self, ctx):
            return NoteEvent(67, 100, 32) if ctx.step == 0 else None  # G, two bars long

        def reset(self): ...

    sink = Sink()
    bar = [0]
    key = Key.parse("A minor")
    chords = [Chord.parse("Am"), Chord.parse("E")]  # E major swaps G for G#
    eng = Engine([Voice("lead", OneLongNote(), sink)], lambda: (chords[bar[0]], key))
    beat = 0.0
    while beat < 8:
        bar[0] = int(beat // 4)
        eng.tick(beat)
        if beat < 3.9:
            assert sink.sounding == {67}
        elif beat > 4.05:
            assert not sink.sounding
        beat += 0.01
    notes, _ = eng.last_bars(1)
    assert eng.history[0].length_beats == 4.0  # the capture shows the shortened note


def _loop_run(progression, bars, lag=2, tracker=None):
    """Feed a tracker what a detector would report: the true chord, `lag` steps late."""
    from elfjamalong.loop import ProgressionTracker

    tracker = tracker or ProgressionTracker(lambda: 120.0)
    rows = []
    for step in range(bars * 16):
        truth = progression[(step // 16) % len(progression)]
        heard = progression[(max(step - lag, 0) // 16) % len(progression)]
        now, nxt = tracker.update(step, heard)
        rows.append((step, truth, heard, now, nxt))
    return tracker, rows


def test_loop_is_predicted_after_two_rounds_and_not_before():
    prog = [Chord.parse(c) for c in "Am F C G".split()]
    tracker, rows = _loop_run(prog, 16)
    early = [r for r in rows if r[0] < 8 * 16 - 1]  # the second round ends at step 127
    assert all(now == heard and nxt is None for _, _, heard, now, nxt in early)  # pure following
    late = [r for r in rows if r[0] >= 9 * 16]
    assert tracker.loop_steps == 64
    assert all(now == truth for _, truth, _, now, _ in late)  # including the first step of every bar
    assert any(heard != truth for _, truth, heard, _, _ in late)  # which plain following gets wrong
    assert all(nxt == prog[(step // 16 + 1) % 4] for step, _, _, _, nxt in late)


def test_leaving_the_loop_falls_back_to_following():
    prog = [Chord.parse(c) for c in "Am F C G".split()]
    tracker, _ = _loop_run(prog, 12)
    assert tracker.loop_steps == 64
    other = Chord.parse("D")
    answers = [tracker.update(12 * 16 + i, other)[0] for i in range(8)]
    assert answers == [other] * 8  # it plays what it hears from the first sixteenth
    assert tracker.loop_steps is None  # and has forgotten the loop


def test_a_held_chord_is_not_a_reason_to_react_late():
    """Three bars of one chord look like a one-bar loop; the change after them must not be delayed."""
    from elfjamalong.loop import ProgressionTracker

    tracker = ProgressionTracker(lambda: 120.0)
    am, f = Chord.parse("Am"), Chord.parse("F")
    for step in range(48):
        assert tracker.update(step, am)[0] == am
    assert tracker.loop_steps == 16
    assert tracker.update(48, f)[0] == f


def test_loop_survives_a_change_heard_one_sixteenth_late():
    prog = [Chord.parse(c) for c in "Am F C G".split()]
    tracker, _ = _loop_run(prog, 12)
    for step in range(12 * 16, 14 * 16):  # this round the detector is a sixteenth slower
        truth = prog[(step // 16) % 4]
        heard = prog[((step - 3) // 16) % 4]
        assert tracker.update(step, heard)[0] == truth
    assert tracker.loop_steps == 64


def test_bass_walks_into_the_next_chord_when_the_loop_is_known():
    from elfjamalong.melody import Context
    from elfjamalong.roles import BassLine

    key = Key.parse("C major")
    for seed in range(6):
        bass = BassLine(seed=seed)
        notes = {s: bass.step(Context(s, Chord.parse("C"), key, Chord.parse("F"))) for s in range(16)}
        if notes[14] is not None:  # patterns with a passing note on the last eighth
            assert abs(notes[14].pitch % 12 - 5) in (1, 2) or abs(notes[14].pitch % 12 - 5) in (10, 11)
            assert notes[14].pitch % 12 in key.pitch_classes


def test_render_writes_one_track_per_role(tmp_path):
    import mido

    from elfjamalong.cli import main

    out = tmp_path / "jam.mid"
    assert main(["render", "--chords", "Am F G7 C", "--roles", "lead,bass,arp", "--bars", "8", "--seed", "3",
                 "-o", str(out)]) == 0
    mid = mido.MidiFile(out)
    assert [t.name for t in mid.tracks[1:]] == ["ElfJamAlong lead", "ElfJamAlong bass", "ElfJamAlong arp", "Chords"]
    for track in mid.tracks[1:]:
        ons = sum(m.type == "note_on" for m in track)
        assert ons > 8 and ons == sum(m.type == "note_off" for m in track)
    assert abs(mid.length - 16.0) < 0.1  # 8 bars at 120 BPM


def test_first_chord_after_silence_and_changes_are_prompt():
    """The belief filter must not make the detector sluggish after a pause."""
    now = [0.0]
    det = ChordDetector(SR, clock=lambda: now[0])
    audio = np.concatenate([strum("Am", 2.0, SR), np.zeros(SR * 3, dtype=np.float32), strum("D", 2.0, SR)])
    heard_d = None
    for i in range(0, len(audio), 256):
        det.feed(audio[i : i + 256])
        now[0] += 256 / SR
        if heard_d is None and now[0] > 5.0 and str(det.chord) == "D":
            heard_d = now[0] - 5.0
    assert heard_d is not None and heard_d < 0.4, heard_d


def test_detector_plus_tracker_puts_bar_starts_on_the_new_chord():
    """End to end on audio: fourth round of a strummed loop at 120 BPM (a bar is 2 s, a sixteenth 0.125 s)."""
    from elfjamalong.loop import ProgressionTracker

    names = ["Am", "F", "C", "G"]
    rng = np.random.default_rng(5)
    audio = np.concatenate([strum(n, 2.0, SR, strums=4, rng=rng) for n in names * 4])
    now = [0.0]
    det = ChordDetector(SR, clock=lambda: now[0])
    tracker = ProgressionTracker(lambda: 120.0)
    step_len = int(0.125 * SR)
    followed = predicted = starts = 0
    for step in range(16 * 16):
        chunk = audio[step * step_len : (step + 1) * step_len]
        if step and det.chord is not None:  # the engine asks at the start of the step
            now_chord, _ = tracker.update(step, det.chord)
            if step >= 12 * 16 and step % 16 < 2:  # the first two sixteenths of each bar in round four
                truth = names[(step // 16) % 4]
                starts += 1
                followed += str(det.chord) == truth
                predicted += str(now_chord) == truth
        for i in range(0, len(chunk), 512):
            det.feed(chunk[i : i + 512])
            now[0] += len(chunk[i : i + 512]) / SR
    assert tracker.loop_steps == 64
    assert followed == 0  # plain following is always late here
    assert starts == 8 and predicted >= 7


# ------------------------------------------------------------ changes of 2026-11-13


def _lead_notes(bars=32, seed=0, **ctx_kw):
    from elfjamalong.melody import Context

    gen = RuleBasedMelody(seed=seed, **{k: ctx_kw.pop(k) for k in ("answer",) if k in ctx_kw})
    chord, key = Chord.parse("C"), Key.parse("C major")
    out = []
    for step in range(bars * 16):
        kw = {k: (v(step) if callable(v) else v) for k, v in ctx_kw.items()}
        event = gen.step(Context(step, chord, key, **kw))
        if event:
            out.append((step, event))
    return out


def test_lead_plays_harder_and_busier_when_the_player_does():
    soft = [_lead_notes(seed=s, energy=0.0) for s in range(6)]
    hard = [_lead_notes(seed=s, energy=1.0) for s in range(6)]
    assert sum(map(len, hard)) > 1.3 * sum(map(len, soft))
    mean = lambda runs: np.mean([e.velocity for run in runs for _, e in run])
    assert mean(hard) > mean(soft) + 15


def test_answer_mode_stays_off_the_strums_and_fills_the_gaps():
    """The player strums on beats one and two of every bar and rests on three and four."""
    since = lambda step: float(step % 16 % 4) if step % 16 < 8 else float(step % 16 - 4)
    def halves(runs):
        first = sum(1 for run in runs for step, _ in run if 0 < step % 16 < 8 and step % 4 == 0)
        second = sum(1 for run in runs for step, _ in run if step % 16 >= 8)
        return first, second
    plain = halves([_lead_notes(seed=s, since_onset=since) for s in range(6)])
    answer = halves([_lead_notes(seed=s, since_onset=since, answer=True) for s in range(6)])
    assert answer[0] < 0.6 * plain[0]  # fewer notes on top of the strum on beat two
    assert answer[1] > 1.2 * plain[1]  # more in the half bar the player leaves empty


def test_detector_reports_energy_and_strum_onsets():
    now = [0.0]
    det = ChordDetector(SR, clock=lambda: now[0])
    quiet = 0.25 * np.concatenate([strum("Em", 1.0, SR, strums=2) for _ in range(6)])
    loud = np.concatenate([strum("Em", 1.0, SR, strums=2) for _ in range(2)])
    onsets = []
    for audio in (quiet, loud):
        for i in range(0, len(audio), 512):
            det.feed(audio[i : i + 512])
            now[0] += 512 / SR
            if det.since_onset() < 0.03:
                onsets.append(round(now[0] * 2) / 2)
        if audio is quiet:
            assert 0.35 < det.energy < 0.65  # playing at their usual level
    assert det.energy > 0.8  # four times louder than they have been
    assert len(set(onsets)) >= 12  # a strum every half second for eight seconds


def test_lead_approaches_a_known_next_chord():
    """The last note of a bar should sit a scale step from a tone of the chord that is coming."""
    f = Chord.parse("F")
    def last_notes(**kw):
        runs = [_lead_notes(seed=s, **kw) for s in range(12)]
        return [max((n for n in run if n[0] // 16 == bar), default=None) for run in runs for bar in range(32)]
    def approaching(notes):
        good = [n for n in notes if n and n[1].pitch % 12 not in f.pitch_classes
                and ({(n[1].pitch + d) % 12 for d in (-2, -1, 1, 2)} & f.pitch_classes)]
        return len(good) / len([n for n in notes if n])
    assert approaching(last_notes(next_chord=f)) > approaching(last_notes()) + 0.1


def test_calibration_finds_the_delay():
    from elfjamalong.calibrate import onset_delays, summary

    sent = [1.0 + 0.6 * i for i in range(8)]
    blocks = []
    t = 0.0
    while t < 7:
        level = 0.001
        for s in sent[:7]:  # the last note is never heard
            if s + 0.035 <= t < s + 0.12:
                level = 0.2
        blocks.append((t, level))
        t += 0.005
    delays = onset_delays(blocks, sent)
    assert len(delays) == 7 and all(0.03 <= d <= 0.045 for d in delays)
    assert "--offset-ms" in summary(delays, 8)[1]
    assert "heard only" in summary(onset_delays([(i * 0.01, 0.001) for i in range(500)], sent), 8)[0]


def test_presets_choose_roles(tmp_path):
    import mido

    from elfjamalong.cli import main

    out = tmp_path / "trio.mid"
    assert main(["render", "--preset", "trio", "--bars", "4", "-o", str(out)]) == 0
    assert [t.name for t in mido.MidiFile(out).tracks[1:]] == \
        ["ElfJamAlong lead", "ElfJamAlong bass", "ElfJamAlong arp", "Chords"]


@pytest.mark.parametrize("seed", range(4))
def test_learned_lead_keeps_the_rules_of_the_road(seed):
    """The trained lead must obey the same contract: in key, in range, monophonic, not silent."""
    from elfjamalong.engine import Voice
    from elfjamalong.learned import LearnedMelody

    chords = [Chord.parse(c) for c in "Am F C G".split()]
    key = Key.parse("C major")
    sink = Sink()
    bar = [0]
    eng = Engine([Voice("lead", LearnedMelody(seed=seed), sink)], lambda: (chords[bar[0] % 4], key))
    beat = 0.0
    while beat < 32 * 4:
        bar[0] = int(beat // 4)
        sink.t = beat
        eng.tick(beat)
        beat += 0.01
    eng.stop()
    assert sink.max_poly == 1 and not sink.sounding
    assert 80 < len(sink.on) < 32 * 16 * 0.8
    assert all(60 <= p <= 84 for _, p, _ in sink.on)
    assert all(p % 12 in key.pitch_classes for _, p, _ in sink.on)
    assert len({p for _, p, _ in sink.on}) >= 6
    leaps = [abs(b[1] - a[1]) for a, b in zip(sink.on, sink.on[1:])]
    assert np.mean(leaps) < 4.5 and max(leaps) <= 12


def test_learned_lead_follows_borrowed_chords_density_and_unknown_key():
    from elfjamalong.learned import LearnedMelody
    from elfjamalong.melody import Context

    def run(chord, key, **kw):
        gen = LearnedMelody(seed=1, **kw)
        return [e.pitch for s in range(32 * 16) if (e := gen.step(Context(s, Chord.parse(chord), key)))]

    assert all(p % 12 != 7 for p in run("E", Key.parse("A minor")))  # G# in, G out
    assert {p % 12 for p in run("Em", None)} <= {4, 7, 9, 11, 2}  # the chord's pentatonic
    assert len(run("C", None, density=0.9)) > 1.5 * len(run("C", None, density=0.2))


def test_link_audio_source_receives_a_channel():
    """Needs tools/linktap/build.sh to have been run; sends itself a tone over Link Audio."""
    import subprocess
    import time
    from pathlib import Path

    helper = Path(__file__).resolve().parents[1] / "tools" / "linktap" / "linktap"
    if not helper.exists():
        pytest.skip("linktap helper not built")
    from elfjamalong.cli import _LinkAudio

    sender = subprocess.Popen([str(helper), "--send-tone"], stderr=subprocess.DEVNULL)
    try:
        time.sleep(1.5)
        try:
            source = _LinkAudio("tone")
        except SystemExit as err:
            pytest.skip(f"Link peers cannot see each other on this machine: {err}")
        heard = []
        source.start(heard.append)
        time.sleep(1.5)
        source.close()
    finally:
        sender.terminate()
    audio = np.concatenate(heard)
    assert source.sample_rate == 48000 and "tone" in source.label
    assert len(audio) > 48000  # at least a second arrived
    spectrum = np.abs(np.fft.rfft(audio[:48000] * np.hanning(48000)))
    assert abs(int(spectrum.argmax()) - 440) <= 1


def test_dominant_seventh_brings_its_flat_seventh():
    key = Key.parse("A major")
    assert 8 in scale_for(Chord.parse("A"), key) and 7 not in scale_for(Chord.parse("A"), key)
    allowed = scale_for(Chord.parse("A7"), key)
    assert 7 in allowed and 8 not in allowed  # G natural replaces G sharp
    sink = play([Chord.parse("A7")], key, 16, seed=1)
    assert all(p % 12 != 8 for _, p, _ in sink.on)
    assert Chord.parse("A7").pitch_classes == Chord.parse("A").pitch_classes  # bass and arpeggio are unchanged


def test_chords_from_midi_notes():
    from types import SimpleNamespace as Msg

    from elfjamalong.midi_in import MidiChords, chord_from_notes

    spell = lambda *notes: str(chord_from_notes(notes))
    assert spell(48, 52, 55) == "C" and spell(52, 55, 60) == "C"  # root position and an inversion
    assert spell(45, 48, 52) == "Am" and spell(43, 47, 50, 53) == "G7"
    assert spell(48, 52, 55, 57) == "C" and spell(45, 52, 55, 60) == "Am"  # C6 or Am7: the bass decides
    assert chord_from_notes([48]) is None and chord_from_notes([48, 55]) is None  # no third, no guess

    now = [0.0]
    keys = MidiChords(clock=lambda: now[0])
    for name, notes in [("Am", (45, 48, 52)), ("F", (41, 45, 48)), ("C", (48, 52, 55)), ("G", (43, 47, 50))] * 2:
        for n in notes:
            keys.feed(Msg(type="note_on", note=n, velocity=70))
        assert str(keys.chord) == name and keys.active(4.0)
        now[0] += 2.0
        for n in notes:
            keys.feed(Msg(type="note_off", note=n, velocity=0))
    assert keys.key.pitch_classes == Key.parse("C major").pitch_classes
    assert keys.active(4.0)
    now[0] += 5.0
    assert not keys.active(4.0)  # hands off the keys for longer than the tail
    for n in (45, 48, 52):
        keys.feed(Msg(type="note_on", note=n, velocity=120))
    assert keys.energy > 0.7 and keys.since_onset() == 0.0


@pytest.mark.xfail(strict=True, reason="measured 2026-11-13: through the tap the trio's own sound hides whether the player stopped "
                   "(masked-energy share, level and model confidence are the same with and without the guitar). "
                   "Use --source link. Remove the mark when the detector can tell.")
def test_recorded_tap_goes_inactive_after_the_guitar_stops():
    """Recorded from Live through the tap with the trio audible: 26 s of the virtual guitar loop, then the
    clip stopped and 18 s more. After --tail (4 s) plus the clip's last bar and release, the detector
    should have stopped reporting a chord. Today it never does."""
    import json
    import mido

    sr, x = _load_wav_mono(_FIXTURES / "trio-tap-stop.wav")
    t_stop = json.loads((_FIXTURES / "trio-tap-stop.json").read_text())["t_stop"]
    events, _ = _own_note_events(_FIXTURES / "trio-tap-stop.mid")
    now = [0.0]
    det = ChordDetector(sr, clock=lambda: now[0])
    nxt, went_inactive = 0, None
    for i in range(0, len(x), 256):
        while nxt < len(events) and events[nxt][0] <= now[0]:
            _, is_on, pitch, cancel = events[nxt]
            det.own_note_on(pitch, cancel=cancel) if is_on else det.own_note_off(pitch)
            nxt += 1
        det.feed(x[i : i + 256])
        now[0] += 256 / sr
        if now[0] > t_stop and not det.active(4.0):
            went_inactive = now[0] - t_stop
            break
    assert went_inactive is not None and went_inactive < 12.0
