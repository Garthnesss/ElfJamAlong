"""Keep what was just played: write it to a MIDI file and, if Live's bridge is up, into a clip."""

from __future__ import annotations

import json
import socket
from datetime import datetime
from pathlib import Path

import mido

from .engine import PlayedNote

TICKS = 480


def write_midi(notes: list[PlayedNote], bars: int, bpm: float, path: Path) -> None:
    mid = mido.MidiFile(ticks_per_beat=TICKS)
    mid.tracks.append(mido.MidiTrack([mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(bpm), time=0)]))
    for voice in sorted({n.voice for n in notes}):
        events = []
        for n in notes:
            if n.voice != voice:
                continue
            on = round(n.start_beat * TICKS)
            off = min(round((n.start_beat + n.length_beats) * TICKS), bars * 4 * TICKS)
            events.append((on, 1, mido.Message("note_on", note=n.pitch, velocity=n.velocity)))
            events.append((off, 0, mido.Message("note_off", note=n.pitch)))
        track = mido.MidiTrack([mido.MetaMessage("track_name", name=f"ElfJamAlong {voice}", time=0)])
        last = 0
        for tick, _, msg in sorted(events, key=lambda e: (e[0], e[1])):
            track.append(msg.copy(time=tick - last))
            last = tick
        mid.tracks.append(track)
    path.parent.mkdir(parents=True, exist_ok=True)
    mid.save(path)


# ---------------------------------------------------------------- Ableton Live


def _live(command: str, params: dict | None = None, port: int = 9877):
    """One request to the AbletonMCP remote script, if it is installed and Live is open."""
    with socket.create_connection(("localhost", port), timeout=3) as s:
        s.sendall(json.dumps({"type": command, "params": params or {}}).encode())
        buf = b""
        while True:
            chunk = s.recv(65536)
            if not chunk:
                break
            buf += chunk
            try:
                reply = json.loads(buf)
            except ValueError:
                continue
            if reply.get("status") != "success":
                raise RuntimeError(reply.get("message") or str(reply))
            return reply["result"]
    raise RuntimeError("no reply from Live")


def to_live_clip(notes: list[PlayedNote], bars: int, track_name: str, clip_name: str) -> str:
    """Put the notes in the first empty clip slot of the track called `track_name`."""
    count = _live("get_session_info")["track_count"]
    for index in range(count):
        info = _live("get_track_info", {"track_index": index})
        if info["name"] != track_name or not info["is_midi_track"]:
            continue
        slot = next((s["index"] for s in info["clip_slots"] if not s["has_clip"]), None)
        if slot is None:
            raise RuntimeError(f"no empty clip slot on '{track_name}'")
        where = {"track_index": index, "clip_index": slot}
        _live("create_clip", {**where, "length": float(bars * 4)})
        _live("add_notes_to_clip", {**where, "notes": [
            {"pitch": n.pitch, "start_time": n.start_beat, "duration": n.length_beats,
             "velocity": n.velocity, "mute": False}
            for n in notes
        ]})
        _live("set_clip_name", {**where, "name": clip_name})
        return f"track '{track_name}', slot {slot + 1}"
    raise RuntimeError(f"no MIDI track called '{track_name}'")


def capture(notes: list[PlayedNote], bars: int, bpm: float, label: str, folder: Path,
            live_track: str | None = "ElfJamAlong") -> list[str]:
    """Save a capture. Returns human-readable lines saying where it went."""
    if not notes:
        return ["nothing to capture yet"]
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    path = folder / f"{stamp}_{bars}bars.mid"
    write_midi(notes, bars, bpm, path)
    lines = [f"saved {len(notes)} notes, {bars} bars -> {path}"]
    if live_track:
        try:
            lines.append("also in Live: " + to_live_clip(notes, bars, live_track, f"Jam {stamp[11:]} {label}".strip()))
        except (OSError, RuntimeError, KeyError) as err:
            lines.append(f"(not added to Live: {err})")
    return lines
