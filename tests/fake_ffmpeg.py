"""Platzhalter fuer ffmpeg im Test.

Kann zweierlei:
  * Segmentmodus: schreibt fortlaufend Daten in seg_NNNNN.<ext>, rollt nach
    -segment_time weiter und endet nach -t Sekunden.
  * concat-Modus: haengt die in der Listendatei genannten Dateien aneinander.
"""

import os
import signal
import sys
import time

_stop = {"flag": False}


def _handler(signum, frame):
    _stop["flag"] = True


for _sig in (signal.SIGINT, signal.SIGTERM):
    try:
        signal.signal(_sig, _handler)
    except (ValueError, OSError):
        pass


def arg(args, name, default=None):
    try:
        return args[args.index(name) + 1]
    except (ValueError, IndexError):
        return default


def main():
    args = sys.argv[1:]
    out = args[-1]

    if "concat" in args:
        listing = arg(args, "-i")
        base = os.path.dirname(os.path.abspath(listing)) or os.getcwd()
        with open(listing, encoding="utf-8") as handle:
            names = [line.strip()[6:-1] for line in handle
                     if line.strip().startswith("file ")]
        with open(out, "wb") as target:
            for name in names:
                with open(os.path.join(base, name), "rb") as part:
                    target.write(part.read())
        return 0

    if os.environ.get("RR_FAKE_FAIL"):
        # Stellt einen nicht erreichbaren Stream nach.
        sys.stderr.write(
            "https://stream.example/live: Server returned 404 Not Found\n")
        sys.stderr.flush()
        return 1

    total = float(arg(args, "-t", "10"))
    seg_time = float(arg(args, "-segment_time", "3"))
    number = int(arg(args, "-segment_start_number", "0"))

    started = time.monotonic()
    handle = None
    seg_started = 0.0
    try:
        while time.monotonic() - started < total and not _stop["flag"]:
            now = time.monotonic()
            if handle is None or (now - seg_started) >= seg_time:
                if handle:
                    handle.close()
                    number += 1
                handle = open(out % number, "wb")
                seg_started = now
            handle.write(b"\x00" * 1024)
            handle.flush()
            time.sleep(0.05)
    finally:
        if handle:
            handle.close()
    return 255 if _stop["flag"] else 0


if __name__ == "__main__":
    sys.exit(main())
