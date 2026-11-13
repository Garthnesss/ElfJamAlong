import json, sys, bisect
TRUTH = "Am Dm G C F Dm E Am".split()
d = json.load(open(sys.argv[1]))
LAG = float(sys.argv[2]) if len(sys.argv) > 2 else 0.6   # grace after a true change
samples = [s for s in d["samples"] if s[1] is not None]
wall = [s[0] for s in samples]; song = [s[1] for s in samples]; playing = [s[2] for s in samples]


def song_at(t):
    i = bisect.bisect_left(wall, t)
    if i == 0 or i >= len(wall):
        return None
    (t0, s0), (t1, s1) = (wall[i-1], song[i-1]), (wall[i], song[i])
    return s0 + (s1 - s0) * (t - t0) / (t1 - t0)


fire_song = d["fire_song"]
start = float(sys.argv[3]) if len(sys.argv) > 3 and sys.argv[3] != 'auto' else (int(fire_song // 4) + 1) * 4   # clip launches on the next bar
t_stop = d["t_stop"]


def truth_at(t, off=0):
    s = song_at(t)
    if s is None or s < start:
        return None
    bar = int((s - start) // 4) % 8
    return TRUTH[bar]


# heard as a step function
heard = d["heard"]
ht = [h[0] for h in heard]


def heard_at(t):
    i = bisect.bisect_right(ht, t) - 1
    return heard[i][1] if i >= 0 else "-"


def score(off):
    ok = n = 0
    t = d["t_fire"]
    while t < t_stop:
        s = song_at(t)
        if s is not None and s >= start + off * 4:
            bar = int((s - start) // 4 + off) % 8 if False else int((s - start) // 4) % 8
            n += 1
            ok += heard_at(t) == TRUTH[(bar + off) % 8]
        t += 0.1
    return ok / n if n else 0


if len(sys.argv) > 3 and sys.argv[3] == 'auto':
    cands = [x*0.25 for x in range(0, 128)]
    def sc(st):
        global start
        start = st; return score(0)
    start = max(cands, key=sc)
    print('auto start (song beats, mod 32):', start, 'score', score(0))
best = max(range(8), key=score)
print("assumed phase 0 score %.3f; best phase %d score %.3f" % (score(0), best, score(best)))
off = best if score(best) > score(0) + 0.1 else 0


def tr(t):
    s = song_at(t)
    if s is None or s < start:
        return None
    return TRUTH[(int((s - start) // 4) + off) % 8]


t = d["t_fire"]; rows = []
while t < t_stop:
    tt = tr(t)
    if tt:
        # grace: ignore LAG seconds after a true change
        prev = tr(t - LAG)
        rows.append((t, tt, heard_at(t), prev == tt))
    t += 0.05
n = len(rows); settled = [r for r in rows if r[3]]
print("frames %d, right overall %.1f%%, right when settled (>%.1fs after change) %.1f%%" % (
    n, 100*sum(r[1] == r[2] for r in rows)/n, LAG, 100*sum(r[1] == r[2] for r in settled)/max(1, len(settled))))
# wrong segments among settled frames
segs = []; cur = None
for t, tt, hh, st in rows:
    wrong = st and tt != hh
    if wrong:
        if cur and cur[1] == hh and cur[2] == tt and t - cur[4] < 0.15:
            cur[3] = t; cur[4] = t
        else:
            cur = [t, hh, tt, t, t]; segs.append(cur)
print("wrong-chord segments (heard vs truth, start s after fire, duration s):")
for s in segs:
    print("  %5.1f  heard %-3s truth %-3s  %.2fs" % (s[0]-d["t_fire"], s[1], s[2], s[3]-s[0]+0.05))
# reaction: for each true change, first time heard == truth
changes = []; last = None
t = d["t_fire"]
while t < t_stop:
    tt = tr(t)
    if tt and tt != last:
        changes.append((t, tt)); last = tt
    t += 0.02
react = []
for (t0, c), nxt in zip(changes, changes[1:] + [(t_stop, None)]):
    if t0 - d["t_fire"] < 1: continue
    th = next((h[0] for h in heard if h[0] >= t0 and h[1] == c and h[0] < nxt[0]), None)
    react.append(None if th is None else th - t0)
vals = [r for r in react if r is not None]
print("changes %d, reached right chord for %d; reaction mean %.2fs median %.2fs worst %.2fs" % (
    len(react), len(vals), sum(vals)/len(vals), sorted(vals)[len(vals)//2], max(vals)))
print("after stop: heard lines after t_stop:")
for h in heard:
    if h[0] >= t_stop - 0.2:
        print("  +%.1fs chord %s key %s" % (h[0]-t_stop, h[1], h[2]))
print("raw tail:", d["raw_tail"][-2:])
