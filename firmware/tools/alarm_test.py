#!/usr/bin/env python3
"""Records the LogGuard detector log with scenario markers and counts alarms.

Bench test of false alarms (and of detection, with a chainsaw sound as the
control). Run it in the ESP-IDF terminal with `idf.py monitor` closed.

1. Record (the board keeps running; opening the port does not reset it):

       python tools/alarm_test.py record COM7 alarmi.log

   Type a scenario name and Enter when it starts, e.g. `tisina`, `govor`,
   `muzika`, `testera`. Everything after that line belongs to that scenario
   until the next name. Type `q` and Enter to stop.

2. Count:

       python tools/alarm_test.py count alarmi.log

   Per scenario: windows, share of windows with p >= threshold, alarms as
   the firmware counts them (CONSEC windows in a row; then the counter starts
   again), alarms after the cooldown, longest run, highest p.

`count` also reads a log saved any other way (copied from the monitor), as
long as the lines `logguard: p=... consec=...` are in it; scenario markers are
lines `SCENARIO <name>`. Needs pyserial only for `record` (it is part of the
ESP-IDF Python environment).
"""
import argparse
import re
import sys
import threading
import time

ANSI = re.compile(r"\x1b\[[0-9;]*m")
WINDOW = re.compile(r"\((\d+)\) logguard: p=([0-9.]+) raw=(-?\d+)/(-?\d+) consec=(\d+)")
MARK = re.compile(r"^SCENARIO\s+(.+)$")


def record(port, out, baud):
    import serial

    ser = serial.Serial()
    ser.port, ser.baudrate, ser.timeout = port, baud, 0.5
    ser.dtr = False          # do not reset the board when the port opens
    ser.rts = False
    ser.open()
    stop = threading.Event()
    lock = threading.Lock()
    f = open(out, "a", encoding="utf-8")

    def reader():
        while not stop.is_set():
            raw = ser.readline()
            if not raw:
                continue
            line = ANSI.sub("", raw.decode("utf-8", errors="replace")).rstrip()
            with lock:
                f.write(line + "\n")
                f.flush()
            m = WINDOW.search(line)
            if m:
                print(f"  p={m.group(2)} consec={m.group(5)}", flush=True)

    t = threading.Thread(target=reader, daemon=True)
    t.start()
    print(f"Recording {port} -> {out}. Type a scenario name + Enter to mark it, 'q' + Enter to stop.")
    try:
        while True:
            name = input().strip()
            if name.lower() == "q":
                break
            if name:
                with lock:
                    f.write(f"SCENARIO {name}\n")
                    f.flush()
                print(f"== scenario '{name}' from {time.strftime('%H:%M:%S')}", flush=True)
    except (KeyboardInterrupt, EOFError):
        pass
    stop.set()
    t.join(timeout=2)
    ser.close()
    f.close()
    print(f"Saved {out}. Now: python tools/alarm_test.py count {out}")


def count(path, threshold, consec_needed, cooldown_s):
    scenarios, order, name = {}, [], "(bez oznake)"
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            line = ANSI.sub("", line).strip()
            m = MARK.match(line)
            if m:
                name = m.group(1).strip()
                continue
            w = WINDOW.search(line)
            if not w:
                continue
            if name not in scenarios:
                scenarios[name] = []
                order.append(name)
            scenarios[name].append((int(w.group(1)), float(w.group(2)), int(w.group(5))))

    if not scenarios:
        sys.exit("no 'logguard: p=... consec=...' lines found (is 'Log the score of every window' on?)")

    head = (f"{'scenarij':<16}{'prozora':>8}{'trajanje s':>11}{'p>=' + str(threshold):>9}"
            f"{'alarmi':>8}{'uz pauzu':>10}{'max consec':>11}{'max p':>7}")
    print(head)
    print("-" * len(head))
    for name in order:
        rows = scenarios[name]
        n = len(rows)
        above = sum(1 for _, p, _ in rows if p >= threshold)
        # The firmware resets consec to 0 after an alert and otherwise lets it grow,
        # so every time consec equals CONSEC_NEEDED is one alarm condition.
        events = [ms for ms, _, c in rows if c == consec_needed]
        sent, quiet_until = 0, -1
        for ms in events:
            if ms >= quiet_until:
                sent += 1
                quiet_until = ms + cooldown_s * 1000
        dur = (rows[-1][0] - rows[0][0]) / 1000 if n > 1 else 0.0
        print(f"{name[:15]:<16}{n:>8}{dur:>11.0f}{100 * above / n:>8.1f}%{len(events):>8}{sent:>10}"
              f"{max(c for _, _, c in rows):>11}{max(p for _, p, _ in rows):>7.2f}")
    print()
    print(f"Prag {threshold}, alarm = {consec_needed} uzastopna prozora, pauza {cooldown_s} s "
          "(kao Kconfig). 'alarmi' = svaki put kad consec dostigne prag; 'uz pauzu' = koliko bi ih "
          "firmver poslao. Uslovi (prostorija, zvučnik, udaljenost, jačina) se upisuju uz rezultat.")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("record", help="record the serial log with scenario markers")
    r.add_argument("port")
    r.add_argument("out")
    r.add_argument("--baud", type=int, default=115200)
    c = sub.add_parser("count", help="count windows and alarms per scenario")
    c.add_argument("log")
    c.add_argument("--threshold", type=float, default=0.80)
    c.add_argument("--consec", type=int, default=3)
    c.add_argument("--cooldown", type=int, default=60)
    a = ap.parse_args()
    if a.cmd == "record":
        record(a.port, a.out, a.baud)
    else:
        count(a.log, a.threshold, a.consec, a.cooldown)


if __name__ == "__main__":
    main()
