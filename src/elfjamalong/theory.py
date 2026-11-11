"""Small music-theory vocabulary shared by the detector and the melody generators."""

from __future__ import annotations

from dataclasses import dataclass

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

    @property
    def pitch_classes(self) -> frozenset[int]:
        return frozenset((self.root + i) % 12 for i in TRIADS[self.quality])

    def __str__(self) -> str:
        return NOTE_NAMES[self.root] + ("m" if self.quality == "min" else "")

    @classmethod
    def parse(cls, text: str) -> "Chord":
        t = text.strip()
        if t.endswith("m") and not t.endswith("dim"):
            return cls(parse_note(t[:-1]), "min")
        return cls(parse_note(t), "maj")


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
    borrowed E major in A minor swaps G for G#). Without one: the chord's own
    pentatonic, which is safe over that chord whatever the key turns out to be.
    """
    if key is None:
        penta = MAJOR_PENTATONIC if chord.quality == "maj" else MINOR_PENTATONIC
        return frozenset((chord.root + i) % 12 for i in penta)
    pcs = set(key.pitch_classes)
    for tone in chord.pitch_classes:
        if tone not in pcs:
            pcs.discard((tone - 1) % 12)
            pcs.discard((tone + 1) % 12)
            pcs.add(tone)
    return frozenset(pcs | chord.pitch_classes)
