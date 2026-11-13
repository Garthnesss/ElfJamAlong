"""Run `elfjamalong run` against Live with the virtual-guitar clip, log what it hears against the truth.

usage: uv run python -I tools/live_check/measure.py OUT.json [--run-args "..."] [--seconds N] [--stop-after N] [--tail N]
Needs Live open with Link on, the clip at track 4 slot 0, the AbletonMCP bridge on 9877.
"""
import argparse, json, math, re, socket, subprocess, sys, threading, time

TRUTH = "Am Dm G C F Dm E Am".split()


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
    ap.add_argument("out")
    ap.add_argument("--run-args", default="--preset trio --split-channels")
    ap.add_argument("--seconds", type=float, default=50)   # clip plays this long
    ap.add_argument("--tail", type=float, default=12)       # watch this long after stopping it
    ap.add_argument("--track", type=int, default=4)
    ap.add_argument("--clip", type=int, default=0)
    a = ap.parse_args()

    cmd = ["uv", "run", "elfjamalong", "run"] + a.run_args.split()
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, cwd=__import__("os").path.dirname(__import__("os").path.dirname(__import__("os").path.dirname(__import__("os").path.abspath(__file__)))))
    heard, raw = [], []
    stop = threading.Event()

    def reader():
        buf = b""
        while not stop.is_set():
            c = p.stdout.read(1)
            if not c:
                break
            if c in b"\r\n":
                if buf:
                    line = buf.decode("utf8", "replace")
                    t = time.time()
                    raw.append((t, line))
                    m = re.search(r"chord (\S+)\s+key (.+?)\s{2,}", line)
                    if m:
                        heard.append((t, m.group(1), m.group(2).strip()))
                buf = b""
            else:
                buf += c
    th = threading.Thread(target=reader, daemon=True)
    th.start()
    time.sleep(5)
    import mido
    midi = []
    name = next((n for n in mido.get_input_names() if "ElfJamAlong" in n), None)
    if name:
        inp = mido.open_input(name)
        def mreader():
            while not stop.is_set():
                for m in inp.iter_pending():
                    if m.type in ("note_on", "note_off"):
                        midi.append((time.time(), m.type if m.velocity else "note_off", m.note, m.velocity, m.channel))
                time.sleep(0.001)
        threading.Thread(target=mreader, daemon=True).start()
    else:
        print("no ElfJamAlong MIDI input found", mido.get_input_names())
    time.sleep(1)

    samples = []  # (wall, song_time, playing)

    def poll():
        r = bridge("get_session_info")
        t = time.time()
        if r and "result" in r:
            res = r["result"]
            samples.append((t, res.get("current_song_time"), res.get("is_playing")))

    poll()
    t_fire = time.time()
    poll()
    fire_song = samples[-1][1]
    bridge("fire_clip", {"track_index": a.track, "clip_index": a.clip})
    t_end_play = t_fire + a.seconds
    while time.time() < t_end_play:
        poll(); time.sleep(0.5)
    t_stop = time.time()
    bridge("stop_clip", {"track_index": a.track, "clip_index": a.clip})
    t_end = t_stop + a.tail
    while time.time() < t_end:
        poll(); time.sleep(0.5)
    stop.set()
    p.terminate()
    json.dump({"heard": heard, "samples": samples, "t_fire": t_fire, "fire_song": fire_song,
               "t_stop": t_stop, "midi": midi, "raw_tail": raw[-5:], "raw_head": raw[:5], "args": a.run_args}, open(a.out, "w"))
    print("wrote", a.out, "heard", len(heard), "samples", len(samples))


main()
