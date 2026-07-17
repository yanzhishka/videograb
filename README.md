# VideoGrab

A local app for downloading video, audio, and public Telegram post media from a link.

## Telegram links

VideoGrab supports public Telegram post links such as:

```text
https://t.me/Telegram/429
https://t.me/s/Telegram/429
```

Posts containing one video or photo are downloaded as a regular media file. Posts containing several photos are downloaded as a ZIP archive.

Private posts and Telegram Stories require an authenticated Telegram session. Telegram does not expose their media on the public link page, so they are not available in the current public-only mode.

## YummyAnime links

Paste a title page from `old.yummyani.me/catalog/item/`. VideoGrab loads the available episodes and shows separate selectors for the episode, voice or subtitles, player, and quality.

The **Automatic** player option tries the available supported players in this order: CVH, Aksor, and Sibnet. You can also select one of these players manually. Only combinations backed by a supported downloadable player are shown.

## Start on macOS

1. Open **Terminal**: press `Cmd + Space`, type `Terminal`, then press `Enter`.
2. Type `python3 ` in Terminal and leave the trailing space.
3. Drag `videograb.py` into the Terminal window. Its full path will be inserted automatically.
4. Press `Enter`.

The command will look similar to this:

```bash
python3 /Users/your-username/Desktop/videograb/videograb.py
```

You can also enter the path manually:

```bash
cd /Users/your-username/Desktop/videograb
python3 videograb.py
```

After starting the app, open [http://localhost:8742](http://localhost:8742) in a browser, paste a link, and choose the quality.

To stop the app, return to Terminal and press `Ctrl + C`.

## Start on Windows

1. Install [Python 3](https://www.python.org/downloads/windows/). During installation, select **Add Python to PATH**.
2. Open Command Prompt: press `Win + R`, type `cmd`, then press `Enter`.
3. Type `py ` and leave the trailing space.
4. Drag `videograb.py` into the Command Prompt window. Its full path will be inserted automatically.
5. Press `Enter`.

The command will look similar to this:

```bat
py "C:\Users\Your Name\Desktop\videograb\videograb.py"
```

You can also enter the path manually:

```bat
cd /d "C:\Users\Your Name\Desktop\videograb"
py videograb.py
```

After starting the app, open [http://localhost:8742](http://localhost:8742) in a browser, paste a link, and choose the quality.

To stop the app, return to Command Prompt and press `Ctrl + C`.

## Start on Linux

1. Open Terminal from the application menu or press `Ctrl + Alt + T`.
2. Type `python3 ` and leave the trailing space.
3. Drag `videograb.py` into the Terminal window. Most desktop environments will insert its full path automatically.
4. Press `Enter`.

The command will look similar to this:

```bash
python3 /home/your-username/videograb/videograb.py
```

You can also enter the path manually:

```bash
cd /home/your-username/videograb
python3 videograb.py
```

After starting the app, open [http://localhost:8742](http://localhost:8742) in a browser, paste a link, and choose the quality.

To stop the app, return to Terminal and press `Ctrl + C`.

## Requirements

Only Python 3 is required. On first launch, VideoGrab checks for `yt-dlp` and `ffmpeg`. If either one is missing, it shows the missing programs and asks whether to install them. After installation, it checks again and starts automatically.

The app uses the system package manager:

- Windows — `winget`;
- macOS — Homebrew;
- Debian, Ubuntu, and derivatives — `apt` or `apt-get`;
- Fedora, RHEL, and derivatives — `dnf` or `yum`;
- Fedora Atomic, Silverblue, Kinoite, and other immutable RPM systems — `rpm-ostree`;
- openSUSE — `zypper`;
- Arch, Manjaro, BigLinux, and other `pacman`-based systems — `pacman`;
- Void Linux — `xbps-install`;
- Alpine Linux — `apk`;
- Gentoo — `emerge`;
- Solus — `eopkg`;
- NixOS or Nix-enabled Linux — Nix;
- GNU Guix System or Guix-enabled Linux — Guix;
- Qubes OS — the package manager of the underlying TemplateVM (`apt` or `dnf`).
- OpenBSD — `pkg_add`.

If `winget` is unavailable on Windows, install **App Installer** from Microsoft Store. If Homebrew is unavailable on macOS, install it from [brew.sh](https://brew.sh), then run `videograb.py` again.

On `rpm-ostree` systems, packages are staged for the next boot. Restart the computer after the installer finishes, then run `videograb.py` again. On Qubes OS, run the script in the TemplateVM for a persistent installation, then restart the qubes based on that template.

You can also install the dependencies manually.

macOS:

```bash
brew install python yt-dlp ffmpeg
```

Windows:

```bat
py -m pip install -U yt-dlp
winget install Gyan.FFmpeg
```

Ubuntu and Debian:

```bash
sudo apt update
sudo apt install python3 yt-dlp ffmpeg
```

rpm-ostree systems:

```bash
sudo rpm-ostree install yt-dlp ffmpeg
systemctl reboot
```

OpenBSD:

```sh
doas pkg_add -I yt-dlp ffmpeg
```
