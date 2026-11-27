#!/usr/bin/env python3
"""Scan SwitchBot meters and upload their measurements over HTTPS."""

import argparse
import fcntl
import json
import os
import subprocess
import sys
import tempfile
import time
from urllib.parse import urlsplit

from switchbot_scan import H4Device, scan


def upload(url, header_file, sensors):
    parts = urlsplit(url)
    if parts.scheme != "https" or not parts.hostname or parts.username or parts.password:
        raise ValueError("The upload URL must be an HTTPS URL without credentials")
    if not sensors:
        raise ValueError("No SwitchBot readings to upload")
    if os.stat(header_file).st_mode & 0o077:
        raise PermissionError("Authorization header file must not be accessible to group or others")

    body = json.dumps({"device": "Echo Show 5", "sensors": sensors})
    result = subprocess.run(
        [
            "curl", "-4", "--silent", "--show-error", "--fail-with-body",
            "--connect-timeout", "15", "--max-time", "15",
            "--header", "Content-Type: application/json",
            "--header", "@" + header_file,
            "--data-binary", "@-", "--", url,
        ],
        input=body,
        text=True,
        capture_output=True,
        timeout=20,
        check=False,
    )
    if result.returncode:
        raise RuntimeError(f"Sensor upload failed: {result.stderr.strip()}")
    response = json.loads(result.stdout)
    if not isinstance(response, dict) or response.get("accepted") != len(sensors):
        raise RuntimeError("The sensor server did not accept all readings")
    return response["accepted"]


def update_state(path, sensors):
    with open(path + ".lock", "a", encoding="utf-8") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        with open(path, encoding="utf-8") as state_file:
            state = json.load(state_file)
        state["sensors"] = sensors
        state["sensorUpdatedAt"] = int(time.time() * 1000)
        fd, temporary = tempfile.mkstemp(prefix=os.path.basename(path) + ".", dir=os.path.dirname(path))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as output:
                json.dump(state, output, ensure_ascii=False)
                output.write("\n")
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True)
    parser.add_argument("--header-file", required=True)
    parser.add_argument("--duration", type=int, default=30)
    parser.add_argument("--device", default="/dev/stpbt")
    parser.add_argument("--interval", type=int, help="Repeat every N seconds")
    parser.add_argument("--state", help="Update the kiosk state JSON")
    args = parser.parse_args()
    if args.duration < 1:
        parser.error("--duration must be at least 1")
    if args.interval is not None and args.interval < args.duration:
        parser.error("--interval must be at least --duration")
    device = H4Device(args.device)
    try:
        while True:
            started = time.monotonic()
            sensors = scan(device, args.duration)
            if args.state:
                update_state(args.state, sensors)
            try:
                count = upload(args.url, args.header_file, sensors)
                print(f"Uploaded {count} sensor reading(s)", flush=True)
            except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
                if args.interval is None:
                    raise
                print(f"Sensor upload failed: {error}", file=sys.stderr, flush=True)
            if args.interval is None:
                break
            time.sleep(max(0, args.interval - (time.monotonic() - started)))
    finally:
        device.close()


if __name__ == "__main__":
    main()
