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
