"""Record what the tap hears while ElfJamAlong plays along, plus the notes it sent (a fixture).

usage: uv run python -I tools/live_check/record.py OUT_STEM [--play 24] [--after 18] [--run-args "..."]

Writes OUT_STEM.wav (mono 16-bit, the tap's rate) and OUT_STEM.mid (the notes ElfJamAlong
played, tracks "ElfJamAlong lead/bass/arp", times counted from the first audio sample).
Starts `elfjamalong run`, fires the clip on track 4 slot 0 through the AbletonMCP bridge, stops
it after --play seconds and keeps recording for --after seconds. Needs Live open with Link on,
the ElfJamAlong track audible, and the guitar clip's track NOT armed with MIDI From "All Ins".
"""
import argparse, json, socket, subprocess, sys, threading, time, wave
from pathlib import Path

import mido
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from elfjamalong.capture import midi_file  # noqa: E402
from elfjamalong.engine import PlayedNote  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
VOICES = {0: "lead", 1: "bass", 2: "arp"}


def bridge(command, params=None):
    s = socket.create_connection(("localhost", 9877), timeout=3)
    s.sendall(json.dumps({"type": command, "params": params or {}}).encode())
    buf = b""
    while True:
        try:
            d = s.recv(65536)
        except socket.timeout:
            break
        if not d:
            break
        buf += d
        try:
            r = json.loads(buf)
            s.close()
            return r
        except ValueError:
            continue
    s.close()
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("stem")
    ap.add_argument("--play", type=float, default=24)
    ap.add_argument("--after", type=float, default=18)
    ap.add_argument("--run-args", default="--preset trio --split-channels")
    a = ap.parse_args()

    run = subprocess.Popen(["uv", "run", "elfjamalong", "run"] + a.run_args.split(), stdin=subprocess.PIPE,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, cwd=ROOT)
    time.sleep(6)
    tap = subprocess.Popen([str(ROOT / "tools/livetap/livetap")], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    rate = None
    while True:
        line = tap.stderr.readline().decode().strip()
        if line.startswith("rate="):
            rate = float(line.split("=")[1])
            break
        if not line:
            sys.exit("livetap failed")
    chunks, notes = [], []
    state = {"t0": None, "n": 0}
    stop = threading.Event()

    def pump():
        while not stop.is_set():
            data = tap.stdout.read(4096)
            if not data:
                break
            if state["t0"] is None:
                state["t0"] = time.time()
            arr = np.frombuffer(data[: len(data) // 4 * 4], dtype="<f4")
            chunks.append(arr)
            state["n"] += len(arr)

    threading.Thread(target=pump, daemon=True).start()
    name = next(n for n in mido.get_input_names() if "ElfJamAlong" in n)
    inp = mido.open_input(name)

    def midi_reader():
        while not stop.is_set():
            for m in inp.iter_pending():
                if m.type in ("note_on", "note_off") and state["t0"] is not None:
                    # audio time of "now": samples received so far (the pipe adds a little delay)
                    notes.append((state["n"] / rate, m.type if m.velocity else "note_off", m.note, m.velocity, m.channel))
            time.sleep(0.001)

    threading.Thread(target=midi_reader, daemon=True).start()
    time.sleep(1)
    bridge("fire_clip", {"track_index": 4, "clip_index": 0})
    time.sleep(a.play)
    bridge("stop_clip", {"track_index": 4, "clip_index": 0})
    t_stop_audio = state["n"] / rate
    time.sleep(a.after)
    stop.set()
    tap.terminate()
    run.terminate()

    audio = np.concatenate(chunks)
    with wave.open(a.stem + ".wav", "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(int(rate))
        w.writeframes((np.clip(audio, -1, 1) * 32767).astype("<i2").tobytes())
    bpm = 117.0
    played, open_ = [], {}
    for t, kind, pitch, vel, ch in notes:
        key = (ch, pitch)
        if kind == "note_on":
            open_[key] = (t, vel)
        elif key in open_:
            t0, v = open_.pop(key)
            played.append(PlayedNote(VOICES.get(ch, "lead"), t0 * bpm / 60, pitch, v, (t - t0) * bpm / 60))
    for (ch, pitch), (t0, v) in open_.items():
        played.append(PlayedNote(VOICES.get(ch, "lead"), t0 * bpm / 60, pitch, v, (len(audio) / rate - t0) * bpm / 60))
    end_beats = len(audio) / rate * bpm / 60
    bars = int(end_beats // 4) + 1
    midi_file(played, bars, bpm, order=["lead", "bass", "arp"]).save(a.stem + ".mid")
    json.dump({"rate": rate, "t_stop": t_stop_audio, "seconds": len(audio) / rate, "bpm": bpm}, open(a.stem + ".json", "w"))
    print("wrote", a.stem, "audio %.1f s, clip stopped at %.1f s, %d notes" % (len(audio) / rate, t_stop_audio, len(played)))


main()
