"""Platzhalter fuer ffprobe im Test.

Ueber die Umgebungsvariable RR_FAKE_PROBE wird gesteuert, was gemeldet wird:
mp3 (Vorgabe), aac, opus, leer (keine Tonspur), fehler (Abbruch).
"""

import json
import os
import sys

BITRATEN = {"mp3": "128000", "aac": "96000", "opus": "64000"}


def main():
    modus = os.environ.get("RR_FAKE_PROBE", "mp3")

    if modus == "fehler":
        sys.stderr.write("https://example/stream: Server returned 404 Not Found\n")
        return 1

    if modus == "leer":
        print(json.dumps({"streams": [], "format": {}}))
        return 0

    bitrate = BITRATEN.get(modus, "128000")
    print(json.dumps({
        "streams": [{"codec_name": modus, "bit_rate": bitrate}],
        "format": {"bit_rate": bitrate, "tags": {"icy-name": "Test-Sender FM"}},
    }))
    return 0


if __name__ == "__main__":
    sys.exit(main())
