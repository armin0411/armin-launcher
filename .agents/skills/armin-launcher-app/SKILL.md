---
name: armin-launcher-app
description: >-
  Add, update, hide, or remove applications in Armin Launcher (catalog.json,
  catalog.windows.json, ui/icons/, ui/shots/, ui/details.json), keep the
  launcher catalog and local images up to date, run tests, and push to GitHub.
---

# Armin Launcher Catalog & Maintenance Skill

Repository path: `/home/armin/Projects/armin-launcher` (GitHub: `armin0411/armin-launcher`).

## Key Files

- `catalog.json` — Linux x86_64 catalog (version 1 schema, see `AGENTS.md`).
- `catalog.windows.json` — Windows x86_64 catalog (`winget`, `zip`, `msi`, `exe`, `github_release`).
- `ui/icons/<id>.png` or `ui/icons/<id>.svg` — Local app logo served at `/icons/<id>.<ext>`.
- `ui/shots/<id>-1.jpg` (etc.) — Local app screenshots served at `/shots/<filename>`.
- `ui/details.json` — App descriptions, features, and `/shots/...` references.
- `launcher.py` — Backend engine (`validate_catalog`, `Engine`, `Server`).
- `launchcraft-ctl` — CLI helper (`list`, `validate`, `check`, `add`, `edit`, `remove`, `update-installed`).

## Behavior on Invocation

1. **Always run a maintenance pass**:
   - Check all existing apps across supported systems (Arch/Omarchy, Debian/Ubuntu/Kubuntu, Fedora, Windows 11, macOS) to see if any have gained better or newer installation/update methods (e.g. a newly published GitHub release, native `.pkg.tar.zst` / `.AppImage` / `.deb` / `.rpm` / `.msi` / `.dmg` asset, or official `pacman`/`aur`/`winget`/`brew` package).
   - Remove or update any entries whose upstream releases disappeared (`404` with no releases).
   - Verify and refresh local icons (`ui/icons/`) and local screenshots (`ui/shots/` + `ui/details.json`), ensuring all referenced files exist locally and load cleanly.
2. **If called without a specific app request**:
   - Perform the maintenance pass above, run verification tests, and push any updates to GitHub.
3. **If called with a specific app request (add / update / remove)**:
   - Perform the maintenance pass above **and** apply the requested app change:
     - **Adding**: Verify real release assets / packages per OS, save the app icon to `ui/icons/<id>.{png,svg}`, save 1–2 screenshots locally to `ui/shots/` (if available), add metadata/features to `ui/details.json`, and add entries to `catalog.json` and `catalog.windows.json`.
     - **Removing**: Remove from `catalog.json`, `catalog.windows.json`, `ui/details.json`, and delete unused `ui/icons/<id>.*` and `ui/shots/<id>-*`.

## Verify & Push to GitHub

Always validate both catalogs, run the unit tests and headless Chromium smoke test, then commit and push:

```sh
cd /home/armin/Projects/armin-launcher
./launchcraft-ctl validate
./launchcraft-ctl --catalog catalog.windows.json validate
python3 -m unittest discover -s tests -v
python3 tests/browser_smoke.py
git status -sb
git add -A catalog.json catalog.windows.json ui/details.json ui/icons/ ui/shots/
git commit -m "Update Armin Launcher catalog and local assets"
git push origin main
```
