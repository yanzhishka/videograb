# VideoGrab

A local app for downloading video or audio from a link.

## Start on macOS

1. Open **Terminal**: press `Cmd + Space`, type `Terminal`, then press `Enter`.
2. Type `python3 ` in Terminal and leave the trailing space.
3. Drag `app.py` into the Terminal window. Its full path will be inserted automatically.
4. Press `Enter`.

The command will look similar to this:

```bash
python3 /Users/your-username/Desktop/videograb/app.py
```

You can also enter the path manually:

```bash
cd /Users/your-username/Desktop/videograb
python3 app.py
```

After starting the app, open [http://localhost:8742](http://localhost:8742) in a browser, paste a link, and choose the quality.

To stop the app, return to Terminal and press `Ctrl + C`.

## Start on Windows

1. Install [Python 3](https://www.python.org/downloads/windows/). During installation, select **Add Python to PATH**.
2. Open Command Prompt: press `Win + R`, type `cmd`, then press `Enter`.
3. Type `py ` and leave the trailing space.
4. Drag `app.py` into the Command Prompt window. Its full path will be inserted automatically.
5. Press `Enter`.

The command will look similar to this:

```bat
py "C:\Users\Your Name\Desktop\videograb\app.py"
```

You can also enter the path manually:

```bat
cd /d "C:\Users\Your Name\Desktop\videograb"
py app.py
```

After starting the app, open [http://localhost:8742](http://localhost:8742) in a browser, paste a link, and choose the quality.

To stop the app, return to Command Prompt and press `Ctrl + C`.

## Start on Linux

1. Open Terminal from the application menu or press `Ctrl + Alt + T`.
2. Type `python3 ` and leave the trailing space.
3. Drag `app.py` into the Terminal window. Most desktop environments will insert its full path automatically.
4. Press `Enter`.

The command will look similar to this:

```bash
python3 /home/your-username/videograb/app.py
```

You can also enter the path manually:

```bash
cd /home/your-username/videograb
python3 app.py
```

After starting the app, open [http://localhost:8742](http://localhost:8742) in a browser, paste a link, and choose the quality.

To stop the app, return to Terminal and press `Ctrl + C`.

## Requirements

Only Python 3 is required. On first launch, VideoGrab checks for `yt-dlp` and `ffmpeg`. If either one is missing, it shows the missing programs and asks whether to install them. After installation, it checks again and starts automatically.

The app uses the system package manager:

- Windows — `winget`;
- macOS — Homebrew;
- Ubuntu/Debian — `apt`;
- Fedora — `dnf`;
- Arch Linux — `pacman`.

If `winget` is unavailable on Windows, install **App Installer** from Microsoft Store. If Homebrew is unavailable on macOS, install it from [brew.sh](https://brew.sh), then run `app.py` again.

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
