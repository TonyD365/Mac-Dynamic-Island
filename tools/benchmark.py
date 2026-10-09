"""Measure how much work the island does, and compare two measurements.

    python tools/benchmark.py --src src --json head.json      # measure a source tree
    python tools/benchmark.py --compare base.json head.json   # Markdown table of the difference

It times the things that run over and over while the island sits on screen: the 20-times-a-second
tick, the 4-times-a-second refresh, and every background reading. From those it estimates the
island's idle load. Nothing is sent to other apps and no setting is touched.
"""
import argparse
import json
import os
import statistics
import subprocess
import sys
import tempfile
import time

# How often each reading runs in the app, in seconds (see Monitors.start).
INTERVALS = {"camera_in_use": 1.0, "mic_in_use": 1.0, "volume": 0.12, "muted": 0.12, "brightness": 0.12,
             "battery": 4.0, "bluetooth": 30.0, "bluetooth_signature": 1.0, "now_playing": 1.5, "memory_used": 3.0,
             "gpu_usage": 3.0, "net_bytes": 3.0}
TICKS_PER_SECOND, REFRESHES_PER_SECOND = 20, 4
NOISE = 0.25        # differences smaller than this are within run-to-run variation on shared runners


def median_ms(fn, repeat):
    times = []
    for _ in range(repeat):
        start = time.perf_counter()
        fn()
        times.append((time.perf_counter() - start) * 1000)
    return statistics.median(times)


def measure(src):
    src = os.path.abspath(src)
    results = {}

    # Cold import of the whole app, in fresh interpreters.
    code = "import sys; sys.path.insert(0, %r); import island" % src
    results["startup: import (ms)"] = median_ms(lambda: subprocess.run([sys.executable, "-c", code], check=True), 3)

    sys.path.insert(0, src)
    import monitors

    for name in INTERVALS:
        fn = getattr(monitors, name, None)
        if fn is None:
            continue                            # this source tree doesn't have that reading
        call = (lambda fn=fn: fn(None)) if name == "brightness" else fn
        try:
            results["reading: %s (ms)" % name] = median_ms(call, 5)
        except Exception:
            pass                                # not available on this machine

    try:
        results.update(measure_interface(src))
    except Exception as e:                      # no window server, for instance
        print("interface benchmark skipped: %r" % (e,), file=sys.stderr)

    # Idle load: every reading at its own rate, plus the main loop, as a share of one CPU core.
    # Readings are counted by wall time, so this is an upper bound.
    load = sum(results.get("reading: %s (ms)" % name, 0.0) / interval for name, interval in INTERVALS.items())
    load += results.get("loop: tick, idle (ms)", 0.0) * TICKS_PER_SECOND
    load += results.get("loop: refresh, idle (ms)", 0.0) * REFRESHES_PER_SECOND
    results["estimated idle load (% of one core)"] = load / 10.0
    return results


def measure_interface(src):
    from AppKit import NSApplication, NSScreen
    NSApplication.sharedApplication()
    import island
    import settings

    settings.PATH = os.path.join(tempfile.mkdtemp(), "settings.json")     # never the real settings
    settings.save = lambda values: None
    if hasattr(island, "lockscreen"):
        island.lockscreen.attach = lambda number: None
    if island.screen_util.builtin_screen() is None:                       # CI machines have no built-in display
        island.screen_util.builtin_screen = lambda *a, **k: NSScreen.screens()[0]

    results = {}
    start = time.perf_counter()
    isl = island.Island()
    isl.relocate()
    results["startup: build window and layers (ms)"] = (time.perf_counter() - start) * 1000
    if not isl.screen_ok:
        raise RuntimeError("no screen to draw on")

    mon = isl.monitors                           # never started: fixed, typical readings instead
    mon.batt, mon.ac, mon.cpu, mon.mem, mon.volume, mon.muted, mon.brightness, mon.bt = 80, False, 0.1, 0.5, 0.5, False, 0.7, {}
    if hasattr(mon, "gpu"):
        mon.gpu = 0.2
    now = time.time()
    for _ in range(20):
        isl.tick()

    results["loop: tick, idle (ms)"] = median_ms(isl.tick, 400)
    results["loop: refresh, idle (ms)"] = median_ms(lambda: isl.refresh(time.time()), 300)

    mon.music = {"app": "Player", "control": None, "playing": True, "rate": 1.0, "title": "A song title",
                 "artist": "An artist", "position": 30.0, "duration": 200.0, "at": now}
    results["loop: refresh, media playing (ms)"] = median_ms(lambda: isl.refresh(time.time()), 300)
    mon.music = None

    isl.mode = "expanded"
    isl.open_menu()
    isl.menu_seen = time.time() + 3600
    results["loop: tick, ring open (ms)"] = median_ms(isl.tick, 400)
    turn = (lambda: isl.inner.rotate(1)) if hasattr(isl, "inner") else (lambda: isl.rotate_menu(1))
    results["ring: turn one step (ms)"] = median_ms(turn, 100)
    if hasattr(isl, "outer"):                   # a category open: two rings to track
        category = next((e for e in isl.inner.items if e.children), None)
        if category is not None:
            isl.open_outer(category, isl.inner.pos[0])
            results["loop: tick, both rings open (ms)"] = median_ms(isl.tick, 400)
    return results


def compare(base_path, head_path):
    with open(base_path) as f:
        base = json.load(f)
    with open(head_path) as f:
        head = json.load(f)
    fmt = lambda v: "—" if v is None else ("%.3f" % v if v < 10 else "%.1f" % v)
    lines = ["## Benchmark", "",
             "| Measurement | Base | This PR | Change |", "|---|---:|---:|---:|"]
    worse = 0
    for name in list(head) + [n for n in base if n not in head]:
        b, h = base.get(name), head.get(name)
        if b is None or h is None:
            change = "new" if b is None else "removed"
        elif b == 0:
            change = "—"
        else:
            delta = (h - b) / b
            mark = ""
            if delta > NOISE and (h - b) > 0.05:        # ignore large percentages of tiny numbers
                mark, worse = " ⚠️", worse + 1
            elif delta < -NOISE and (b - h) > 0.05:
                mark = " ✅"
            change = "%+.0f%%%s" % (delta * 100, mark)
        lines.append("| %s | %s | %s | %s |" % (name, fmt(b), fmt(h), change))
    lines += ["",
              "Medians, lower is better. Both columns were measured in this run on the same machine. "
              "Shared runners are noisy: changes within ±%d%% are not marked." % (NOISE * 100),
              "The idle load is an upper bound: readings are counted by wall time, not CPU time.", ""]
    lines.append("**%d measurement(s) got noticeably slower.**" % worse if worse else "No measurement got noticeably slower.")
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--src", help="source tree to measure")
    parser.add_argument("--json", help="write the measurements here")
    parser.add_argument("--compare", nargs=2, metavar=("BASE", "HEAD"))
    args = parser.parse_args()
    if args.compare:
        sys.stdout.write(compare(*args.compare))
        return
    results = measure(args.src or "src")
    if args.json:
        with open(args.json, "w") as f:
            json.dump(results, f, indent=2)
    for name, value in results.items():
        print("%-42s %10.3f" % (name, value))


if __name__ == "__main__":
    main()
