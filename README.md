# Mac-Dynamic-Island

A Dynamic Island for the MacBook notch, written in Python with PyObjC.

It sits around the camera on the built-in display: clock and battery when idle, and it springs open
for the camera / microphone indicators, now playing, volume and brightness, Bluetooth connections and
focus sessions. Click it for a ring of action buttons (scroll to turn the ring), including your own
custom buttons and the settings.

## Install

Download the `.pkg` from the [latest release](https://github.com/TonyD365/Mac-Dynamic-Island/releases/latest)
and open it. It installs **Dynamic Island** into `/Applications` and starts it.

The installer is not signed with an Apple Developer ID, so macOS blocks it the first time:
open **System Settings → Privacy & Security**, scroll down and click **Open Anyway**.

Works on Apple silicon and Intel Macs, with or without a notch. macOS 12 or later.

## Updates

A released app checks this repository for the release marked **Latest**. When that release has a
higher version, the app tells you, downloads its installer, verifies the checksum and opens it.
Turn this off with **Settings → Automatic Updates**; **Check for Updates** shows the current version.

## Run from source

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python main.py
```

Use a universal2 Python (the python.org installer) if you want to build the universal app.

## Build

```bash
./build.sh
```

Produces `dist/Dynamic Island.app` and `dist/Dynamic Island.pkg` for arm64 and x86_64.

## Release

1. Commit and push to `main`.
2. On GitHub, publish a release whose tag is `v` + the version number, for example `v1.2.3`.
3. The **Release** workflow builds the installer for that version and attaches
   `Dynamic-Island-1.2.3.pkg` and its `.sha256` to the release.

Installed apps pick the update up once the release is marked **Latest** and the files are attached.
Pre-releases and drafts are ignored.

## Notes

- Lock-screen display, brightness reading and the Lock Screen button use private macOS interfaces
  and may stop working after a system update.
- Focus-mode blocking is a nudge, not a lock: blocked apps are hidden and blocked pages are replaced
  in Safari, Chrome, Edge, Brave and Arc. Force-quitting the app lifts it.
