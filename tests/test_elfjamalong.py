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
        ["G", "Dm", "C", "A#", "F#m", "A", "D#m"]
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
