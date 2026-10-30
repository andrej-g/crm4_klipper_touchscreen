# Raspberry Pi configuration

The bridge needs Python 3.9+, a working UART (or TCP emulator), a network path to
Moonraker and permission to open the device. Raspberry Pi OS Lite **64-bit** is
recommended; a desktop is optional. Hardware testing used a Pi 400 and Python
3.13. Other boards/OS releases need their own UART mapping checked.

## OS and serial port

Use Raspberry Pi Imager to install Raspberry Pi OS on the Pi's microSD. Configure
your own username/password, SSH key, network, correct Wi-Fi country, keyboard and
timezone. Boot and update with `sudo apt update && sudo apt full-upgrade`.

On **Pi 400 / Pi 4 / Zero 2 W**, a reliable option is to dedicate the PL011 UART
to the GPIO header (this disables Bluetooth):

1. Run `sudo raspi-config` → Interface Options → Serial Port: serial login shell
   **No**, serial hardware **Yes**.
2. Back up `/boot/firmware/config.txt` (`/boot/config.txt` on older images), then
   add under an applicable `[all]` section:

   ```ini
   enable_uart=1
   dtoverlay=disable-bt
   ```

3. Run `sudo systemctl disable --now hciuart` if that service is installed.
4. Ensure the serial UART is not used by a getty: for this mapping,
   `sudo systemctl mask --now serial-getty@serial0.service serial-getty@ttyAMA0.service`.
5. Add your login user to `dialout`: `sudo usermod -aG dialout "$USER"` (also done
   by the installer's `--install-deps`). **Reboot** so the user systemd manager
   and your login both acquire the new group membership.

After reboot:

```sh
readlink -f /dev/serial0
ls -l /dev/serial0 /dev/ttyAMA0
id
cat /proc/cmdline
sudo lsof /dev/serial0       # install lsof if needed; no owner before bridge/flash
```

On the tested Pi 400 configuration `/dev/serial0` resolves to `/dev/ttyAMA0`,
GPIO14/15 on physical pins 8/10. There should be no `console=serial0,...`,
`console=ttyAMA0,...` or another serial-console owner. Leave unrelated boot
arguments intact. Do not assume the same mapping on Pi 5, USB adapters or other
boards; use a verified device path (`/dev/serial/by-id/...` is useful for USB).

References: [official UART configuration](https://www.raspberrypi.com/documentation/computers/configuration.html#configure-uarts),
[official OS installation](https://www.raspberrypi.com/documentation/computers/getting-started.html).

## Screen wiring

The tested stock CR-M4 module is a DACAI 4.3-inch resistive serial HMI, identified
by `4SZCX48800M043_1010_1T`. It has its own processor; it is not an HDMI/DSI Linux
desktop display. Its UI uses 480×800 portrait coordinates.

On this board, J5 viewed **from the back of the PCB**, GND square pad first:

| Pin | Signal | Pi connection |
|---|---|---|
| 1 | GND | common GND, e.g. physical pin 6 |
| 2/3 | screen TX / DOUT (pair common) | Pi RX, GPIO15 / physical pin 10 |
| 4/5 | screen RX / DIN (pair common) | Pi TX, GPIO14 / physical pin 8 |
| 6 | +5 V supply | verified regulated screen supply |

Use one pin from each common TX/RX pair. Validate your board revision and cable
orientation by continuity before wiring; a mating cable can reverse the visual
order. With power removed, check for unintended shorts. The tested unit drew
0.166 A from a 5 V bench supply and TX measured 3.3 V relative to GND. This is
one operating-point reading, not a maximum/startup-current specification.

Measure your screen's signal level before attaching Pi GPIO. Verified 3.3 V UART
can connect directly; **Pi GPIO is not 5 V tolerant**. Use appropriate level
translation if needed. Screen power and logic voltage are different quantities.
Never power this 5 V-marked module from 12/24 V or from Pi 3.3 V.

Bench bring-up used separate Pi USB-C and screen bench supplies, with common
GND and **no connection between their +5 V outputs**. Remove the printer's
original screen harness while testing; do not connect a second TX driver or
screen power source. Changes to wiring require both endpoints powered off.
Avoid driving an unpowered screen through its signal pins. Powering the screen
from Pi 5 V later requires a measured total power budget.

UART settings: **115200, 8 data bits, no parity, 1 stop bit, no flow control**.
Stop the service before opening the same port for a terminal, capture or flash.

## Networking and permissions

The bridge may run on the Klipper Pi or on a separate Pi. Set `moonraker` to the
actual host URL. From this Pi, check `curl --fail http://PRINTER_IP:7125/server/info`.
For a 401/403, supply `api_key` privately or narrowly configure Moonraker trusted
clients for this Pi; do not expose Moonraker publicly or disable authentication
for an entire network just to make the example work.

A user service works without root once device permissions are correct. User
services do not inherit your terminal's activated venv or shell environment; the
generated unit uses the clone's `.venv/bin/python` and an explicit config path.
Use `sudo loginctl enable-linger "$USER"` to run the user manager at boot without
logging in. See [service installation](installation.md).
