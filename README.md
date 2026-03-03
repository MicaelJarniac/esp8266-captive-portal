# ESP8266 Captive Portal

A MicroPython captive portal for the ESP8266 (e.g. Wemos D1 Mini). When the
device boots without stored WiFi credentials, it opens a WiFi access point and
serves a configuration page where users can select a network and enter a
password. Once connected, the AP shuts down and the device stays on the home
network.

This is a fork of
[anson-vandoren/esp8266-captive-portal](https://github.com/anson-vandoren/esp8266-captive-portal).

## How It Works

1. On boot the device checks for saved WiFi credentials (`wifi.creds`).
2. If valid credentials exist it connects to the stored network.
3. If there are no credentials (or the connection fails) it starts a captive
   portal:
   - Opens a WiFi access point named `ESP8266-XXXXXX` (derived from the MAC
     address).
   - Runs a DNS server that resolves **every** domain to the portal IP
     (`192.168.4.1`), so any URL triggers the setup page.
   - Runs an HTTP server on port 80 that serves a WiFi configuration form.
   - The form scans for nearby networks and lets the user pick one, or type an
     SSID manually.
   - After submitting credentials the device saves them to disk, connects to
     the chosen network, and shuts the AP down after a short delay.

## Blog Series

The original project was built as part of a blog series:

- [Part 1](https://ansonvandoren.com/posts/esp8266-captive-web-portal-part-1/)
- [Part 2](https://ansonvandoren.com/posts/esp8266-captive-web-portal-part-2/)
- [Part 3](https://ansonvandoren.com/posts/esp8266-captive-web-portal-part-3/)
- [Part 4](https://ansonvandoren.com/posts/esp8266-captive-web-portal-part-4/)

## Prerequisites

| Tool | Purpose |
|------|---------|
| [uv](https://docs.astral.sh/uv/) | Python package and project manager |
| [just](https://github.com/casey/just) | Command runner (like `make`, but simpler) |
| [mpremote](https://docs.micropython.org/en/latest/reference/mpremote.html) | MicroPython board communication (installed as a dev dependency) |
| [mpy-cross](https://pypi.org/project/mpy-cross/) | Cross-compiler for `.mpy` bytecode (installed as a dev dependency) |
| An ESP8266 board | Flashed with MicroPython firmware |

### Flashing MicroPython

If your board doesn't have MicroPython yet, flash it with `esptool` (included
in the dev dependencies):

```sh
# Erase flash
esptool.py --port /dev/ttyUSB0 erase_flash

# Flash MicroPython firmware (download from https://micropython.org/download/ESP8266_GENERIC/)
esptool.py --port /dev/ttyUSB0 --baud 460800 write_flash --flash_size=detect 0 ESP8266_GENERIC-<version>.bin
```

## Getting Started

```sh
# Clone the repository
git clone https://github.com/MicaelJarniac/esp8266-captive-portal.git
cd esp8266-captive-portal

# Install dev dependencies (mpremote, mpy-cross, esptool, stubs, etc.)
uv sync

# Install type stubs into the typings/ directory
just stubs

# Deploy to a connected board (cross-compile, copy, reset)
just load
```

For a brand-new board that needs MicroPython dependencies installed on-device:

```sh
# Wipe the board, install MicroPython deps, build, copy, and reset
just fresh
```

## `just` Commands

Run `just` with no arguments to list all available commands.

| Command | Description |
|---------|-------------|
| `just` | List all available commands |
| `just stubs` | Install MicroPython type stubs into `typings/` |
| `just wipe` | Erase **all** files from the board |
| `just deps` | Install MicroPython dependencies on-device (e.g. `typing` extensions) |
| `just cross` | Cross-compile `.py` sources to `.mpy` bytecode in `build/` (`main.py` and `boot.py` are copied as-is) |
| `just copy` | Copy everything in `build/` to the board |
| `just reset` | Reset the board |
| `just load` | **Build & deploy** — runs `cross` → `copy` → `reset` |
| `just fresh` | **Full clean deploy** — runs `wipe` → `deps` → `load` |
| `just connect` | Open a serial REPL session with the board |
| `just forget` | Delete stored WiFi credentials from the board and reset |

## Project Structure

```
src/captive-portal/
├── boot.py            # Runs on every boot — garbage collects
├── main.py            # Entry point — creates and starts CaptivePortal
├── captive_portal.py  # Orchestrator: manages AP, DNS, HTTP, and WiFi connection
├── captive_dns.py     # DNS server — resolves all queries to the portal IP
├── captive_http.py    # HTTP server — serves the config page and handles login
├── server.py          # Base TCP/UDP server class
├── credentials.py     # Reads/writes WiFi credentials to wifi.creds
├── index.html         # WiFi setup page (network scanner + manual SSID entry)
├── connected.html     # Confirmation page shown after connecting
└── __init__.py
```

### Build Output

`just cross` compiles Python modules to `.mpy` bytecode (except `main.py` and
`boot.py` which must remain plain `.py` for MicroPython's boot sequence). HTML
files are copied as-is. Everything lands in `build/`.

## Development

### Type Checking

The project is configured for [Pyright](https://github.com/microsoft/pyright)
with MicroPython stubs. Configuration lives in `pyproject.toml` under
`[tool.pyright]`. After running `just stubs`, your editor should provide
autocompletion and type checking for MicroPython APIs.

### Linting and Sessions

[Nox](https://nox.thea.codes/) is set up (via `nox-uv`) for task automation.
The `noxfile.py` is minimal — extend it with sessions as needed.

### Spelling

[cspell](https://cspell.org/) is configured via `cspell.config.yaml` with a
custom word list at `docs/wordlist.txt`.

## Usage

1. Flash MicroPython onto your ESP8266 board.
2. Deploy the captive portal with `just fresh` (first time) or `just load`
   (subsequent deploys).
3. The board starts a WiFi network named `ESP8266-XXXXXX`. Connect to it from
   your phone or laptop.
4. A setup page appears (or navigate to any URL). Select your home WiFi network,
   enter the password, and hit **Connect**.
5. The device saves the credentials, connects to your network, and turns off the
   setup AP.

To change networks later, run `just forget` to clear the stored credentials —
the captive portal will start again on the next boot.

### Customization

- **AP name**: Pass a custom `essid` to `CaptivePortal(essid=b"MyDevice")` in
  `main.py`.
- **AP password**: Pass `ap_password=b"secret123"` (must be ≥ 8 bytes) to
  require a WPA2 password for the setup network.
- **Styling**: Edit `index.html` and `connected.html` directly.

## License

[MIT](LICENSE) — Copyright (c) 2020 Anson VanDoren

## Contributors

- Anson VanDoren ([@anson-vandoren](https://github.com/anson-vandoren))
- [@grey27](https://github.com/grey27)
- [@jasonbrackman](https://github.com/jasonbrackman)
- Micael Jarniac ([@MicaelJarniac](https://github.com/MicaelJarniac))
