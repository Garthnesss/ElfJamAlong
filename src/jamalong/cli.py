"""Command line: `jamalong devices | run | demo | render | capture`."""

from __future__ import annotations

import argparse
import math
import os
import select
import signal
import subprocess
import sys
import tempfile
import threading
import tomllib
from pathlib import Path

import numpy as np

from .chords import ChordDetector, estimate_key
from .capture import capture
from .engine import Engine, Voice, run_realtime
from .melody import RuleBasedMelody
from .roles import Arpeggio, BassLine
from .theory import Chord, Key


PID_FILE = Path(tempfile.gettempdir()) / "jamalong.pid"
ROLES = ("lead", "bass", "arp")


def _generator(args) -> RuleBasedMelody:
    return RuleBasedMelody(low=args.low, high=args.high, density=args.density, seed=args.seed)


def _voices(args, midi, wrap=lambda sink, role: sink) -> list[Voice]:
    """One voice per requested role. All share a channel unless --split-channels."""
    roles = [r.strip() for r in args.roles.split(",") if r.strip()] if isinstance(args.roles, str) else list(args.roles)
    unknown = [r for r in roles if r not in ROLES]
    if unknown or not roles:
        raise SystemExit(f"--roles takes any of {', '.join(ROLES)}; got {args.roles!r}")
    makers = {
        "lead": lambda: _generator(args),
        "bass": lambda: BassLine(seed=args.seed),
        "arp": lambda: Arpeggio(seed=args.seed),
    }
    voices = []
    for role in roles:
        channel = args.channel + (ROLES.index(role) if args.split_channels else 0)
        voices.append(Voice(role, makers[role](), wrap(midi.on_channel(channel), role)))
    return voices


class _Capturer:
    """Capture on SIGUSR1 (`jamalong capture`) or when Enter is pressed in the terminal."""

    def __init__(self, engine: Engine, clock, args, label=lambda: ""):
        self.engine, self.clock, self.args, self.label = engine, clock, args, label
        self.requested = threading.Event()
        signal.signal(signal.SIGUSR1, lambda *_: self.requested.set())
        PID_FILE.write_text(str(os.getpid()))

    def poll(self) -> None:
        if sys.stdin and sys.stdin.isatty() and select.select([sys.stdin], [], [], 0)[0]:
            sys.stdin.readline()
            self.requested.set()
        if not self.requested.is_set():
            return
        self.requested.clear()
        notes, bars = self.engine.last_bars(self.args.capture_bars)
        if self.args.split_channels or self.args.no_live_clip:
            live_track = None
        else:
            live_track = self.args.live_track
        for line in capture(notes, bars, self.clock.tempo, self.label(), Path(self.args.capture_dir), live_track):
            print("  capture: " + line, flush=True)

    def close(self) -> None:
        PID_FILE.unlink(missing_ok=True)


def _clock(args):
    from .clock import InternalClock, LinkClock

    if args.no_link:
        print(f"Clock: internal, {args.bpm:g} BPM")
        return InternalClock(args.bpm)
    clock = LinkClock(args.bpm)
    print("Clock: Ableton Link (turn on Link in the DAW to share tempo and bar position)")
    return clock


def _key_of(chords: list[Chord]) -> Key | None:
    hist = np.zeros(12)
    for c in chords:
        for pc in c.pitch_classes:
            hist[pc] += 1
    return estimate_key(hist)


def _install_stop() -> threading.Event:
    stop = threading.Event()
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    return stop


# ------------------------------------------------------------------- commands


def cmd_devices(_args) -> int:
    import sounddevice as sd

    for i, d in enumerate(sd.query_devices()):
        if d["max_input_channels"] > 0:
            mark = "*" if i == sd.default.device[0] else " "
            print(f"{mark} {i:2d}  {d['name']}  ({d['max_input_channels']} in, {d['default_samplerate']:.0f} Hz)")
    return 0


class _LiveTap:
    """Audio straight from a running app's output, via the `livetap` helper (no driver)."""

    helper = Path(__file__).resolve().parents[2] / "tools" / "livetap" / "livetap"

    def __init__(self, bundle_id: str):
        if not self.helper.exists():
            raise SystemExit(f"livetap helper not built. Run: {self.helper.parent / 'build.sh'}")
        self.proc = subprocess.Popen([str(self.helper), bundle_id], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        line = self.proc.stderr.readline().decode().strip()
        if not line.startswith("rate="):
            rest = self.proc.stderr.read().decode().strip()
            raise SystemExit(f"{line} {rest}".strip() or "livetap failed to start")
        self.sample_rate = float(line.split("=")[1])
        self.label = f"{bundle_id} output (direct tap)"

    def start(self, feed) -> None:
        def pump():
            while chunk := self.proc.stdout.read(4096):
                feed(np.frombuffer(chunk[: len(chunk) // 4 * 4], dtype="<f4"))

        threading.Thread(target=pump, daemon=True).start()

    def close(self) -> None:
        self.proc.send_signal(signal.SIGINT)
        try:
            self.proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            self.proc.kill()


class _DeviceInput:
    """Audio from an input device: an interface, a microphone or a loopback device."""

    def __init__(self, device: str | None, channel: int):
        import sounddevice as sd

        self._sd = sd
        self.device = int(device) if device is not None and device.isdigit() else device
        info = sd.query_devices(self.device, "input")
        if channel > info["max_input_channels"]:
            raise SystemExit(f"{info['name']} has only {info['max_input_channels']} input channel(s)")
        self.channel = channel
        self.sample_rate = info["default_samplerate"]
        self.label = f"{info['name']} ch {channel}"

    def start(self, feed) -> None:
        ch = self.channel - 1
        self._stream = self._sd.InputStream(
            device=self.device, channels=self.channel, samplerate=self.sample_rate,
            callback=lambda indata, *_: feed(indata[:, ch]),
        )
        self._stream.start()

    def close(self) -> None:
        self._stream.stop()
        self._stream.close()


class _TellDetector:
    """Passes notes to the MIDI port and tells the detector which notes are ours."""

    def __init__(self, sink, detector: ChordDetector, cancel: bool):
        self.sink, self.detector, self.cancel = sink, detector, cancel

    def note_on(self, pitch: int, velocity: int) -> None:
        self.detector.own_note_on(pitch, self.cancel)
        self.sink.note_on(pitch, velocity)

    def note_off(self, pitch: int) -> None:
        self.detector.own_note_off(pitch)
        self.sink.note_off(pitch)


def cmd_run(args) -> int:
    from .midi_out import MidiOut

    source = _LiveTap(args.app) if args.source == "live" else _DeviceInput(args.device, args.input_channel)
    detector = ChordDetector(
        source.sample_rate, gate_db=args.gate_db, fixed_key=Key.parse(args.key) if args.key else None
    )
    clock = _clock(args)
    midi = MidiOut(channel=args.channel)

    def harmony():
        if args.follow_transport and not clock.playing:
            return None
        if not detector.active(args.tail):
            return None
        return detector.chord, detector.key

    engine = Engine(_voices(args, midi, lambda sink, role: _TellDetector(sink, detector, role == "lead")), harmony)
    stop = _install_stop()
    capturer = _Capturer(engine, clock, args, lambda: str(detector.key or ""))
    print(f"Listening: {source.label} @ {source.sample_rate:.0f} Hz")
    print(f"MIDI out:  virtual port 'JamAlong', channel {args.channel}, roles: {args.roles}")
    print(f"Press Enter to keep the last {args.capture_bars} bars.  Ctrl-C to quit.", flush=True)

    def status():
        shown = None
        while not stop.wait(0.2):
            capturer.poll()
            now = (str(detector.chord) if detector.active(args.tail) else "-", str(detector.key or "?"))
            if now != shown:
                shown = now
                print(f"  chord {now[0]:<4} key {now[1]:<9} {clock.tempo:6.1f} BPM  link peers {clock.peers}", flush=True)

    threading.Thread(target=status, daemon=True).start()
    source.start(detector.feed)
    try:
        run_realtime(engine, clock, stop, args.offset_ms)
    finally:
        capturer.close()
        source.close()
        midi.close()
    return 0


def cmd_demo(args) -> int:
    """No audio input: loop a typed progression so MIDI routing can be checked."""
    from .midi_out import MidiOut

    chords = [Chord.parse(c) for c in args.chords.split()]
    key = Key.parse(args.key) if args.key else _key_of(chords)
    clock = _clock(args)
    midi = MidiOut(channel=args.channel)

    def harmony():
        bar = math.floor(clock.beat() / 4)
        return chords[bar % len(chords)], key

    engine = Engine(_voices(args, midi), harmony)
    stop = _install_stop()
    capturer = _Capturer(engine, clock, args, lambda: str(key or ""))
    print(f"Demo: {' | '.join(map(str, chords))}  (key {key}), roles: {args.roles}.  MIDI on port 'JamAlong'.")
    print(f"Press Enter to keep the last {args.capture_bars} bars.  Ctrl-C to quit.", flush=True)

    def watch():
        while not stop.wait(0.2):
            capturer.poll()

    threading.Thread(target=watch, daemon=True).start()
    try:
        run_realtime(engine, clock, stop, args.offset_ms)
    finally:
        capturer.close()
        midi.close()
    return 0


def cmd_capture(_args) -> int:
    """Ask the running JamAlong to keep what it just played."""
    try:
        os.kill(int(PID_FILE.read_text()), signal.SIGUSR1)
    except (FileNotFoundError, ValueError, ProcessLookupError):
        print("JamAlong is not running", file=sys.stderr)
        return 1
    print("capture requested")
    return 0


def cmd_render(args) -> int:
    """Offline: write the melody (and the chords, on a second track) to a MIDI file."""
    import mido

    chords = [Chord.parse(c) for c in args.chords.split()]
    key = Key.parse(args.key) if args.key else _key_of(chords)
    tpb = 480
    events: list[tuple[int, mido.Message]] = []

    class Sink:
        now = 0

        def note_on(self, pitch, velocity):
            events.append((self.now, mido.Message("note_on", note=pitch, velocity=velocity)))

        def note_off(self, pitch):
            events.append((self.now, mido.Message("note_off", note=pitch)))

    sink = Sink()
    position = {"bar": 0}
    engine = Engine(_generator(args), sink, lambda: (chords[position["bar"] % len(chords)], key))
    ticks_total = args.bars * 4 * tpb
    for tick in range(0, ticks_total, 10):
        position["bar"] = tick // (4 * tpb)
        sink.now = tick
        engine.tick(tick / tpb)
    sink.now = ticks_total
    engine.stop()

    def to_track(evts, name):
        track = mido.MidiTrack()
        track.append(mido.MetaMessage("track_name", name=name, time=0))
        last = 0
        for t, msg in sorted(evts, key=lambda e: (e[0], e[1].type == "note_on")):
            track.append(msg.copy(time=t - last))
            last = t
        return track

    chord_events = []
    for bar in range(args.bars):
        c = chords[bar % len(chords)]
        notes = [48 + c.root] + [60 + (pc - 0) % 12 for pc in sorted(c.pitch_classes)]
        for n in notes:
            chord_events.append((bar * 4 * tpb, mido.Message("note_on", note=n, velocity=60, channel=1)))
            chord_events.append(((bar + 1) * 4 * tpb - 10, mido.Message("note_off", note=n, channel=1)))

    mid = mido.MidiFile(ticks_per_beat=tpb)
    tempo_track = mido.MidiTrack([mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(args.bpm), time=0)])
    mid.tracks.extend([tempo_track, to_track(events, "JamAlong melody"), to_track(chord_events, "Chords")])
    mid.save(args.output)
    notes = sum(1 for _, m in events if m.type == "note_on")
    print(f"Wrote {args.output}: {args.bars} bars, {notes} melody notes, key {key}")
    return 0


# ----------------------------------------------------------------------- main


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="jamalong", description="Plays a melody along with your guitar chords.")
    sub = p.add_subparsers(dest="command", required=True)

    def melody_opts(sp):
        sp.add_argument("--key", help="lock the key, e.g. 'A minor' or 'G' (default: detect)")
        sp.add_argument("--density", type=float, default=0.5, help="how busy the melody is, 0.05-1 (default 0.5)")
        sp.add_argument("--low", type=int, default=60, help="lowest MIDI note (default 60 = C4 / Ableton C3)")
        sp.add_argument("--high", type=int, default=84, help="highest MIDI note (default 84)")
        sp.add_argument("--seed", type=int, help="fix the random seed for repeatable output")
        sp.add_argument("--bpm", type=float, default=120.0, help="tempo when not synced (default 120)")

    def live_opts(sp):
        sp.add_argument("--roles", default="lead", help="comma list of lead, bass, arp (default lead)")
        sp.add_argument("--split-channels", action="store_true",
                        help="send lead/bass/arp on channels N, N+1, N+2 instead of all on one")
        sp.add_argument("--capture-bars", type=int, default=8, help="bars kept by a capture (default 8)")
        sp.add_argument("--capture-dir", default="captures", help="folder for captured MIDI files")
        sp.add_argument("--live-track", default="JamAlong", help="Live track that receives captured clips")
        sp.add_argument("--no-live-clip", action="store_true", help="capture to a file only")
        sp.add_argument("--no-link", action="store_true", help="use an internal clock instead of Ableton Link")
        sp.add_argument("--channel", type=int, default=1, help="MIDI channel 1-16 (default 1)")
        sp.add_argument("--offset-ms", type=float, default=0.0, help="play this many ms early to cancel latency")

    sub.add_parser("devices", help="list audio inputs").set_defaults(fn=cmd_devices)

    run = sub.add_parser("run", help="listen to the guitar and play along")
    run.add_argument("--source", choices=["device", "live"], default="device",
                     help="'device' = an audio input; 'live' = tap a running app's output directly, no driver")
    run.add_argument("--app", default="com.ableton.live", help="bundle id to tap with --source live")
    run.add_argument("--device", help="audio input: index or name from `jamalong devices` (default: system input)")
    run.add_argument("--input-channel", type=int, default=1, help="which input channel the guitar is on (default 1)")
    run.add_argument("--gate-db", type=float, default=-50.0, help="ignore input quieter than this (default -50 dBFS)")
    run.add_argument("--tail", type=float, default=4.0, help="keep playing this many seconds after you stop (default 4)")
    run.add_argument("--follow-transport", action="store_true",
                     help="only play while the DAW is playing (needs Link Start Stop Sync)")
    melody_opts(run)
    live_opts(run)
    run.set_defaults(fn=cmd_run)

    demo = sub.add_parser("demo", help="no guitar: loop a typed chord progression over MIDI")
    demo.add_argument("--chords", default="Am F C G", help="one chord per bar (default 'Am F C G')")
    melody_opts(demo)
    live_opts(demo)
    demo.set_defaults(fn=cmd_demo)

    render = sub.add_parser("render", help="write a melody for a typed progression to a MIDI file")
    render.add_argument("--chords", default="Am F C G")
    render.add_argument("--bars", type=int, default=16)
    render.add_argument("-o", "--output", default="jamalong.mid")
    melody_opts(render)
    render.set_defaults(fn=cmd_render)

    sub.add_parser("capture", help="keep the last bars the running JamAlong played").set_defaults(fn=cmd_capture)

    # Saved settings: ./jamalong.toml, e.g.  [run]  source = "live"  roles = "lead,bass"
    config = Path("jamalong.toml")
    if config.exists():
        saved = tomllib.loads(config.read_text())
        for name, parser in (("run", run), ("demo", demo), ("render", render)):
            parser.set_defaults(**{k.replace("-", "_"): v for k, v in saved.get(name, {}).items()})

    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
