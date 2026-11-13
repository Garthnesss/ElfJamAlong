"""Small music-theory vocabulary shared by the detector and the melody generators."""

from __future__ import annotations

from dataclasses import dataclass, field

NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
_FLAT_TO_SHARP = {"DB": "C#", "EB": "D#", "GB": "F#", "AB": "G#", "BB": "A#"}

MAJOR_SCALE = (0, 2, 4, 5, 7, 9, 11)
MINOR_SCALE = (0, 2, 3, 5, 7, 8, 10)
MAJOR_PENTATONIC = (0, 2, 4, 7, 9)
MINOR_PENTATONIC = (0, 3, 5, 7, 10)

TRIADS = {"maj": (0, 4, 7), "min": (0, 3, 7)}


def parse_note(name: str) -> int:
    key = name.strip().upper()
    key = _FLAT_TO_SHARP.get(key, key)
    for i, n in enumerate(NOTE_NAMES):
        if n == key:
            return i
    raise ValueError(f"unknown note name: {name!r}")


@dataclass(frozen=True)
class Chord:
    root: int  # pitch class 0-11
    quality: str  # "maj" | "min"
    # A dominant seventh (G7). It colours the scale but is still "the G chord": two
    # chords that differ only in this are equal, so nothing that follows chords flickers.
    seventh: bool = field(default=False, compare=False)

    @property
    def pitch_classes(self) -> frozenset[int]:
        return frozenset((self.root + i) % 12 for i in TRIADS[self.quality])

    def __str__(self) -> str:
        return NOTE_NAMES[self.root] + ("m" if self.quality == "min" else "") + ("7" if self.seventh else "")

    @classmethod
    def parse(cls, text: str) -> "Chord":
        """'Am', 'F#', 'Bb'. Richer names land on their triad: 'G7' -> G, 'Dm7' -> Dm."""
        t = text.strip()
        root_len = 2 if len(t) > 1 and t[1] in "#b" else 1
        root, rest = parse_note(t[:root_len]), t[root_len:].lower()
        if rest.startswith(("dim", "aug", "+", "o")):
            raise ValueError(f"only major and minor chords are supported: {text!r}")
        minor = rest.startswith(("m", "-")) and not rest.startswith("maj")
        return cls(root, "min" if minor else "maj", seventh=rest in ("7", "9", "13"))


@dataclass(frozen=True)
class Key:
    tonic: int
    mode: str  # "major" | "minor"

    @property
    def pitch_classes(self) -> frozenset[int]:
        scale = MAJOR_SCALE if self.mode == "major" else MINOR_SCALE
        return frozenset((self.tonic + i) % 12 for i in scale)

    def __str__(self) -> str:
        return f"{NOTE_NAMES[self.tonic]} {self.mode}"

    @classmethod
    def parse(cls, text: str) -> "Key":
        parts = text.replace("-", " ").split()
        if len(parts) == 1 and parts[0].endswith("m"):
            return cls(parse_note(parts[0][:-1]), "minor")
        mode = "major"
        if len(parts) > 1:
            mode = "minor" if parts[1].lower().startswith("min") else "major"
        return cls(parse_note(parts[0]), mode)


def scale_for(chord: Chord, key: Key | None) -> frozenset[int]:
    """Pitch classes the melody may use right now.

    With a known key: the key's scale, bent so every chord tone is in it (a
    borrowed E major in A minor swaps G for G#; a dominant seventh adds its flat
    seventh). Without one: the chord's own
    pentatonic, which is safe over that chord whatever the key turns out to be.
    """
    if key is None:
        penta = MAJOR_PENTATONIC if chord.quality == "maj" else MINOR_PENTATONIC
        return frozenset((chord.root + i) % 12 for i in penta)
    pcs = set(key.pitch_classes)
    tones = set(chord.pitch_classes)
    if chord.seventh:  # a dominant seventh brings its flat seventh (A7 in A major: G, not G#)
        tones.add((chord.root + 10) % 12)
    for tone in sorted(tones):
        if tone not in pcs:
            pcs.discard((tone - 1) % 12)
            pcs.discard((tone + 1) % 12)
            pcs.add(tone)
    return frozenset(pcs | tones)
