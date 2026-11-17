# Armin Launcher

**Armin Launcher** is a fast, zero-dependency local software launcher and updater for Linux built with Python's standard library and plain HTML, CSS, and JavaScript. No pip packages, Node.js, or background daemons required — it binds only to an ephemeral `127.0.0.1` port, opens in Chromium app mode, and exits cleanly when you close the window.

[![Download Armin Launcher](https://img.shields.io/badge/%E2%AC%87%EF%B8%8F_Download_Armin_Launcher-Latest_Release-2d81ff?style=for-the-badge&logo=github&logoColor=white)](https://github.com/armin0411/armin-launcher/archive/refs/heads/main.zip)

> Prefer Git? Clone and launch in seconds:
> ```sh
> git clone https://github.com/armin0411/armin-launcher.git
> cd armin-launcher
> python3 launcher.py
> ```

---

## Quick Start

### Requirements
- **Python 3.12+** (standard library only)
- **Chromium** (or Chromium-based browser) for the desktop UI
- Optional for Arch Linux package installs: `pacman`, `pkexec`, and `yay` or `paru` for AUR entries

### Run directly
```sh
python3 launcher.py
```

### Install desktop shortcut (optional)
Registers a per-user `.desktop` entry and `~/.local/bin` wrappers without touching system keybindings:
```sh
./install-desktop
```

### Headless / custom port
```sh
python3 launcher.py --no-browser --port 8765
python3 launcher.py --headless-server --catalog /tmp/my-catalog.json
```

---

## Features

- **Unified App Library** — Manage GitHub releases (`.pkg.tar.zst`, `.AppImage`, `.tar.*`), Arch repository packages, and AUR packages from one interface.
- **On-Demand Update Checks** — No background polling; click **Refresh** when you want to check for new releases (with ETag caching and GitHub rate-limit fallback).
- **Resumable, Verified Downloads** — Interrupted downloads resume via HTTP `Range` requests and are verified against publisher `SHA256SUMS` or asset digests before installation.
- **Batch Updates** — **Update All** downloads selected release packages and applies them in a single `pkexec pacman -U` transaction.
- **Grid & Compact Table Views** — Switch between card grid and dense table view, filter by `All`, `Installed`, `Updates`, or `Hidden`, search instantly, and toggle dark/light themes or UI zoom (`Ctrl`/`Cmd` `+`, `-`, `0`).
- **Live Catalog Editing** — Add apps via the **Add App** modal or edit `catalog.json` externally; changes appear without restarting.

---

## CLI (`launchcraft-ctl`)

Manage and validate your catalog from the terminal:

```sh
./launchcraft-ctl list
./launchcraft-ctl list --json
./launchcraft-ctl validate
./launchcraft-ctl check                      # installed vs cached latest versions
./launchcraft-ctl check photocraft --refresh
./launchcraft-ctl add /path/to/app.json
printf '%s\n' '{"hidden":true}' | ./launchcraft-ctl edit photocraft
./launchcraft-ctl remove some-app            # removes catalog entry only
```

---

## Security & Architecture

- **Local-only server**: Binds strictly to `127.0.0.1` on an ephemeral port, rejects foreign origins, and requires a per-session token (`secrets.token_urlsafe`) on all mutating `POST` requests.
- **No external UI assets**: All HTML, CSS, JavaScript, and app icons are served locally with a strict Content Security Policy.
- **Safe extraction & execution**: Tarball extraction rejects path traversal, device files, and unsafe links; launch commands are parsed without a shell.
- **User data locations**:
  - Downloads cache: `~/.cache/launchcraft/downloads/`
  - App state & tarballs: `~/.local/share/launchcraft/`
  - AppImages: `~/Applications/`

---

## Verification

Run the unit/integration test suite (uses temporary homes/catalogs and mocked package commands):
```sh
python3 -m unittest discover -s tests -v
```

Run the headless Chromium UI smoke test:
```sh
python3 tests/browser_smoke.py /tmp/armin-launcher-ui-check
```
