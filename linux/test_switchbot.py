import fcntl
import json
import os
import subprocess
import tempfile
import time
import unittest
from unittest.mock import patch

import switchbot_scan
import switchbot_upload


class SwitchBotTest(unittest.TestCase):
    def test_meter_advertisement_and_temperature(self):
        manufacturer = bytes([0] * 8 + [8, 0x80 | 17, 48])
        service = bytes([0x54, 0, 90])
        data = (
            bytes([len(manufacturer) + 3, 0xFF, 0x69, 0x09]) + manufacturer
            + bytes([len(service) + 3, 0x16, 0x3D, 0xFD]) + service
        )
        report = b"\x00\x00\x01\x02\x03\x04\x05\x06" + bytes([len(data)]) + data + b"\xc4"
        event = bytes([4, 0x3E, 2 + len(report), 2, 1]) + report
        address, fields, rssi = next(switchbot_scan.advertisements(event))
        self.assertEqual((address, rssi), ("060504030201", -60))
        self.assertEqual(switchbot_scan.advertisement_fields(fields), (manufacturer, service))
        self.assertEqual(
            switchbot_scan.reading(manufacturer, service),
            {"temperatureC": 17.8, "humidity": 48, "battery": 90},
        )
        self.assertEqual(
            switchbot_scan.reading(bytes([0] * 8 + [5, 2, 99]), bytes([0x77, 0, 70])),
            {"temperatureC": -2.5, "humidity": 99, "battery": 70},
        )

    def test_rejects_malformed_or_invalid_readings(self):
        with self.assertRaises(ValueError):
            switchbot_scan.advertisement_fields(b"\x04\xff\x69")
        self.assertIsNone(switchbot_scan.reading(bytes([0] * 10 + [101]), b"\x54\x00\x64"))
        self.assertIsNone(switchbot_scan.reading(bytes(11), b"\x01\x00\x64"))

    def test_scan_orders_sensors_independently_of_discovery_order(self):
        manufacturer = bytes([0] * 8 + [8, 0x80 | 17, 48])
        service = b"\x54\x00\x64"
        data = (
            bytes([len(manufacturer) + 3, 0xFF, 0x69, 0x09]) + manufacturer
            + bytes([len(service) + 3, 0x16, 0x3D, 0xFD]) + service
        )

        def event(address):
            report = b"\x00\x00" + bytes.fromhex(address)[::-1] + bytes([len(data)]) + data + b"\xc4"
            return bytes([4, 0x3E, 2 + len(report), 2, 1]) + report

        for addresses in (["000000005593", "00000000107A"], ["00000000107A", "000000005593"]):
            device = unittest.mock.Mock()
            device.event.side_effect = [*(event(address) for address in addresses), None]
            self.assertEqual([sensor["id"] for sensor in switchbot_scan.scan(device, 5)], ["107A", "5593"])

    def test_upload_requires_all_readings_accepted(self):
        sensors = [{"id": "1234", "temperatureC": 17.8, "humidity": 48}]
        with tempfile.NamedTemporaryFile() as header:
            os.chmod(header.name, 0o600)
            with patch("switchbot_upload.subprocess.run") as run:
                run.return_value.returncode = 0
                run.return_value.stdout = '{"accepted":1}'
                self.assertEqual(switchbot_upload.upload("https://example.com/ingest", header.name, sensors), 1)
                self.assertIn("-4", run.call_args.args[0])
                self.assertEqual(json.loads(run.call_args.kwargs["input"])["sensors"], sensors)
                run.return_value.stdout = '{"accepted":0}'
                with self.assertRaises(RuntimeError):
                    switchbot_upload.upload("https://example.com/ingest", header.name, sensors)
            os.chmod(header.name, 0o644)
            with self.assertRaises(PermissionError):
                switchbot_upload.upload("https://example.com/ingest", header.name, sensors)

    def test_state_update_preserves_other_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "state.json")
            with open(path, "w", encoding="utf-8") as state:
                json.dump({"appearanceMode": "dark", "memo": "unchanged"}, state)
            switchbot_upload.update_state(path, [{"id": "1234", "temperatureC": 17.8, "humidity": 48}])
            with open(path, encoding="utf-8") as state:
                result = json.load(state)
            self.assertEqual(result["appearanceMode"], "dark")
            self.assertEqual(result["memo"], "unchanged")
            self.assertEqual(result["sensors"][0]["id"], "1234")
            self.assertIsInstance(result["sensorUpdatedAt"], int)

    def test_light_update_waits_for_shared_lock(self):
        with tempfile.TemporaryDirectory() as directory:
            api = os.path.join(directory, "www", "api")
            os.makedirs(api)
            path = os.path.join(api, "state.json")
            lux = os.path.join(directory, "lux")
            with open(path, "w", encoding="utf-8") as state:
                json.dump({"appearanceMode": "light"}, state)
            with open(lux, "w", encoding="utf-8") as sensor:
                sensor.write("1 lux\n")
            env = {**os.environ, "KIOSK_HOME": directory, "KIOSK_LUX_PATH": lux}
            with open(path + ".lock", "w", encoding="utf-8") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX)
                process = subprocess.Popen(
                    ["/bin/sh", os.path.join(os.path.dirname(__file__), "kiosk-light")], env=env
                )
                try:
                    time.sleep(0.3)
                    with open(path, encoding="utf-8") as state:
                        self.assertEqual(json.load(state)["appearanceMode"], "light")
                    with open(path, "w", encoding="utf-8") as state:
                        json.dump({"appearanceMode": "light", "sensors": [{"id": "1234"}]}, state)
                    fcntl.flock(lock, fcntl.LOCK_UN)
                    deadline = time.monotonic() + 5
                    while time.monotonic() < deadline:
                        with open(path, encoding="utf-8") as state:
                            result = json.load(state)
                        if result["appearanceMode"] == "dark":
                            break
                        time.sleep(0.05)
                    self.assertEqual(result["appearanceMode"], "dark")
                    self.assertEqual(result["sensors"], [{"id": "1234"}])
                finally:
                    process.terminate()
                    process.wait(timeout=5)


if __name__ == "__main__":
    unittest.main()
