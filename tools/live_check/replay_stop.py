"""Replay a record.py recording through the detector; report how long it stays 'active' after the guitar stops.
usage: uv run python -I tools/live_check/replay_stop.py STEM [--tail 4]"""
import json, sys, wave
from pathlib import Path
import mido, numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from elfjamalong.chords import ChordDetector

stem = sys.argv[1]; tail = float(sys.argv[sys.argv.index("--tail") + 1]) if "--tail" in sys.argv else 4.0
meta = json.load(open(stem + ".json"))
with wave.open(stem + ".wav") as w:
    sr = w.getframerate(); x = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(np.float32) / 32768
mid = mido.MidiFile(stem + ".mid"); tempo = 0
events = []
for tr in mid.tracks:
    name, tick = "", 0
    for m in tr:
        tick += m.time
        if m.type == "set_tempo": tempo = m.tempo
        if m.type == "track_name": name = m.name
    if not name.startswith("ElfJamAlong"): continue
    tick = 0
    for m in tr:
        tick += m.time
        if m.type in ("note_on", "note_off"):
            events.append((tick, m.type == "note_on" and m.velocity > 0, m.note, "lead" in name))
spt = tempo / 1e6 / mid.ticks_per_beat
events = sorted([(t * spt, on, p, c) for t, on, p, c in events], key=lambda e: (e[0], e[1]))
now = [0.0]
det = ChordDetector(sr, clock=lambda: now[0])
nxt = 0; last_active = None; first_inactive_after = None; t_stop = meta["t_stop"]
for i in range(0, len(x), 256):
    while nxt < len(events) and events[nxt][0] <= now[0]:
        _, on, p, c = events[nxt]
        (det.own_note_on(p, cancel=c) if on else det.own_note_off(p)); nxt += 1
    det.feed(x[i:i + 256]); now[0] += 256 / sr
    if now[0] > t_stop and not det.active(tail) and first_inactive_after is None:
        first_inactive_after = now[0] - t_stop
play = [e for e in events if e[0] < t_stop]
print("audio %.1f s, guitar stopped at %.1f s, %d own note-ons before, %d after" % (len(x) / sr, t_stop, sum(e[1] for e in play), sum(e[1] for e in events if e[0] >= t_stop)))
print("detector went inactive %s s after the stop (tail %.1f)" % ("%.1f" % first_inactive_after if first_inactive_after is not None else "NEVER within the recording", tail))
