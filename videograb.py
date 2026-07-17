#!/usr/bin/env python3
"""VideoGrab downloads video from YouTube, VK, TikTok, and ~1,800 other sites with yt-dlp.

Run:  python3 videograb.py  →  open http://localhost:8742
"""
import collections
import html
import json
import mimetypes
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
import urllib.request
import uuid
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

PORT = 8742

# job ID -> {pct, phase, name, file, error, tmp}
# Jobs whose files have not been retrieved are kept until the server restarts.
JOBS = {}
SLOTS = threading.Semaphore(2)  # Run two downloads at a time.

DEPENDENCIES = {
    "yt-dlp": "yt-dlp",
    "ffmpeg": "ffmpeg",
}

ANILIBRIA_HOSTS = {"anilibria.top", "www.anilibria.top", "aniliberty.top", "www.aniliberty.top"}
ANILIBRIA_EPISODE_PATH = re.compile(r"^/anime/video/episode/([0-9a-f-]+)$", re.IGNORECASE)
TELEGRAM_HOSTS = {"t.me", "www.t.me", "telegram.me", "www.telegram.me",
                  "telegram.dog", "www.telegram.dog"}
NUXT_DATA = re.compile(
    r'<script[^>]+id=["\']__NUXT_DATA__["\'][^>]*>(.*?)</script>', re.DOTALL
)


class SourceError(Exception):
    """An error message that is safe to show to the user."""


def _anilibria_episode_id(url):
    """Return an AniLiberty episode ID, or None for other sites."""
    parsed = urllib.parse.urlsplit(url)
    if parsed.hostname not in ANILIBRIA_HOSTS:
        return None
    match = ANILIBRIA_EPISODE_PATH.fullmatch(parsed.path.rstrip("/"))
    return match.group(1) if match else None


def _nuxt_ref(data, value):
    """Resolve a value in the compact __NUXT_DATA__ format."""
    if isinstance(value, int) and 0 <= value < len(data):
        return data[value]
    return value


def _anilibria_episode(url):
    """Extract episode HLS playlists from AniLiberty page SSR data.

    yt-dlp does not have an AniLiberty extractor because the page does not
    contain a video tag. Nuxt places the episode playlist URLs in __NUXT_DATA__.
    """
    episode_id = _anilibria_episode_id(url)
    if not episode_id:
        return None
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                          "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            page = response.read().decode(response.headers.get_content_charset() or "utf-8")
    except Exception as exc:
        raise SourceError(f"Could not open the AniLiberty page: {exc}") from exc

    match = NUXT_DATA.search(page)
    if not match:
        raise SourceError("AniLiberty did not provide episode data; the page may have changed")
    try:
        data = json.loads(match.group(1))
    except json.JSONDecodeError as exc:
        raise SourceError("Could not read AniLiberty episode data") from exc

    sources = {}
    for item in data:
        if not isinstance(item, dict) or _nuxt_ref(data, item.get("id")) != episode_id:
            continue
        for key, value in item.items():
            quality = re.fullmatch(r"hls(\d+)", key)
            source = _nuxt_ref(data, value)
            if quality and isinstance(source, str) and source.startswith(("https://", "http://")):
                sources[int(quality.group(1))] = source
        break
    if not sources:
        raise SourceError("No available video streams were found for this AniLiberty episode")

    title_match = re.search(r"<title>(.*?)</title>", page, re.IGNORECASE | re.DOTALL)
    title = html.unescape(re.sub(r"\s*\|\s*Ani(?:Liberty|Libria)\s*$", "",
                                 title_match.group(1)).strip()) if title_match else "AniLiberty episode"
    return {"title": title, "sources": sources}


def _pick_anilibria_source(sources, requested_height=None):
    """Return the exact quality or the nearest one not above the request."""
    if requested_height in sources:
        return sources[requested_height]
    eligible = [height for height in sources if requested_height is None or height <= requested_height]
    return sources[max(eligible)] if eligible else sources[min(sources)]


def _safe_filename(title):
    title = re.sub(r'[<>:"/\\|?*\x00-\x1f]', " ", title).strip()
    return (title or "video")[:150].rstrip()


def _safe_title(title):
    # Do not allow path separators or yt-dlp templates in the file name.
    return _safe_filename(title).replace("%", "%%")


def _telegram_target(url):
    """Parse public Telegram post and story links."""
    parsed = urllib.parse.urlsplit(url)
    hostname = (parsed.hostname or "").lower()
    parts = [urllib.parse.unquote(part) for part in parsed.path.split("/") if part]

    username = None
    if hostname in TELEGRAM_HOSTS:
        if not parts:
            return None
        if parts[0] == "c" and len(parts) >= 3:
            return {"kind": "private", "username": parts[1], "id": parts[2]}
        if parts[0] == "s" and len(parts) >= 3 and parts[2].isdigit():
            return {"kind": "post", "username": parts[1], "id": parts[2]}
        username = parts[0]
        parts = parts[1:]
    elif hostname.endswith(".t.me") and hostname != "www.t.me":
        username = hostname[:-5]
    else:
        return None

    if len(parts) >= 2 and parts[0] == "s" and (parts[1].isdigit() or parts[1] == "live"):
        return {"kind": "story", "username": username, "id": parts[1]}
    if parts and parts[0].isdigit():
        return {"kind": "post", "username": username, "id": parts[0]}
    return None


def _telegram_post(url):
    """Extract downloadable media from a public Telegram post preview."""
    target = _telegram_target(url)
    if not target:
        return None
    if target["kind"] == "private":
        raise SourceError("Private Telegram posts require an authenticated Telegram session")
    if target["kind"] == "story":
        raise SourceError(
            "Telegram stories require an authenticated Telegram session; public t.me pages do not expose story media"
        )

    username, post_id = target["username"], target["id"]
    embed_url = f"https://t.me/{urllib.parse.quote(username)}/{post_id}?embed=1&mode=tme"
    request = urllib.request.Request(
        embed_url,
        headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                          "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            page = response.read().decode(response.headers.get_content_charset() or "utf-8")
    except Exception as exc:
        raise SourceError(f"Could not open the Telegram post: {exc}") from exc

    if "tgme_widget_message_error" in page:
        raise SourceError("Telegram did not provide a public preview for this post")

    media = []
    for kind, pattern in (
        ("video", r'<video\b[^>]*\bsrc="([^"]+)"'),
        ("audio", r'<audio\b[^>]*\bsrc="([^"]+)"'),
        ("photo", (r'class="[^"]*tgme_widget_message_photo_wrap[^"]*"[^>]*'
                   r'background-image:url\(\'([^\']+)\'\)')),
    ):
        for media_url in re.findall(pattern, page, re.IGNORECASE | re.DOTALL):
            media_url = html.unescape(media_url)
            if media_url.startswith(("https://", "http://")):
                media.append({"kind": kind, "url": media_url})

    unique_media = []
    seen = set()
    for item in media:
        if item["url"] not in seen:
            seen.add(item["url"])
            unique_media.append(item)
    if not unique_media:
        raise SourceError("No downloadable media was found in this public Telegram post")

    return {
        "title": f"Telegram @{username} post {post_id}",
        "media": unique_media,
        "embed_url": embed_url,
    }


def _media_extension(item, content_type=None):
    suffix = Path(urllib.parse.urlsplit(item["url"]).path).suffix.lower()
    if re.fullmatch(r"\.[a-z0-9]{2,5}", suffix):
        return suffix
    guessed = mimetypes.guess_extension((content_type or "").split(";", 1)[0].strip())
    if guessed == ".jpe":
        guessed = ".jpg"
    return guessed or {"video": ".mp4", "audio": ".mp3", "photo": ".jpg"}.get(item["kind"], ".bin")


def _run_direct_media_job(job, media, title, referer):
    """Download one or more direct media files and ZIP albums."""
    downloaded = []
    try:
        with SLOTS:
            if job["cancelled"]:
                return
            job["phase"] = "download"
            total_items = len(media)
            base_name = _safe_filename(title)
            for index, item in enumerate(media, 1):
                if job["cancelled"]:
                    return
                request = urllib.request.Request(
                    item["url"],
                    headers={"User-Agent": "Mozilla/5.0", "Referer": referer},
                )
                with urllib.request.urlopen(request, timeout=60) as response:
                    size = int(response.headers.get("Content-Length", 0))
                    extension = _media_extension(item, response.headers.get("Content-Type"))
                    numbered = f" {index}" if total_items > 1 else ""
                    destination = Path(job["tmp"].name) / f"{base_name}{numbered}{extension}"
                    received = 0
                    with destination.open("wb") as output:
                        while True:
                            if job["cancelled"]:
                                return
                            chunk = response.read(1024 * 256)
                            if not chunk:
                                break
                            output.write(chunk)
                            received += len(chunk)
                            item_progress = received / size if size else 0
                            job["pct"] = ((index - 1) + item_progress) / total_items * 100
                    downloaded.append(destination)

            if len(downloaded) == 1:
                job["file"] = downloaded[0]
            else:
                archive = Path(job["tmp"].name) / f"{base_name}.zip"
                job["phase"] = "processing"
                with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as output:
                    for file in downloaded:
                        output.write(file, file.name)
                job["file"] = archive
            job["name"] = job["file"].stem
            job["pct"] = 100.0
    except Exception as exc:
        job["error"] = str(exc)
    finally:
        if job["error"] or job["cancelled"]:
            job["tmp"].cleanup()


def _missing_dependencies():
    return [name for name, executable in DEPENDENCIES.items() if not shutil.which(executable)]


def _confirm(question):
    try:
        answer = input(question).strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return False
    return answer in {"y", "yes"}


def _admin_command(command):
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        return command
    if platform.system() == "OpenBSD" and shutil.which("doas"):
        return ["doas", *command]
    return ["sudo", *command]


def _is_qubes_os():
    return Path("/etc/qubes-release").exists() or "QUBES_VMNAME" in os.environ


def _install_commands(missing):
    """Return installation commands for the available package manager."""
    system = platform.system()
    packages = {"yt-dlp": "yt-dlp", "ffmpeg": "ffmpeg"}

    if system == "Windows":
        if not shutil.which("winget"):
            return None, "winget was not found. Install App Installer from Microsoft Store, then run this file again."
        winget = ["winget", "install", "--exact", "--accept-package-agreements",
                  "--accept-source-agreements", "--id"]
        package_ids = {"yt-dlp": "yt-dlp.yt-dlp", "ffmpeg": "Gyan.FFmpeg"}
        return [winget + [package_ids[name]] for name in missing], None

    if system == "Darwin":
        if not shutil.which("brew"):
            return None, ("Homebrew was not found. Install it from https://brew.sh, "
                          "then run this file again.")
        return [["brew", "install", *[packages[name] for name in missing]]], None

    if system == "OpenBSD":
        if not shutil.which("pkg_add"):
            return None, "pkg_add was not found. Install the OpenBSD package tools, then run this file again."
        requested = [packages[name] for name in missing]
        return [_admin_command(["pkg_add", "-I", *requested])], None

    if system == "Linux":
        requested = [packages[name] for name in missing]
        # Immutable Fedora-family systems apply layered packages after a reboot.
        if shutil.which("rpm-ostree"):
            return [_admin_command(["rpm-ostree", "install", *requested])], None
        if shutil.which("apt"):
            return [_admin_command(["apt", "update"]),
                    _admin_command(["apt", "install", "-y", *requested])], None
        if shutil.which("apt-get"):
            return [_admin_command(["apt-get", "update"]),
                    _admin_command(["apt-get", "install", "-y", *requested])], None
        if shutil.which("dnf"):
            return [_admin_command(["dnf", "install", "-y", *requested])], None
        if shutil.which("yum"):
            return [_admin_command(["yum", "install", "-y", *requested])], None
        if shutil.which("zypper"):
            return [_admin_command(["zypper", "--non-interactive", "install", *requested])], None
        if shutil.which("pacman"):
            return [_admin_command(["pacman", "-S", "--needed", *requested])], None
        if shutil.which("xbps-install"):
            return [_admin_command(["xbps-install", "-S"]),
                    _admin_command(["xbps-install", "-y", *requested])], None
        if shutil.which("apk"):
            return [_admin_command(["apk", "add", *requested])], None
        if shutil.which("emerge"):
            gentoo_packages = {"yt-dlp": "net-misc/yt-dlp", "ffmpeg": "media-video/ffmpeg"}
            return [_admin_command(["emerge", "--ask=n", *[gentoo_packages[name] for name in missing]])], None
        if shutil.which("eopkg"):
            return [_admin_command(["eopkg", "install", "-y", *requested])], None
        if shutil.which("nix"):
            return [["nix", "profile", "install", *[f"nixpkgs#{name}" for name in requested]]], None
        if shutil.which("guix"):
            return [["guix", "install", *requested]], None
        return None, ("No supported package manager was found (rpm-ostree, apt, dnf, yum, zypper, "
                      "pacman, xbps, apk, emerge, eopkg, Nix, or Guix).")

    return None, f"Automatic installation is not supported on: {system}."


def _refresh_path():
    """Add common package-manager directories to the current process PATH."""
    candidates = [
        "/opt/homebrew/bin", "/usr/local/bin", str(Path.home() / ".local" / "bin"),
    ]
    if platform.system() == "Windows":
        local_app_data = os.environ.get("LOCALAPPDATA")
        if local_app_data:
            candidates += [
                str(Path(local_app_data) / "Microsoft" / "WinGet" / "Links"),
                str(Path(local_app_data) / "Microsoft" / "WindowsApps"),
            ]
    path_items = os.environ.get("PATH", "").split(os.pathsep)
    additions = [folder for folder in candidates if Path(folder).is_dir() and folder not in path_items]
    if additions:
        os.environ["PATH"] = os.pathsep.join([*additions, *path_items])


def ensure_dependencies():
    missing = _missing_dependencies()
    if not missing:
        return True

    names = ", ".join(missing)
    print(f"Not found: {names}.")
    if not _confirm("Install them now? [y/N]: "):
        print("Installation cancelled.")
        return False

    if _is_qubes_os():
        print("Qubes OS detected. For a persistent installation, run this in the TemplateVM, "
              "then restart the qubes based on that template.")

    commands, problem = _install_commands(missing)
    if problem:
        print(problem)
        return False

    for command in commands:
        try:
            result = subprocess.run(command).returncode
        except OSError as exc:
            print(f"Could not start the installer: {exc}")
            return False
        if result != 0:
            print("Installation failed.")
            return False

    if any("rpm-ostree" in command for command in commands):
        print("Packages are staged for the next boot. Restart the system, then run VideoGrab again.")
        return False

    _refresh_path()
    still_missing = _missing_dependencies()
    if still_missing:
        print("Still not found after installation: " + ", ".join(still_missing))
        print("Close and reopen the terminal, then run this file again.")
        return False

    print("Dependencies installed. Checking again and starting VideoGrab…")
    os.execv(sys.executable, [sys.executable, *sys.argv])

INDEX = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>VideoGrab — Link to file</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=Unbounded:wght@500;600&family=Inter:wght@400;500;600&display=swap');
  :root{
    --bg:#0E1013; --panel:#16191E; --fg:#EDEFF2; --muted:#9CA3AF; --dim:#6B7280;
    --lime:#A3E635; --lime-hi:#BEF264; --border:rgba(255,255,255,.07);
    --ok:#4ADE80; --err:#FB7185;
  }
  *{box-sizing:border-box;margin:0}
  body{
    min-height:100dvh; display:flex; flex-direction:column; align-items:center;
    justify-content:center; gap:1.2rem; padding:1.25rem;
    background:var(--bg); color:var(--fg);
    background-image:radial-gradient(50rem 26rem at 50% -12%, rgba(163,230,53,.09), transparent);
    font-family:Inter,system-ui,sans-serif; font-size:.95rem; line-height:1.5;
  }
  .logo{display:flex;align-items:center;gap:.5rem;font-family:Unbounded,sans-serif;
        font-weight:500;font-size:1rem;color:var(--muted);user-select:none}
  .logo b{color:var(--lime);font-weight:600}
  h1{font-family:Unbounded,sans-serif;font-weight:600;text-align:center;
     font-size:clamp(1.5rem,4.5vw,2.4rem);letter-spacing:-.01em}
  h1 span{color:var(--lime)}
  .sub{color:var(--muted);text-align:center;max-width:32rem;margin-bottom:.8rem}
  main{width:100%;max-width:600px;display:flex;flex-direction:column;gap:.8rem}
  .pill{
    display:flex;align-items:center;gap:.5rem;padding:.4rem .4rem .4rem 1.15rem;
    background:var(--panel);border:1px solid var(--border);border-radius:999px;
    transition:border-color .2s, box-shadow .2s;
  }
  .pill:focus-within{border-color:var(--lime);box-shadow:0 0 0 4px rgba(163,230,53,.12)}
  .pill > svg{flex:none;color:var(--dim)}
  input{
    flex:1;min-width:0;min-height:48px;font:inherit;color:var(--fg);
    background:none;border:0;outline:none;
  }
  input::placeholder{color:var(--dim)}
  .go{
    flex:none;width:48px;height:48px;border-radius:50%;border:0;cursor:pointer;
    display:grid;place-items:center;background:var(--lime);color:var(--bg);
    transition:background .15s, transform .1s;
  }
  .go:hover:not(:disabled){background:var(--lime-hi)}
  .go:active:not(:disabled){transform:scale(.93)}
  .go:disabled{opacity:.45;cursor:default}
  .go:focus-visible{outline:2px solid var(--fg);outline-offset:2px}
  .controls{display:flex;justify-content:space-between;align-items:center;gap:.6rem;
            flex-wrap:wrap;padding:0 .3rem}
  .seg{display:flex;background:var(--panel);border:1px solid var(--border);
       border-radius:999px;padding:3px;gap:3px}
  .seg button{
    display:inline-flex;align-items:center;gap:.4rem;min-height:40px;padding:0 1.05rem;
    font:inherit;font-weight:500;color:var(--muted);background:none;border:0;
    border-radius:999px;cursor:pointer;transition:color .15s, background .15s;
  }
  .seg button:hover{color:var(--fg)}
  .seg button[aria-pressed="true"]{background:var(--lime);color:var(--bg)}
  .seg button:focus-visible{outline:2px solid var(--lime);outline-offset:2px}
  .ghost{
    display:inline-flex;align-items:center;gap:.45rem;min-height:44px;padding:0 .6rem;
    font:inherit;color:var(--muted);background:none;border:0;cursor:pointer;
    border-radius:.6rem;transition:color .15s;
  }
  .ghost:hover{color:var(--fg)}
  .ghost:focus-visible{outline:2px solid var(--lime);outline-offset:2px}
  [hidden]{display:none !important}
  #qpanel{display:flex;align-items:center;gap:.6rem;flex-wrap:wrap;
          background:var(--panel);border:1px solid var(--border);border-radius:1.4rem;
          padding:.6rem .9rem;animation:pop .18s ease-out}
  .qtitle{color:var(--muted);font-size:.85rem}
  #qopts{display:flex;gap:.4rem;flex-wrap:wrap}
  .qopt{min-height:40px;padding:0 1rem;font:inherit;font-weight:500;color:var(--fg);
        background:none;border:1px solid var(--border);border-radius:999px;cursor:pointer;
        transition:border-color .15s,color .15s}
  .qopt:hover{border-color:var(--lime);color:var(--lime)}
  .qopt:focus-visible{outline:2px solid var(--lime);outline-offset:2px}
  @keyframes pop{from{opacity:0;translate:0 -4px}}
  @media (prefers-reduced-motion:reduce){#qpanel{animation:none}}
  #dl{position:fixed;top:14px;right:14px;width:min(330px,calc(100vw - 28px));z-index:50;
      background:var(--panel);border:1px solid var(--border);border-radius:16px;
      box-shadow:0 12px 40px rgba(0,0,0,.55);padding:.8rem .95rem;
      display:flex;flex-direction:column;gap:.55rem;animation:pop .18s ease-out}
  .dl-head{display:flex;justify-content:space-between;align-items:center}
  .dl-head span{font-size:.85rem;font-weight:600}
  .dl-head button{font:inherit;font-size:.75rem;color:var(--muted);background:none;
                  border:0;cursor:pointer;padding:.3rem .4rem;border-radius:.4rem}
  .dl-head button:hover{color:var(--fg)}
  .dl-head button:focus-visible{outline:2px solid var(--lime);outline-offset:2px}
  #dl-list{display:flex;flex-direction:column;gap:.55rem;max-height:60vh;overflow-y:auto}
  .dl-item{display:flex;flex-direction:column;gap:.3rem}
  .dl-row{display:flex;align-items:center;gap:.4rem}
  .dl-name{flex:1;font-size:.8rem;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
  .dl-x{flex:none;display:grid;place-items:center;width:24px;height:24px;border:0;
        background:none;color:var(--dim);cursor:pointer;border-radius:50%;
        transition:color .15s}
  .dl-x:hover{color:var(--fg)}
  .dl-x:focus-visible{outline:2px solid var(--lime);outline-offset:1px}
  .dl-bar{height:4px;border-radius:2px;background:rgba(255,255,255,.06);overflow:hidden}
  .dl-bar i{display:block;height:100%;width:0;border-radius:2px;background:var(--lime);
            transition:width .3s ease}
  .dl-status{font-size:.72rem;color:var(--muted)}
  .dl-item.done .dl-status{color:var(--ok)}
  .dl-item.err .dl-status{color:var(--err)}
  .dl-item.err .dl-bar i{background:var(--err)}
  #status{min-height:1.4rem;font-size:.85rem;color:var(--muted);text-align:center}
  #status.err{color:var(--err)} #status.ok{color:var(--ok)}
  .sites{color:var(--dim);font-size:.8rem;text-align:center;max-width:34rem;margin-top:.8rem}
  footer{color:var(--dim);font-size:.75rem;text-align:center}
</style>
</head>
<body>
  <div class="logo">Video<b>Grab</b></div>

  <h1>Link <span>&rarr;</span> file</h1>
  <p class="sub">Video, audio, and public Telegram media — in the best available quality.</p>

  <main>
    <form id="f" class="pill">
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor"
           stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
        <path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/>
        <path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/>
      </svg>
      <input id="url" type="url" required placeholder="Paste a media link"
             aria-label="Media link" autocomplete="off" autofocus>
      <button type="submit" class="go" id="btn" aria-label="Download">
        <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor"
             stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
          <line x1="12" y1="4" x2="12" y2="17"/><polyline points="6 11 12 17 18 11"/>
          <line x1="5" y1="21" x2="19" y2="21"/>
        </svg>
      </button>
    </form>

    <div id="qpanel" hidden>
      <span class="qtitle" id="qtitle">Quality:</span>
      <div id="qopts" role="group" aria-label="Choose quality"></div>
    </div>

    <div class="controls">
      <div class="seg" role="group" aria-label="What to download">
        <button type="button" data-mode="video" aria-pressed="true">
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor"
               stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
            <rect x="2" y="5" width="14" height="14" rx="2"/><path d="m16 10 6-3v10l-6-3"/>
          </svg>
          Media
        </button>
        <button type="button" data-mode="audio" aria-pressed="false">
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor"
               stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
            <path d="M9 18V5l12-2v13"/><circle cx="6" cy="18" r="3"/><circle cx="18" cy="16" r="3"/>
          </svg>
          Audio (MP3)
        </button>
      </div>
      <button type="button" class="ghost" id="paste">
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor"
             stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
          <rect x="8" y="2" width="8" height="4" rx="1"/>
          <path d="M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2"/>
        </svg>
        Paste from clipboard
      </button>
    </div>

    <p id="status" role="status" aria-live="polite"></p>
  </main>

  <div id="dl" hidden>
    <div class="dl-head">
      <span>Downloads</span>
      <button type="button" id="dlclear">clear</button>
    </div>
    <div id="dl-list"></div>
  </div>

  <p class="sites">YouTube &middot; Telegram &middot; VK Video &middot; TikTok &middot; Instagram &middot; X &middot;
     Rutube &middot; Twitch &middot; Pornhub &middot; and 1,800+ more</p>

  <footer>Runs locally — your links are not sent anywhere. The file is saved to Downloads.</footer>

<script>
const f = document.getElementById('f'), btn = document.getElementById('btn'),
      status = document.getElementById('status'), url = document.getElementById('url'),
      qpanel = document.getElementById('qpanel'), qopts = document.getElementById('qopts'),
      qtitle = document.getElementById('qtitle');
let mode = 'video';

// Fallback list when the site does not provide its available formats.
const FALLBACK = [['max', 'Maximum'], ['1080', '1080p'], ['720', '720p'], ['480', '480p']];

document.querySelectorAll('.seg button').forEach(b => b.addEventListener('click', () => {
  mode = b.dataset.mode;
  qpanel.hidden = true;
  document.querySelectorAll('.seg button').forEach(x =>
    x.setAttribute('aria-pressed', x === b ? 'true' : 'false'));
}));

document.getElementById('paste').addEventListener('click', async () => {
  try {
    url.value = (await navigator.clipboard.readText()).trim();
    url.focus();
  } catch {
    status.className = 'err';
    status.textContent = 'The browser denied clipboard access — paste the link manually (Ctrl/Cmd+V)';
  }
});

function renderOpts(opts) {
  qtitle.textContent = 'Quality:';
  qopts.replaceChildren(...opts.map(([q, label]) => {
    const b = document.createElement('button');
    b.type = 'button'; b.className = 'qopt'; b.textContent = label;
    b.addEventListener('click', () => download(q));
    return b;
  }));
  qpanel.hidden = false;
  qopts.firstChild.focus();
}

f.addEventListener('submit', async e => {
  e.preventDefault();
  status.className = ''; status.textContent = '';
  qtitle.textContent = 'Checking available options…';
  qopts.replaceChildren();
  qpanel.hidden = false;
  btn.disabled = true;
  try {
    const r = await fetch('/probe?url=' + encodeURIComponent(url.value.trim()));
    const p = await r.json();
    if (!r.ok) throw new Error(p.error || 'server returned error ' + r.status);
    if (mode === 'audio') {
      // Best uses source VBR; presets are shown only when the audio track supports them.
      const opts = [['best', p.max_abr ? 'Best · ~' + p.max_abr + ' kbps' : 'Best']];
      for (const b of [192, 128]) if (!p.max_abr || b < p.max_abr) opts.push([String(b), b + ' kbps']);
      renderOpts(opts);
    } else {
      renderOpts(p.original_only
        ? [['max', 'Original media']]
        : p.heights.length
        ? p.heights.map((h, i) => [String(h), h + 'p' + (i === 0 ? ' · maximum' : '')])
        : FALLBACK);
    }
  } catch (err) {
    qpanel.hidden = true;
    status.className = 'err';
    status.textContent = 'Could not continue: ' + err.message;
  } finally {
    btn.disabled = false;
  }
});

const dl = document.getElementById('dl'), dlList = document.getElementById('dl-list');

document.getElementById('dlclear').addEventListener('click', () => {
  dlList.querySelectorAll('.done, .err').forEach(e => e.remove());
  if (!dlList.children.length) dl.hidden = true;
});

function addItem(label) {
  const el = document.createElement('div');
  el.className = 'dl-item';
  el.innerHTML =
    '<div class="dl-row"><div class="dl-name"></div>' +
    '<button type="button" class="dl-x" aria-label="Cancel and remove">' +
    '<svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" ' +
    'stroke-width="2" stroke-linecap="round" aria-hidden="true">' +
    '<line x1="4" y1="4" x2="12" y2="12"/><line x1="12" y1="4" x2="4" y2="12"/></svg>' +
    '</button></div>' +
    '<div class="dl-bar"><i></i></div><div class="dl-status">Queued…</div>';
  el.querySelector('.dl-name').textContent = label;
  dlList.prepend(el);
  dl.hidden = false;
  return el;
}

async function download(quality) {
  qpanel.hidden = true;
  status.className = ''; status.textContent = '';
  const u = url.value.trim();
  let id;
  try {
    const res = await fetch('/download', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({url: u, mode, quality})
    });
    if (!res.ok) {
      const {error} = await res.json().catch(() => ({error: 'server returned error ' + res.status}));
      throw new Error(error);
    }
    ({id} = await res.json());
  } catch (err) {
    status.className = 'err';
    status.textContent = 'Could not continue: ' + err.message;
    return;
  }
  url.value = '';
  let label = u;
  try { label = new URL(u).hostname.replace('www.', ''); } catch {}
  const item = addItem(label + (mode === 'audio' ? ' — audio' : ' — video'));
  const nameEl = item.querySelector('.dl-name'), barEl = item.querySelector('.dl-bar i'),
        stEl = item.querySelector('.dl-status');
  let cancelled = false;
  item.querySelector('.dl-x').addEventListener('click', () => {
    cancelled = true;
    fetch('/cancel?id=' + id).catch(() => {});
    item.remove();
    if (!dlList.children.length) dl.hidden = true;
  });
  try {
    while (!cancelled) {
      await new Promise(r => setTimeout(r, 500));
      if (cancelled) return;
      const p = await (await fetch('/progress?id=' + id)).json();
      if (p.error) throw new Error(p.error);
      if (p.name) nameEl.textContent = p.name;
      barEl.style.width = p.pct + '%';
      stEl.textContent = p.phase === 'queued' ? 'Queued…'
        : p.phase === 'processing' ? 'Processing…'
        : 'Downloading… ' + Math.round(p.pct) + '%';
      if (p.done) break;
    }
    if (cancelled) return;
    const a = document.createElement('a');
    a.href = '/file?id=' + id;
    a.download = '';
    document.body.appendChild(a); a.click(); a.remove();
    item.classList.add('done');
    barEl.style.width = '100%';
    stEl.textContent = 'Done — file saved to Downloads';
  } catch (err) {
    if (cancelled) return;
    item.classList.add('err');
    barEl.style.width = '100%';
    stEl.textContent = err.message;
  }
}
</script>
</body>
</html>"""


def _run_job(job, cmd):
    tail = collections.deque(maxlen=5)
    try:
        with SLOTS:
            if job["cancelled"]:
                return
            job["phase"] = "download"
            p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                 text=True, errors="replace")
            job["proc"] = p
            deadline = time.monotonic() + 1800
            for line in p.stdout:
                tail.append(line.strip())
                m = re.search(r"\[download\]\s+([\d.]+)%", line)
                if m:
                    job["pct"] = float(m.group(1))
                elif line.startswith(("[Merger]", "[ExtractAudio]")):
                    job["phase"], job["pct"] = "processing", 100.0
                if not job["name"]:
                    m = re.search(r"Destination: (.+)", line)
                    if m:
                        job["name"] = re.sub(r"\.f\d+$", "", Path(m.group(1).strip()).stem)
                if time.monotonic() > deadline:
                    p.kill()
                    job["error"] = "download did not finish within 30 minutes"
                    return
            p.wait()
            files = [f for f in Path(job["tmp"].name).iterdir()
                     if f.is_file() and f.suffix != ".part"]
            if p.returncode != 0 or not files:
                err = next((l for l in reversed(tail) if l.startswith("ERROR")), None)
                job["error"] = (err or (tail[-1] if tail else "yt-dlp could not process this video")).removeprefix("ERROR: ")
                return
            job["file"] = max(files, key=lambda f: f.stat().st_size)
            job["name"] = job["file"].stem
            job["pct"] = 100.0
    except Exception as e:
        job["error"] = str(e)
    finally:
        if job["error"] or job["cancelled"]:
            job["tmp"].cleanup()


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        path, _, query = self.path.partition("?")
        if path == "/":
            body = INDEX.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif path == "/progress":
            job = JOBS.get(urllib.parse.parse_qs(query).get("id", [""])[0])
            if not job:
                self._json(404, {"error": "job not found"})
                return
            self._json(200, {"pct": job["pct"], "phase": job["phase"], "name": job["name"],
                             "done": job["file"] is not None, "error": job["error"]})
        elif path == "/probe":
            u = urllib.parse.parse_qs(query).get("url", [""])[0]
            if not u.startswith(("http://", "https://")):
                self._json(400, {"error": "a link starting with http:// or https:// is required"})
                return
            try:
                telegram = _telegram_post(u)
                anilibria = _anilibria_episode(u)
            except SourceError as exc:
                self._json(422, {"error": str(exc)})
                return
            if telegram:
                self._json(200, {"title": telegram["title"], "heights": [],
                                 "max_abr": None, "original_only": True})
                return
            if anilibria:
                self._json(200, {"title": anilibria["title"],
                                 "heights": sorted(anilibria["sources"], reverse=True),
                                 "max_abr": None})
                return
            try:
                run = subprocess.run(["yt-dlp", "-J", "--no-playlist", u],
                                     capture_output=True, text=True, timeout=60)
            except subprocess.TimeoutExpired:
                self._json(422, {"error": "the site did not respond within one minute"})
                return
            if run.returncode != 0:
                lines = [l for l in run.stderr.strip().splitlines() if l]
                msg = (lines[-1] if lines else "could not read the video").removeprefix("ERROR: ")
                self._json(422, {"error": msg})
                return
            info = json.loads(run.stdout)
            fmts = info.get("formats", [])
            heights = sorted({f["height"] for f in fmts
                              if f.get("height") and f.get("vcodec") not in (None, "none")},
                             reverse=True)
            abrs = [f["abr"] for f in fmts
                    if f.get("abr") and f.get("acodec") not in (None, "none")]
            self._json(200, {"title": info.get("title", ""), "heights": heights[:6],
                             "max_abr": round(max(abrs)) if abrs else None})
        elif path == "/cancel":
            job = JOBS.pop(urllib.parse.parse_qs(query).get("id", [""])[0], None)
            if job:
                job["cancelled"] = True
                if job["proc"]:
                    job["proc"].kill()
                elif job["file"]:  # The file is already complete but has not been retrieved.
                    job["tmp"].cleanup()
            self._json(200, {"ok": True})
        elif path == "/file":
            job = JOBS.pop(urllib.parse.parse_qs(query).get("id", [""])[0], None)
            if not job or not job["file"]:
                self.send_error(404)
                return
            f = job["file"]
            try:
                self.send_response(200)
                self.send_header("Content-Type", "application/octet-stream")
                self.send_header("Content-Disposition",
                                 "attachment; filename*=UTF-8''" + urllib.parse.quote(f.name))
                self.send_header("Content-Length", str(f.stat().st_size))
                self.end_headers()
                with f.open("rb") as fh:
                    shutil.copyfileobj(fh, self.wfile)
            finally:
                job["tmp"].cleanup()
        else:
            self.send_error(404)

    def do_POST(self):
        if self.path != "/download":
            self.send_error(404)
            return
        length = int(self.headers.get("Content-Length", 0))
        try:
            data = json.loads(self.rfile.read(length))
            url = data.get("url", "").strip()
        except (json.JSONDecodeError, AttributeError):
            data, url = {}, ""
        if not url.startswith(("http://", "https://")):
            self._json(400, {"error": "a link starting with http:// or https:// is required"})
            return

        try:
            telegram = _telegram_post(url)
            anilibria = _anilibria_episode(url)
        except SourceError as exc:
            self._json(422, {"error": str(exc)})
            return

        tmp = tempfile.TemporaryDirectory()
        if telegram and data.get("mode") != "audio":
            job_id = uuid.uuid4().hex[:12]
            job = {"pct": 0.0, "phase": "queued", "name": telegram["title"],
                   "file": None, "error": None, "tmp": tmp, "proc": None, "cancelled": False}
            JOBS[job_id] = job
            threading.Thread(
                target=_run_direct_media_job,
                args=(job, telegram["media"], telegram["title"], telegram["embed_url"]),
                daemon=True,
            ).start()
            self._json(200, {"id": job_id})
            return

        ffmpeg = shutil.which("ffmpeg")
        quality = str(data.get("quality", ""))
        h = int(quality) if quality.isdigit() and 100 <= int(quality) <= 8640 else None
        if telegram:
            playable = next((item for item in telegram["media"] if item["kind"] in {"video", "audio"}), None)
            if not playable:
                tmp.cleanup()
                self._json(422, {"error": "This Telegram post contains photos but no audio track"})
                return
            source_url = playable["url"]
            out = str(Path(tmp.name) / (_safe_title(telegram["title"]) + ".%(ext)s"))
        else:
            source_url = _pick_anilibria_source(anilibria["sources"], h) if anilibria else url
            out = (str(Path(tmp.name) / (_safe_title(anilibria["title"]) + ".%(ext)s"))
                   if anilibria else str(Path(tmp.name) / "%(title).150B.%(ext)s"))
        if data.get("mode") == "audio":
            # Without ffmpeg, MP3 conversion is unavailable, so use the source audio format.
            bitrate = {"192": "192K", "128": "128K"}.get(quality, "0")  # 0 = best VBR
            cmd = (["yt-dlp", "--no-playlist", "-x", "--audio-format", "mp3",
                    "--audio-quality", bitrate, "-o", out, source_url]
                   if ffmpeg else
                   ["yt-dlp", "--no-playlist", "-f", "ba", "-o", out, source_url])
        else:
            if anilibria:
                # The link already points to one quality playlist. HLS has no separate
                # yt-dlp formats here, so quality cannot be selected through -f.
                cmd = ["yt-dlp", "--no-playlist", "-o", out, source_url]
                if ffmpeg:
                    cmd += ["--merge-output-format", "mp4"]
            elif ffmpeg:
                # Quality is the real height from /probe, or a fallback value.
                fmt = f"bv*[height<={h}]+ba/b[height<={h}]/b" if h else "bv*+ba/b"
                cmd = ["yt-dlp", "--no-playlist", "-f", fmt, "-o", out, url,
                       "--merge-output-format", "mp4"]
            else:
                # Without ffmpeg, yt-dlp cannot merge video and audio; use the best ready-made file.
                fmt = f"b[height<={h}]/b" if h else "b"
                cmd = ["yt-dlp", "--no-playlist", "-f", fmt, "-o", out, url]
        if telegram:
            cmd[1:1] = ["--add-header", f"Referer:{telegram['embed_url']}"]
        cmd.insert(1, "--newline")  # Print progress on separate lines for live updates.
        job_id = uuid.uuid4().hex[:12]
        job = {"pct": 0.0, "phase": "queued", "name": "", "file": None, "error": None,
               "tmp": tmp, "proc": None, "cancelled": False}
        JOBS[job_id] = job
        threading.Thread(target=_run_job, args=(job, cmd), daemon=True).start()
        self._json(200, {"id": job_id})

    def _json(self, code, obj):
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        if "/progress" not in str(args[0] if args else ""):
            print(self.address_string(), fmt % args)


if __name__ == "__main__":
    if not ensure_dependencies():
        raise SystemExit(1)
    ytdlp = "available" if shutil.which("yt-dlp") else "missing"
    ff = "available" if shutil.which("ffmpeg") else "missing"
    print(f"VideoGrab started: http://localhost:{PORT}   yt-dlp: {ytdlp}   ffmpeg: {ff}")
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
