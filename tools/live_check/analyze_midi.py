import json, sys, bisect, statistics
d = json.load(open(sys.argv[1]))
midi = d["midi"]; t_stop = d["t_stop"]; t_fire = d["t_fire"]
samples = [s for s in d["samples"] if s[1] is not None]
wall = [s[0] for s in samples]; song = [s[1] for s in samples]
bpm = 117.0
for h in d["heard"][-1:]: pass


def song_at(t):
    i = bisect.bisect_left(wall, t)
    if i == 0 or i >= len(wall):
        return None
    (t0, s0), (t1, s1) = (wall[i-1], song[i-1]), (wall[i], song[i])
    return s0 + (s1 - s0) * (t - t0) / (t1 - t0)


ons = [m for m in midi if m[1] == "note_on"]
offs = [m for m in midi if m[1] == "note_off"]
print("notes on %d off %d; channels on: %s" % (len(ons), len(offs), sorted({m[4] for m in ons})))
for ch in sorted({m[4] for m in ons}):
    print("  ch%d: %d notes, pitch %d-%d, vel %d-%d" % (ch, sum(1 for m in ons if m[4]==ch),
          min(m[2] for m in ons if m[4]==ch), max(m[2] for m in ons if m[4]==ch),
          min(m[3] for m in ons if m[4]==ch), max(m[3] for m in ons if m[4]==ch)))
# grid: distance of each note-on from the nearest sixteenth (0.25 beat) of the song clock
dev = []
for m in ons:
    s = song_at(m[0])
    if s is None: continue
    x = (s / 0.25) % 1.0
    x = x if x < 0.5 else x - 1.0
    dev.append(x * 0.25 * 60 / bpm * 1000)   # ms
if dev:
    print("note-on vs sixteenth grid (song clock interpolated from ~0.5 s polls, so +-30 ms of measurement noise):")
    print("  n=%d mean %.0f ms, median %.0f ms, stdev %.0f ms, |max| %.0f ms" % (len(dev), statistics.mean(dev), statistics.median(dev), statistics.pstdev(dev), max(abs(x) for x in dev)))
# stop behaviour
after = [m for m in midi if m[0] >= t_stop]
last_on = max((m[0] for m in ons), default=0)
print("after clip stop: %d note-ons, last note-on at %+.1f s; last event at %+.1f s" % (
    sum(1 for m in after if m[1]=="note_on"), last_on - t_stop, (midi[-1][0]-t_stop) if midi else 0))
open_ = {}
for m in midi:
    k = (m[4], m[2])
    if m[1] == "note_on": open_[k] = open_.get(k, 0) + 1
    else: open_[k] = max(0, open_.get(k, 0) - 1)
print("notes still on at the end (stuck):", {k: v for k, v in open_.items() if v})
