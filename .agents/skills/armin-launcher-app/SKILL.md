---
name: armin-launcher-app
description: >-
  Add, update, hide, or remove applications in Armin Launcher (catalog.json,
  catalog.windows.json, and ui/icons/), run verification tests, and push
  changes to GitHub. Use when asked to add/remove apps or maintain Armin Launcher.
---

# Armin Launcher Catalog & Maintenance Skill

Repository path: `/home/armin/Projects/armin-launcher` (GitHub: `armin0411/armin-launcher`).

## Required Check on Every Invocation

Every time this skill is summoned, **check whether any apps in the catalog have gained better installation or update methods for each supported system** (Arch/Omarchy, Debian/Ubuntu/Kubuntu, Fedora, Windows 11, macOS — e.g. a newly published GitHub release, native `.pkg.tar.zst` / `.AppImage` / `.deb` / `.rpm` / `.msi` / `.dmg` asset, or official `pacman`/`aur`/`winget`/`brew` package). If any better method is found, update `catalog.json` / `catalog.windows.json`, validate, run the test suite, and push to GitHub.

## Key Files

- `catalog.json` — Linux x86_64 catalog (version 1 schema, see `AGENTS.md`).
- `catalog.windows.json` — Windows x86_64 catalog (`winget`, `zip`, `msi`, `exe`, `github_release`).
- `ui/icons/<id>.png` or `ui/icons/<id>.svg` — Local app logo served at `/icons/<id>.<ext>`.
- `launcher.py` — Backend engine (`validate_catalog`, `Engine`, `Server`).
- `launchcraft-ctl` — CLI helper (`list`, `validate`, `check`, `add`, `edit`, `remove`).

## Adding an App

1. **Verify sources and artifacts**:
   - **GitHub releases**: Query `https://api.github.com/repos/<owner>/<repo>/releases` to confirm exact Linux x86_64 (`*.AppImage`, `*.pkg.tar.zst`, `*.tar.gz`) and Windows (`*.zip`, `*.msi`, `*.exe`) asset names.
   - **Arch / AUR**: Verify package names with `pacman -Si <pkg>` or `https://aur.archlinux.org/rpc/v5/search/<pkg>` and check `PKGBUILD` for the installed binary name (`launch`).
   - **Windows `winget`**: Verify the exact `winget` package ID (e.g. `BlenderFoundation.Blender`).
2. **Add the app icon**:
   - Download or create a crisp PNG or SVG icon at `ui/icons/<id>.png` or `ui/icons/<id>.svg`.
   - Keep `id` lowercase alphanumeric with hyphens (`[a-z0-9][a-z0-9-]*`).
3. **Update both catalogs**:
   - Add the Linux entry to `catalog.json` (preserving version 1 schema fields: `id`, `name`, `publisher`, `category`, `tagline`, `accent`, `website`, `source`, `install`, `hidden`).
   - Add the Windows entry to `catalog.windows.json`.
   - Alternatively, use `./launchcraft-ctl add <app.json>` for `catalog.json`.

## Removing or Hiding an App

- **Hide temporarily**: Set `"hidden": true` in `catalog.json` / `catalog.windows.json`, or run:
  ```sh
  printf '%s\n' '{"hidden":true}' | ./launchcraft-ctl edit <id>
  ```
- **Remove permanently**: Delete the app object from `catalog.json` and `catalog.windows.json` (or `./launchcraft-ctl remove <id>`), and remove `ui/icons/<id>.*` if no longer needed.

## Verify & Push to GitHub

Always validate both catalogs, run the unit tests and headless Chromium smoke test, then commit and push:

```sh
cd /home/armin/Projects/armin-launcher
./launchcraft-ctl validate
./launchcraft-ctl --catalog catalog.windows.json validate
python3 -m unittest discover -s tests -v
python3 tests/browser_smoke.py
git status -sb
git add catalog.json catalog.windows.json ui/icons/
git commit -m "Update app catalog"
git push origin main
```
