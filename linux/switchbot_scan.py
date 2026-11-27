#!/usr/bin/env python3
"""Scan SwitchBot meter advertisements through MediaTek's H4 device."""

import argparse
import json
import os
import select
import struct
import time


class H4Device:
    def __init__(self, path):
        self.fd = os.open(path, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
        self.buffer = bytearray()

    def close(self):
        os.close(self.fd)

    def event(self, timeout):
        deadline = time.monotonic() + timeout
        while True:
            if self.buffer:
                if self.buffer[0] != 4:
                    raise RuntimeError(f"Unexpected H4 packet type: {self.buffer[0]}")
                if len(self.buffer) >= 3:
                    length = 3 + self.buffer[2]
                    if len(self.buffer) >= length:
                        result = bytes(self.buffer[:length])
                        del self.buffer[:length]
                        return result
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not select.select([self.fd], [], [], remaining)[0]:
                return None
            data = os.read(self.fd, 4096)
            if not data:
                raise RuntimeError("Bluetooth device closed")
            self.buffer.extend(data)

    def command(self, opcode, parameters=b""):
        command = struct.pack("<BHB", 1, opcode, len(parameters)) + parameters
        if os.write(self.fd, command) != len(command):
            raise RuntimeError(f"Short HCI command write: {opcode:04x}")
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            event = self.event(deadline - time.monotonic())
            if event is None:
                break
            if len(event) >= 7 and event[1] == 0x0E:
                received = int.from_bytes(event[4:6], "little")
                status = event[6]
            elif len(event) >= 7 and event[1] == 0x0F:
                received = int.from_bytes(event[5:7], "little")
                status = event[3]
            else:
                continue
            if received == opcode:
                if status:
                    raise RuntimeError(f"HCI command {opcode:04x} failed: {status}")
                return
        raise TimeoutError(f"HCI command {opcode:04x} timed out")


def advertisements(event):
    if len(event) < 5 or event[1] != 0x3E or event[3] != 0x02:
        return
    offset = 5
    for _ in range(event[4]):
        if offset + 10 > len(event):
            raise ValueError("Truncated BLE advertisement")
        address = event[offset + 2:offset + 8][::-1].hex().upper()
        data_length = event[offset + 8]
        end = offset + 9 + data_length
        if end >= len(event):
            raise ValueError("Truncated BLE advertisement data")
        rssi = int.from_bytes(event[end:end + 1], "little", signed=True)
        yield address, event[offset + 9:end], rssi
        offset = end + 1


def advertisement_fields(data):
    manufacturer = service = None
    offset = 0
    while offset < len(data):
        length = data[offset]
        if length == 0:
            break
        end = offset + 1 + length
        if end > len(data):
            raise ValueError("Truncated BLE advertising field")
        kind = data[offset + 1]
        value = data[offset + 2:end]
        if kind == 0xFF and value[:2] == b"\x69\x09":
            manufacturer = value[2:]
        elif kind == 0x16 and value[:2] == b"\x3d\xfd":
            service = value[2:]
        offset = end
    return manufacturer, service


def reading(manufacturer, service):
    if len(manufacturer) < 11 or len(service) < 3 or service[0] & 0x7F not in (0x54, 0x77):
        return None
    humidity = manufacturer[10] & 0x7F
    if humidity > 100:
        return None
    temperature = (manufacturer[9] & 0x7F) + (manufacturer[8] & 0x0F) / 10
    if not manufacturer[9] & 0x80:
        temperature = -temperature
    return {
        "temperatureC": temperature,
        "humidity": humidity,
        "battery": service[2] & 0x7F,
    }


def scan(device, duration):
    states = {}
    device.command(0x0C03)
    device.command(0x0C01, b"\xff\xff\xff\xff\xff\xff\xff\x3f")
    device.command(0x2001, b"\x1f\x00\x00\x00\x00\x00\x00\x00")
    device.command(0x200B, b"\x01\xa0\x00\x50\x00\x00\x00")
    device.command(0x200C, b"\x01\x00")
    try:
        deadline = time.monotonic() + duration
        while time.monotonic() < deadline:
            event = device.event(deadline - time.monotonic())
            if event is None:
                break
            for address, data, rssi in advertisements(event):
                manufacturer, service = advertisement_fields(data)
                if manufacturer is None and service is None:
                    continue
                now = time.monotonic()
                state = states.setdefault(address, {})
                if manufacturer is not None:
                    state["manufacturer"] = (manufacturer, now)
                if service is not None:
                    state["service"] = (service, now)
                if "manufacturer" in state and "service" in state:
                    payload, payload_time = state["manufacturer"]
                    service_data, service_time = state["service"]
                    if abs(payload_time - service_time) <= 15:
                        values = reading(payload, service_data)
                        if values is not None:
                            state["reading"] = {
                                "id": address[-4:],
                                "name": "",
                                **values,
                                "rssi": rssi,
                            }
                            state["reading_time"] = payload_time
        now = time.monotonic()
        return [
            {**state["reading"], "ageSec": int(now - state["reading_time"])}
            for address, state in sorted(states.items(), key=lambda item: (item[0][-4:], item[0]))
            if "reading" in state
        ]
    finally:
        device.command(0x200C, b"\x00\x00")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--duration", type=int, default=20)
    parser.add_argument("--device", default="/dev/stpbt")
    args = parser.parse_args()
    if args.duration < 1:
        parser.error("--duration must be at least 1")
    device = H4Device(args.device)
    try:
        sensors = scan(device, args.duration)
    finally:
        device.close()
    print(json.dumps({"sensors": sensors}, ensure_ascii=False))


if __name__ == "__main__":
    main()
