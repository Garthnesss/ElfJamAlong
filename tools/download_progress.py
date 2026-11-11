"""Live progress bar for a file that something else is downloading.

    python3 tools/download_progress.py <file> <total-bytes>
"""

import os
import sys
import time

path, total = sys.argv[1], int(sys.argv[2])
width = 40
samples = []  # (time, bytes) over the last ~10 s, for a steady speed reading

while True:
    size = os.path.getsize(path) if os.path.exists(path) else 0
    now = time.time()
    samples = [(t, b) for t, b in samples if now - t <= 10] + [(now, size)]
    span = samples[-1][0] - samples[0][0]
    speed = (samples[-1][1] - samples[0][1]) / span if span > 0 else 0.0
    done = min(1.0, size / total)
    filled = int(done * width)
    if size >= total:
        eta = "done"
    elif speed > 0:
        left = int((total - size) / speed)
        eta = f"{left // 60}m {left % 60:02d}s left"
    else:
        eta = "waiting..."
    bar = "#" * filled + "-" * (width - filled)
    sys.stdout.write(
        f"\r[{bar}] {done * 100:5.1f}%  {size / 1e6:6.1f} / {total / 1e6:.1f} MB  {speed / 1e3:5.0f} KB/s  {eta}      "
    )
    sys.stdout.flush()
    if size >= total:
        print()
        break
    time.sleep(1)
