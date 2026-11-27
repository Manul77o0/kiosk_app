# Echo Show 5 Linux display

This experimental configuration displays the Android app's HTML on an
amazon-checkers device with the downstream framebuffer kernel. It uses Xorg,
Firefox and a loopback-only HTTP server. The screen rotation and touchscreen
matrix are specific to this device.

The page uses `www/api/state.json`; its initial coordinates are the Android
app's defaults. The Linux configuration does not provide the Android admin server or automatic
updates. An experimental SwitchBot sensor service is described below; the
standard postmarketOS kernel does not include a working Bluetooth driver.
The optional `kiosk-light` service enables the device's ambient light sensor
and updates the page's appearance below 70 lux and above 120 lux. Values in
between retain the current mode.

The dependencies are `xorg-server`, `xf86-video-fbdev`,
`xf86-input-libinput`, `firefox-esr`, `font-noto-cjk`, `font-noto-emoji`,
`busybox-extras`, `xinput`, `xdotool`, and `xset`. The light service also
requires `jq`. Enable `kiosk-ui` in the
OpenRC default runlevel; its dependencies start Xorg and the local web server.
Keep USB SSH available while testing. The system clock must be correct for
weather requests over HTTPS.

## Installation

Copy this repository to the device, then run these commands from its root.
Replace `user01` and `/home/user01` with the kiosk user and home directory.
The user must already exist, and the target files must not contain settings
you want to keep.

```sh
mkdir -p "$HOME/.local/share/kiosk-display/www/api" \
    "$HOME/.local/share/kiosk-display/firefox-profile"
cp app/src/main/assets/index.html "$HOME/.local/share/kiosk-display/www/index.html"
cp linux/state.json "$HOME/.local/share/kiosk-display/www/api/state.json"
cp linux/user.js "$HOME/.local/share/kiosk-display/firefox-profile/user.js"
sudo install -d /etc/kiosk-display /usr/local/libexec
sudo install -m 644 linux/xorg.conf /etc/kiosk-display/xorg.conf
printf 'KIOSK_USER="user01"\nKIOSK_HOME="/home/user01/.local/share/kiosk-display"\n' |
    sudo tee /etc/kiosk-display/config >/dev/null
sudo install -m 755 linux/kiosk-display /usr/local/libexec/kiosk-display
sudo install -m 755 linux/kiosk-xorg linux/kiosk-web linux/kiosk-ui /etc/init.d/
sudo rc-update -u
sudo rc-service kiosk-ui start
sudo rc-update add kiosk-ui default
```

To enable automatic appearance on this device:

```sh
sudo install -m 755 linux/kiosk-light /usr/local/libexec/kiosk-light
sudo install -m 755 linux/kiosk-light-service /etc/init.d/kiosk-light
sudo rc-update -u
sudo rc-service kiosk-light start
sudo rc-update add kiosk-light default
```

The browser profile enables Firefox's X11 touch events, while the launcher
sets the touchscreen transform and sizes the browser without a window manager.
Edit `www/api/state.json` to change the displayed location, memo or appearance.
The web server listens only on `127.0.0.1:18088`.

## Experimental SwitchBot sensors

The optional service uses the MT7668 `/dev/stpbt` H4 interface, scans for
SwitchBot indoor and outdoor meter advertisements, and sends readings every
60 seconds using the Android app's `/ingest` JSON format. It requires Python 3,
curl, `flock`, and a separately built `btmtksdio.ko` for the running kernel.
Sensors appear in ascending order of their four-character IDs.
The tested driver is Amazon's
[`android_kernel_amazon_mt76x8-bt`](https://github.com/amazon-oss/android_kernel_amazon_mt76x8-bt)
at commit `bd0ada1c07fcd58ee34c6f84b1c45bf3bf4fbe34`, version
`v0.0.1.00_2022121401`. A module built for another kernel or architecture
cannot be used. The module is experimental, shares hardware with Wi-Fi, and
has not been validated on other devices or kernels.

The service needs `kiosk-web`, `wg-quick.wg0`, and the ambient-light service
updated from this directory. The kernel module must be installed as
`/usr/local/lib/kiosk-sensors/btmtksdio.ko`; install `switchbot_scan.py` and
`switchbot_upload.py` in `/usr/local/libexec`, and install `kiosk-sensors` in
`/etc/init.d/`. Set `/etc/kiosk-display/sensors` to:

```sh
KIOSK_SENSOR_URL="https://example.com/ingest"
KIOSK_SENSOR_HEADER="/home/user01/.local/share/kiosk-display/sensor-authorization"
```

The header file contains one `Authorization: Bearer ...` line. Keep it outside
`www`, owned by the kiosk user, and mode `600`; never put the token in the URL
or service configuration. The service uses IPv4 for HTTPS, reports failures
to syslog, and retries on the next cycle. Sensor values older than five minutes
are hidden from the display. Start and test it before adding `kiosk-sensors` to
the default runlevel. The light and sensor services use the same lock when
updating `state.json`.
