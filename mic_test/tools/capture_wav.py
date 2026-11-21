#!/usr/bin/env python3
"""Records a short WAV from the LogGuard mic test over the serial port.

Usage (ESP-IDF terminal, with idf.py monitor closed):
    python tools/capture_wav.py COM5 snimak.wav
    python tools/capture_wav.py /dev/ttyUSB0 snimak.wav

The board must run mic_test with CONFIG_MICTEST_WAV_SECONDS > 0. The script
sends 'w', waits for the WAV_BEGIN <bytes> <crc32> ... WAV_END block, checks
the length and CRC-32 and writes the file. Needs pyserial (it is part of the
ESP-IDF Python environment).
"""
import argparse
import base64
import sys
import time
import zlib

import serial


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("port", help="serial port, e.g. COM5 or /dev/ttyUSB0")
    ap.add_argument("out", help="output .wav file")
    ap.add_argument("--baud", type=int, default=115200)
    ap.add_argument("--timeout", type=float, default=90.0, help="seconds to wait for the whole WAV")
    args = ap.parse_args()

    ser = serial.Serial()
    ser.port = args.port
    ser.baudrate = args.baud
    ser.timeout = 1.0
    # Keep DTR/RTS released so that opening the port does not reset the board.
    ser.dtr = False
    ser.rts = False
    ser.open()
    # If the board resets anyway, give it time to boot before sending 'w'.
    time.sleep(2.0)
    ser.reset_input_buffer()
    ser.write(b"w")
    print("Sent 'w'. Make the sound now (recording starts at once).")

    deadline = time.time() + args.timeout
    expected = crc = None
    chunks = []
    while time.time() < deadline:
        line = ser.readline().decode("ascii", errors="replace").strip()
        if not line:
            continue
        if expected is None:
            if line.startswith("WAV_BEGIN"):
                _, n, c = line.split()
                expected, crc = int(n), int(c, 16)
                print(f"Receiving {expected} bytes ...")
            elif "mic_test" in line:
                print(line)
            continue
        if line == "WAV_END":
            break
        if line.startswith(("I (", "W (", "E (")):  # stray log line
            continue
        chunks.append(line)
    ser.close()

    if expected is None:
        print("ERROR: no WAV_BEGIN. Is mic_test flashed with WAV enabled, and is the monitor closed?")
        return 1
    data = base64.b64decode("".join(chunks))
    if len(data) != expected:
        print(f"ERROR: got {len(data)} bytes, expected {expected}")
        return 1
    if zlib.crc32(data) != crc:
        print("ERROR: CRC-32 mismatch, the transfer was corrupted")
        return 1
    with open(args.out, "wb") as f:
        f.write(data)
    print(f"OK: {args.out} ({len(data)} bytes, CRC-32 {crc:08x})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
