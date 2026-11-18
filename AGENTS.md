# LaunchCraft catalog maintenance

`catalog.json` is the app catalog. Preserve its version 1 structure and keep entries useful and installable on Linux x86_64. Changes to the catalog do not install or remove software.

## Version 1 schema

The root object has exactly `version` (integer `1`) and `apps` (array). Each app has these required fields:

- `id`: unique, stable lowercase identifier; use letters, numbers and hyphens.
- `name`, `publisher`, `category`, `tagline`: nonempty display strings.
- `accent`: six-digit sRGB hex color, for example `#2d81ff`.
- `website`: HTTPS URL for the app.
- `source`: one of the objects below.
- `install`: one of the objects below.
- `hidden`: boolean; `true` hides an entry without deleting it.

Source objects contain only the fields shown:

| `type` | Required fields | Optional fields |
| --- | --- | --- |
| `github_release` | `repo` (`owner/repository`), `asset_pattern` (glob matching a Linux x86_64 release asset) | `prerelease` (boolean; omitted means false) |
| `arch_repo` | `package` (exact Arch repository package name) | none |
| `aur` | `package` (exact AUR package name) | none |

Install objects contain only the fields shown:

| `type` | Required fields |
| --- | --- |
| `pacman_pkg` | `package` (actual installed package name), `launch` |
| `appimage` | `binary_name`, `launch` |
| `tarball` | `bin`, `launch` |
| `pacman` | `package`, `launch` |
| `aur` | `package`, `launch` |

All fields in these objects other than `prerelease` are nonempty strings. `launch` identifies the executable to launch; `binary_name` is the installed AppImage filename and `bin` identifies the executable in a tarball. Match the install type to the source and artifact: GitHub package assets use `pacman_pkg`, AppImages use `appimage`, and tar archives use `tarball`; Arch repository and AUR packages use `pacman` and `aur`, respectively. The release filename need not equal the installed Arch package name.

## Working on entries

1. Read the existing catalog and any relevant project instructions first. Preserve stable IDs and unrelated entries. Check the upstream [Craft catalog](https://github.com/storytold/craft-launcher/blob/main/crates/core/catalog.toml) when updating suite apps.
2. Verify every new or changed repository, source and package using the publisher's current release assets, Arch package metadata (`pacman -Si` or the Arch package search), or the AUR package page/API. Verify the Linux x86_64 asset name and choose a specific glob that matches the intended GUI artifact, not CLI, checksums, signatures, or other architectures. Prefer published `.pkg.tar.zst` assets for suite apps. Verify actual package names and executables from package metadata or upstream packaging, not merely the release filename. Releases and package names can change; do not infer availability from a similarly named project.
3. Add or edit one complete entry with accurate metadata and a source/install pair. Use `hidden` for a temporary removal from display; delete an entry only when removal is intended. Avoid duplicate IDs and preserve existing IDs when renaming an app. Do not silently repurpose an ID.
4. Parse the JSON and check the root and entry fields, types, supported variants, source/install compatibility, unique IDs, color and URL formats, and nonempty strings. Check each changed glob against an actual intended release asset and each changed package against its authoritative metadata. Review the diff and report verification limits. Never execute a downloaded artifact merely to validate the catalog.

The bundled suite's upstream Arch build derives the installed package name from the desktop-file bundle ID; confirm exceptions against the actual package. Upstream release metadata and the upstream catalog are evidence, not an installation instruction. Do not alter unrelated launcher, UI, or desktop files when assigned only catalog work.

## Git workflow

After making and verifying changes in this repository (running `./launchcraft-ctl validate` and `python3 -m unittest discover -s tests -v`), commit the changes with a clear message and push to `origin main`.
