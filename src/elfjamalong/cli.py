"""Command line: `elfjamalong devices | run | demo | render | capture | calibrate`."""

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


PID_FILE = Path(tempfile.gettempdir()) / "elfjamalong.pid"
ROLES = ("lead", "bass", "arp")


PRESETS = {"solo": "lead", "duo": "lead,bass", "trio": "lead,bass,arp"}


def _generator(args):
    if getattr(args, "lead", "rules") == "model":
        from .learned import LearnedMelody

        return LearnedMelody(low=args.low, high=args.high, density=args.density, seed=args.seed)
    return RuleBasedMelody(low=args.low, high=args.high, density=args.density, seed=args.seed,
                           answer=getattr(args, "feel", "follow") == "answer")


def _roles(args) -> list[str]:
    if getattr(args, "preset", None):
        args.roles = PRESETS[args.preset]
    roles = [r.strip() for r in args.roles.split(",") if r.strip()] if isinstance(args.roles, str) else list(args.roles)
    unknown = [r for r in roles if r not in ROLES]
    if unknown or not roles:
        raise SystemExit(f"--roles takes any of {', '.join(ROLES)}; got {args.roles!r}")
    return roles


def _makers(args) -> dict:
    return {
        "lead": lambda: _generator(args),
        "bass": lambda: BassLine(seed=args.seed),
        "arp": lambda: Arpeggio(seed=args.seed),
    }


def _voices(args, midi, wrap=lambda sink, role: sink) -> list[Voice]:
    """One voice per requested role. All share a channel unless --split-channels."""
    makers = _makers(args)
    voices = []
    for role in _roles(args):
        channel = args.channel + (ROLES.index(role) if args.split_channels else 0)
        voices.append(Voice(role, makers[role](), wrap(midi.on_channel(channel), role)))
    return voices


class _Capturer:
    """Capture on SIGUSR1 (`elfjamalong capture`) or when Enter is pressed in the terminal."""

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
    try:
        import sounddevice as sd

        for i, d in enumerate(sd.query_devices()):
            if d["max_input_channels"] > 0:
                mark = "*" if i == sd.default.device[0] else " "
                print(f"{mark} {i:2d}  {d['name']}  ({d['max_input_channels']} in, {d['default_samplerate']:.0f} Hz)")
    except OSError as err:  # no audio system on this machine
        print(f"(no audio inputs: {err})")
    linktap = _HelperSource.tools / "linktap" / "linktap"
    if linktap.exists():
        print("Link Audio channels (use with --source link --link-channel <name>):")
        found = subprocess.run([str(linktap), "--list"], capture_output=True, text=True).stdout.split("\n")
        for name in filter(None, found):
            print(f"     {name}")
        if not any(found):
            print("     none (enable Link Audio in the sending app)")
    return 0


class _HelperSource:
    """Audio from a helper program that writes mono float32 PCM to stdout and "rate=<hz>" to stderr."""

    tools = Path(__file__).resolve().parents[2] / "tools"

    def __init__(self, helper: Path, argument: str, label: str):
        if not helper.exists():
            raise SystemExit(f"{helper.name} helper not built. Run: {helper.parent / 'build.sh'}")
        self.proc = subprocess.Popen([str(helper), argument] if argument else [str(helper)],
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.label = label
        while True:  # lines before "rate=" describe what was found, e.g. "channel=Live/Guitar"
            line = self.proc.stderr.readline().decode().strip()
            if line.startswith("rate="):
                break
            if line.startswith("channel="):
                self.label = f"Link Audio channel {line.split('=', 1)[1]}"
                continue
            rest = self.proc.stderr.read().decode().strip()
            raise SystemExit(f"{line} {rest}".strip() or f"{helper.name} failed to start")
        self.sample_rate = float(line.split("=")[1])

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


def _LiveTap(bundle_id: str) -> _HelperSource:
    """Audio straight from a running app's output, via the `livetap` helper (no driver, macOS)."""
    return _HelperSource(_HelperSource.tools / "livetap" / "livetap", bundle_id, f"{bundle_id} output (direct tap)")


def _LinkAudio(channel: str) -> _HelperSource:
    """One Link Audio channel (e.g. a single track sent from Live 12.4+), via the `linktap` helper."""
    return _HelperSource(_HelperSource.tools / "linktap" / "linktap", channel, "Link Audio")


class _MidiInput:
    """Chords played on a MIDI keyboard or sent from a MIDI track."""

    def __init__(self, port: str | None):
        import mido

        names = mido.get_input_names()
        matches = [n for n in names if port is None or port.lower() in n.lower()]
        matches = [n for n in matches if "ElfJamAlong" not in n] or matches
        if not matches:
            raise SystemExit(f"no MIDI input{f' matching {port!r}' if port else ''}; available: {', '.join(names) or 'none'}")
        self._mido, self.name = mido, matches[0]
        self.sample_rate = 0.0
        self.label = f"MIDI input '{self.name}'"

    def start(self, feed) -> None:
        self._port = self._mido.open_input(self.name, callback=feed)

    def close(self) -> None:
        self._port.close()


def _source(args):
    if args.source == "midi":
        return _MidiInput(args.midi_in)
    if args.source == "live":
        return _LiveTap(args.app)
    if args.source == "link":
        return _LinkAudio(args.link_channel)
    return _DeviceInput(args.device, args.input_channel)


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

    source = _source(args)
    fixed_key = Key.parse(args.key) if args.key else None
    if args.source == "midi":
        from .midi_in import MidiChords

        detector = MidiChords(fixed_key)
    else:
        detector = ChordDetector(source.sample_rate, gate_db=args.gate_db, fixed_key=fixed_key)
    clock = _clock(args)
    midi = MidiOut(channel=args.channel)

    def harmony():
        if args.follow_transport and not clock.playing:
            return None
        if not detector.active(args.tail):
            return None
        return detector.chord, detector.key

    tracker = None
    if args.predict:
        from .loop import ProgressionTracker

        tracker = ProgressionTracker(lambda: clock.tempo)
    def feel():
        if args.feel == "off":
            return 0.5, None
        return detector.energy, detector.since_onset() * clock.tempo / 60 * 4

    engine = Engine(_voices(args, midi, lambda sink, role: _TellDetector(sink, detector, role == "lead")), harmony,
                    tracker=tracker, feel=feel)
    stop = _install_stop()
    capturer = _Capturer(engine, clock, args, lambda: str(detector.key or ""))
    print(f"Listening: {source.label}" + (f" @ {source.sample_rate:.0f} Hz" if source.sample_rate else ""))
    print(f"MIDI out:  virtual port 'ElfJamAlong', channel {args.channel}, roles: {args.roles}")
    print(f"Press Enter to keep the last {args.capture_bars} bars.  Ctrl-C to quit.", flush=True)

    def status():
        shown = None
        while not stop.wait(0.2):
            capturer.poll()
            loop = f"loop {tracker.loop_steps // 16} bars" if tracker and tracker.loop_steps else ""
            now = (str(detector.chord) if detector.active(args.tail) else "-", str(detector.key or "?"), loop)
            if now != shown:
                shown = now
                print(f"  chord {now[0]:<4} key {now[1]:<9} {clock.tempo:6.1f} BPM  link peers {clock.peers}  {loop}", flush=True)

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
    print(f"Demo: {' | '.join(map(str, chords))}  (key {key}), roles: {args.roles}.  MIDI on port 'ElfJamAlong'.")
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


def cmd_calibrate(args) -> int:
    """Send short notes, listen for them coming back, and suggest an --offset-ms."""
    import time

    from .calibrate import onset_delays, summary
    from .midi_out import MidiOut

    source = _source(args)
    midi = MidiOut(channel=args.channel)
    blocks: list[tuple[float, float]] = []
    source.start(lambda block: blocks.append((time.monotonic(), float(np.sqrt(np.mean(np.square(block)))))))
    print(f"Listening: {source.label}.  MIDI out: 'ElfJamAlong', channel {args.channel}.")
    print("Use a sound with a sharp attack on the ElfJamAlong track, and keep everything else quiet.")
    input("Press Enter when the track is audible...")
    sent = []
    try:
        time.sleep(0.5)
        for _ in range(args.notes):
            sent.append(time.monotonic())
            midi.note_on(args.note, 110)
            time.sleep(0.08)
            midi.note_off(args.note)
            time.sleep(0.52)
        time.sleep(0.3)
    finally:
        source.close()
        midi.close()
    for line in summary(onset_delays(list(blocks), sent), args.notes):
        print(line)
    return 0


def cmd_capture(_args) -> int:
    """Ask the running ElfJamAlong to keep what it just played."""
    try:
        os.kill(int(PID_FILE.read_text()), signal.SIGUSR1)
    except (FileNotFoundError, ValueError, ProcessLookupError):
        print("ElfJamAlong is not running", file=sys.stderr)
        return 1
    print("capture requested")
    return 0


def cmd_render(args) -> int:
    """Offline: write what each role plays (and the chords, on a last track) to a MIDI file."""
    import mido

    from .capture import TICKS, midi_file

    chords = [Chord.parse(c) for c in args.chords.split()]
    key = Key.parse(args.key) if args.key else _key_of(chords)

    class Null:
        def note_on(self, pitch, velocity): ...
        def note_off(self, pitch): ...

    makers = _makers(args)
    voices = [Voice(role, makers[role](), Null()) for role in _roles(args)]
    position = {"bar": 0}
    engine = Engine(voices, lambda: (chords[position["bar"] % len(chords)], key), history_bars=args.bars + 1)
    for tick in range(0, args.bars * 4 * TICKS, 10):
        position["bar"] = tick // (4 * TICKS)
        engine.tick(tick / TICKS)
    engine.stop()
    notes = list(engine.history)

    mid = midi_file(notes, args.bars, args.bpm, order=_roles(args))
    track = mido.MidiTrack([mido.MetaMessage("track_name", name="Chords", time=0)])
    bar_ticks = 4 * TICKS
    for bar in range(args.bars):
        c = chords[bar % len(chords)]
        pitches = [48 + c.root] + [60 + pc for pc in sorted(c.pitch_classes)]
        for i, n in enumerate(pitches):
            track.append(mido.Message("note_on", note=n, velocity=60, channel=15, time=10 if bar and i == 0 else 0))
        for i, n in enumerate(pitches):
            track.append(mido.Message("note_off", note=n, channel=15, time=bar_ticks - 10 if i == 0 else 0))
    mid.tracks.append(track)
    mid.save(args.output)
    counts = ", ".join(f"{sum(n.voice == r for n in notes)} {r}" for r in _roles(args))
    print(f"Wrote {args.output}: {args.bars} bars, {counts} notes, key {key}")
    return 0


# ----------------------------------------------------------------------- main


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="elfjamalong", description="Plays a melody along with your guitar chords.")
    sub = p.add_subparsers(dest="command", required=True)

    def melody_opts(sp):
        sp.add_argument("--key", help="lock the key, e.g. 'A minor' or 'G' (default: detect)")
        sp.add_argument("--density", type=float, default=0.5, help="how busy the melody is, 0.05-1 (default 0.5)")
        sp.add_argument("--low", type=int, default=60, help="lowest MIDI note (default 60 = C4 / Ableton C3)")
        sp.add_argument("--high", type=int, default=84, help="highest MIDI note (default 84)")
        sp.add_argument("--seed", type=int, help="fix the random seed for repeatable output")
        sp.add_argument("--bpm", type=float, default=120.0, help="tempo when not synced (default 120)")
        sp.add_argument("--lead", choices=["rules", "model"], default="rules",
                        help="who plays the lead: the rules (default) or the model trained on guitar solos")

    def live_opts(sp):
        sp.add_argument("--roles", default="lead", help="comma list of lead, bass, arp (default lead)")
        sp.add_argument("--preset", choices=sorted(PRESETS), help="solo = lead; duo = lead,bass; trio = lead,bass,arp")
        sp.add_argument("--split-channels", action="store_true",
                        help="send lead/bass/arp on channels N, N+1, N+2 instead of all on one")
        sp.add_argument("--capture-bars", type=int, default=8, help="bars kept by a capture (default 8)")
        sp.add_argument("--capture-dir", default="captures", help="folder for captured MIDI files")
        sp.add_argument("--live-track", default="ElfJamAlong", help="Live track that receives captured clips")
        sp.add_argument("--no-live-clip", action="store_true", help="capture to a file only")
        sp.add_argument("--no-link", action="store_true", help="use an internal clock instead of Ableton Link")
        sp.add_argument("--channel", type=int, default=1, help="MIDI channel 1-16 (default 1)")
        sp.add_argument("--offset-ms", type=float, default=0.0, help="play this many ms early to cancel latency")

    sub.add_parser("devices", help="list audio inputs").set_defaults(fn=cmd_devices)

    run = sub.add_parser("run", help="listen to the guitar and play along")
    run.add_argument("--source", choices=["device", "live", "link", "midi"], default="device",
                     help="'device' = an audio input; 'live' = tap a running app's output directly, no driver; "
                          "'link' = receive a Link Audio channel; 'midi' = chords from a MIDI keyboard")
    run.add_argument("--midi-in", metavar="TEXT", help="with --source midi: part of the MIDI input's name")
    run.add_argument("--app", default="com.ableton.live", help="bundle id to tap with --source live")
    run.add_argument("--link-channel", default="", metavar="TEXT",
                     help="with --source link: part of the channel's name (default: the first channel found)")
    run.add_argument("--device", help="audio input: index or name from `elfjamalong devices` (default: system input)")
    run.add_argument("--input-channel", type=int, default=1, help="which input channel the guitar is on (default 1)")
    run.add_argument("--gate-db", type=float, default=-50.0, help="ignore input quieter than this (default -50 dBFS)")
    run.add_argument("--tail", type=float, default=4.0, help="keep playing this many seconds after you stop (default 4)")
    run.add_argument("--follow-transport", action="store_true",
                     help="only play while the DAW is playing (needs Link Start Stop Sync)")
    run.add_argument("--feel", choices=["follow", "answer", "off"], default="follow",
                     help="follow: play harder and busier when you do (default); answer: also stay out of the way of "
                          "your strums and fill the gaps you leave; off: ignore how you play")
    run.add_argument("--predict", action="store_true",
                     help="once a progression has repeated, play over the chord that comes next instead of waiting to hear it")
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
    render.add_argument("-o", "--output", default="elfjamalong.mid")
    render.add_argument("--roles", default="lead", help="comma list of lead, bass, arp (default lead)")
    render.add_argument("--preset", choices=sorted(PRESETS), help="solo = lead; duo = lead,bass; trio = lead,bass,arp")
    melody_opts(render)
    render.set_defaults(fn=cmd_render)

    sub.add_parser("capture", help="keep the last bars the running ElfJamAlong played").set_defaults(fn=cmd_capture)

    cal = sub.add_parser("calibrate", help="measure the instrument's delay and suggest an --offset-ms")
    cal.add_argument("--source", choices=["device", "live", "link"], default="device")
    cal.add_argument("--app", default="com.ableton.live")
    cal.add_argument("--link-channel", default="")
    cal.add_argument("--device")
    cal.add_argument("--input-channel", type=int, default=1)
    cal.add_argument("--channel", type=int, default=1)
    cal.add_argument("--note", type=int, default=84, help="MIDI note to send (default 84)")
    cal.add_argument("--notes", type=int, default=8, help="how many test notes (default 8)")
    cal.set_defaults(fn=cmd_calibrate)

    # Saved settings: ./elfjamalong.toml, e.g.  [run]  source = "live"  roles = "lead,bass"
    config = Path("elfjamalong.toml")
    if config.exists():
        saved = tomllib.loads(config.read_text())
        for name, parser in (("run", run), ("demo", demo), ("render", render), ("calibrate", cal)):
            settings = {k.replace("-", "_"): v for k, v in saved.get(name, {}).items()}
            known = {a.dest for a in parser._actions}
            for k in sorted(set(settings) - known):
                print(f"elfjamalong.toml: [{name}] has no option '{k}' (ignored)", file=sys.stderr)
            parser.set_defaults(**{k: v for k, v in settings.items() if k in known})

    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
