"""MIDI output: a virtual port the DAW sees as an input device."""

from __future__ import annotations

import mido

PORT_NAME = "ElfJamAlong"


class MidiOut:
    def __init__(self, port_name: str = PORT_NAME, channel: int = 1):
        self.channel = channel - 1
        self._port = mido.open_output(port_name, virtual=True)

    def note_on(self, pitch: int, velocity: int) -> None:
        self._port.send(mido.Message("note_on", note=pitch, velocity=velocity, channel=self.channel))

    def note_off(self, pitch: int) -> None:
        self._port.send(mido.Message("note_off", note=pitch, channel=self.channel))

    def close(self) -> None:
        for channel in range(16):  # roles may be on other channels (--split-channels)
            self._port.send(mido.Message("control_change", control=123, value=0, channel=channel))
        self._port.close()

    def on_channel(self, channel: int) -> "ChannelSink":
        return ChannelSink(self._port, channel - 1)


class ChannelSink:
    """The same port, bound to one MIDI channel (so each role can have its own)."""

    def __init__(self, port, channel: int):
        self._port, self.channel = port, channel

    def note_on(self, pitch: int, velocity: int) -> None:
        self._port.send(mido.Message("note_on", note=pitch, velocity=velocity, channel=self.channel))

    def note_off(self, pitch: int) -> None:
        self._port.send(mido.Message("note_off", note=pitch, channel=self.channel))
