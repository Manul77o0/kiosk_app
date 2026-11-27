# Sensor Receiver

A dependency-free Node.js 18+ service that stores the latest temperature and
humidity readings sent by KioskApp. Readings can be used by Homebridge,
Scriptable, or other clients.

## Run

```sh
TOKEN="$(openssl rand -hex 24)" node sensor-receiver.js
```

`TOKEN` is required and must be at least 16 characters. Other environment
variables are optional:

| Variable | Default | Description |
| --- | --- | --- |
| `PORT` | `8787` | Listen port |
| `HOST` | `127.0.0.1` | Listen address |
| `DATA_FILE` | `./sensors.json` | File used to store readings |
| `MAX_AGE_SEC` | `900` | Maximum reading age for an individual sensor endpoint |

Keep the service behind a TLS reverse proxy when exposing it outside the
machine. KioskApp only uploads to HTTPS URLs.

## API

All endpoints require `Authorization: Bearer <TOKEN>`.

- `POST /ingest` accepts readings from KioskApp and returns the number accepted.
- `GET /sensors` returns the latest stored readings.
- `GET /sensors/<id>` returns one reading, or `503` if it is older than
  `MAX_AGE_SEC`. The ID is the sensor ID shown in the app.

## Configure KioskApp

In the admin page at `http://<device-ip>:8080`, open external sensor upload.
Enable uploads and set the URL to `https://<your-domain>/ingest` and the token
to the value of `TOKEN`.

## Scriptable widget

1. Install Scriptable on your iPhone.
2. Create a script and paste in [scriptable-widget.js](./scriptable-widget.js).
3. Set `BASE_URL` and `SENSOR_IDS` at the top of the script.
4. Run the script in Scriptable and enter the token. Scriptable stores it in
   the iPhone Keychain.
5. Add the script as a Home Screen or Lock Screen widget.

The widget refreshes when iOS allows and marks readings older than 15 minutes
as stale.

## Homebridge

Install `homebridge-http-temperature-humidity` and add an accessory to
`config.json` for each sensor:

```json
{
  "accessory": "HttpTemphum",
  "name": "Living Room",
  "url": "http://127.0.0.1:8787/sensors/ABCD",
  "httpMethod": "GET",
  "humidity": true,
  "cacheExpiration": 60,
  "headers": { "Authorization": "Bearer <TOKEN>" }
}
```

Replace `ABCD` with the sensor ID shown in the app. If Homebridge runs on a
different machine, use the receiver's HTTPS URL instead of `127.0.0.1`.
