"""Bounded video downloads and private phone delivery for Heretic."""

import ipaddress
import json
import re
import select
import shutil
import socket
import subprocess
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urljoin, urlsplit

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

ROOT = Path(__file__).resolve().parent
FILES = ROOT / "media-files"
MAX_BYTES = 500 * 1024 * 1024
MAX_STORED_BYTES = 5 * 1024 * 1024 * 1024
PUBLIC_BASE = "http://desktop-7ov7vat.tail4c4266.ts.net:8080/files"
MCP = FastMCP("heretic-media")
DOWNLOAD_LOCK = threading.Lock()


class PublicProxy(BaseHTTPRequestHandler):
    """HTTPS-only downloader proxy that checks and pins every connection."""

    def do_CONNECT(self):
        upstream = None
        try:
            _host, address = resolve_public("https://" + self.path)
            upstream = socket.create_connection((address.strip("[]"), 443), timeout=10)
            self.send_response(200)
            self.end_headers()
            self.connection.setblocking(False)
            upstream.setblocking(False)
            deadline = time.monotonic() + 300
            while time.monotonic() < deadline:
                readable, _, _ = select.select([self.connection, upstream], [], [], 1)
                for source in readable:
                    data = source.recv(65536)
                    if not data:
                        return
                    destination = upstream if source is self.connection else self.connection
                    destination.settimeout(10)
                    destination.sendall(data)
                    destination.setblocking(False)
        except (OSError, ValueError):
            return
        finally:
            if upstream is not None:
                upstream.close()
            self.close_connection = True

    def log_message(self, format, *args):
        return


def resolve_public(url: str) -> tuple[str, str]:
    parsed = urlsplit(url)
    if (len(url) > 3000 or any(ord(char) < 33 for char in url)
            or parsed.scheme != "https" or not parsed.hostname
            or parsed.username is not None or parsed.password is not None
            or parsed.port not in {None, 443}):
        raise ValueError("Use a public HTTPS video URL without embedded credentials.")
    addresses = socket.getaddrinfo(parsed.hostname, 443, type=socket.SOCK_STREAM)
    if not addresses or any(not ipaddress.ip_address(item[4][0]).is_global for item in addresses):
        raise ValueError("Private, loopback and reserved destinations are not supported.")
    address = addresses[0][4][0]
    if ":" in address:
        address = f"[{address}]"
    return parsed.hostname, address


def stored_bytes(folder: Path) -> int:
    return sum(path.stat().st_size for path in folder.rglob("*")
               if path.is_file() and not path.is_symlink())


def terminate_tree(process: subprocess.Popen) -> None:
    try:
        if sys.platform == "win32" and process.poll() is None:
            subprocess.run(["C:\\Windows\\System32\\taskkill.exe", "/PID", str(process.pid),
                            "/T", "/F"], capture_output=True, timeout=5, check=False,
                           creationflags=subprocess.CREATE_NO_WINDOW)
    finally:
        if process.poll() is None:
            process.kill()
        process.wait(timeout=5)


def run_download(command: list[str], job: Path, deadline: float) -> None:
    with ((job / "download.log").open("wb") as log,
          subprocess.Popen(command, cwd=job, stdin=subprocess.DEVNULL, stdout=log,
                              stderr=log, shell=False,
                              creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)) as process):
            while process.poll() is None:
                if time.monotonic() >= deadline or stored_bytes(job) > MAX_BYTES:
                    terminate_tree(process)
                    raise RuntimeError("Download exceeded its five-minute or 500 MB limit.")
                time.sleep(0.25)
            if process.returncode:
                raise RuntimeError("The website download failed. It may require login or block downloads.")


def download_direct(url: str, job: Path, deadline: float) -> None:
    """Pin each redirect's public IP while preserving HTTPS hostname verification."""
    for _ in range(4):
        host, address = resolve_public(url)
        remaining = int(deadline - time.monotonic())
        if remaining < 1:
            raise RuntimeError("Download exceeded its five-minute limit.")
        headers = job / "headers.txt"
        output = job / "video.mp4"
        command = ["C:\\Windows\\System32\\curl.exe", "--disable", "--silent", "--show-error",
                   "--noproxy", "*", "--proto", "=https", "--connect-timeout", "10",
                   "--max-time", str(remaining), "--max-filesize", str(MAX_BYTES),
                   "--resolve", f"{host}:443:{address}", "--dump-header", str(headers),
                   "--output", str(output), "--url", url]
        run_download(command, job, deadline)
        header_text = headers.read_text(encoding="iso-8859-1")
        status_lines = re.findall(r"^HTTP/\S+ (\d{3})", header_text, flags=re.MULTILINE)
        if not status_lines:
            raise RuntimeError("The download returned no HTTP status.")
        status = int(status_lines[-1])
        if status in {301, 302, 303, 307, 308}:
            locations = re.findall(r"^location:\s*(.*?)\r?$", header_text,
                                   flags=re.MULTILINE | re.IGNORECASE)
            if not locations:
                raise RuntimeError("The video redirect had no destination.")
            url = urljoin(url, locations[-1])
            continue
        if status != 200:
            raise RuntimeError(f"The video server returned HTTP {status}.")
        return
    raise RuntimeError("Too many video redirects.")


def video_command(url: str, job: Path) -> list[str]:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("FFmpeg is unavailable.")
    return [sys.executable, "-m", "yt_dlp", "--ignore-config", "--no-cache-dir",
            "--no-playlist", "--use-extractors", "default,-generic", "--no-progress",
            "--socket-timeout", "15", "--retries", "0", "--fragment-retries", "0",
            "--js-runtimes", "node", "--ffmpeg-location", ffmpeg,
            "--max-filesize", str(MAX_BYTES), "--match-filters", "!is_live & duration<=1800",
            "-f", "bv*[protocol=https][height<=720][ext=mp4][vcodec^=avc1]+ba[protocol=https][ext=m4a]/b[protocol=https][height<=720][ext=mp4]",
            "--postprocessor-args", "Merger+ffmpeg_i:-protocol_whitelist file,pipe -f mov",
            "--merge-output-format", "mp4", "--no-overwrites", "--write-info-json",
            "-o", str(job / "video.%(ext)s"), "--", url]


@MCP.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False,
                                     openWorldHint=True))
def download_video(url: str) -> dict:
    """Download one public video and return a private phone download link. Up to 500 MB and 30 minutes.

    Supports public sites handled by yt-dlp and direct HTTPS MP4 URLs. No playlists, live streams,
    browser cookies or login. Takes up to five minutes. Give the returned markdown link to the user.
    """
    resolve_public(url)
    if not DOWNLOAD_LOCK.acquire(blocking=False):
        raise RuntimeError("Another video is downloading. Wait for it to finish.")
    try:
        FILES.mkdir(exist_ok=True)
        if stored_bytes(FILES) > MAX_STORED_BYTES - MAX_BYTES:
            raise RuntimeError("Saved videos have reached the 5 GB storage limit.")
        job_id = uuid.uuid4().hex
        job = FILES / job_id
        job.mkdir()
        deadline = time.monotonic() + 300
        if urlsplit(url).path.lower().endswith(".mp4"):
            download_direct(url, job, deadline)
        else:
            proxy = ThreadingHTTPServer(("127.0.0.1", 0), PublicProxy)
            proxy.daemon_threads = True
            thread = threading.Thread(target=proxy.serve_forever, daemon=True)
            thread.start()
            try:
                command = video_command(url, job)
                command[3:3] = ["--proxy", f"http://127.0.0.1:{proxy.server_port}"]
                run_download(command, job, deadline)
            finally:
                proxy.shutdown()
                proxy.server_close()
                thread.join(timeout=2)
        video = job / "video.mp4"
        if not video.is_file() or not 0 < video.stat().st_size <= MAX_BYTES:
            raise RuntimeError("The download did not produce an MP4 within the size limit.")
        ffprobe = shutil.which("ffprobe")
        if not ffprobe:
            raise RuntimeError("FFprobe is unavailable; cannot validate the downloaded video.")
        probe = subprocess.run([ffprobe, "-v", "error", "-f", "mov", "-protocol_whitelist", "file,pipe", "-show_entries",
                                "format=duration:stream=codec_type", "-of", "json", str(video)],
                               stdin=subprocess.DEVNULL, capture_output=True, text=True,
                               timeout=15, check=True,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        metadata = json.loads(probe.stdout)
        if not any(stream.get("codec_type") == "video" for stream in metadata.get("streams", [])):
            raise RuntimeError("The downloaded file contains no video stream.")
        duration = float(metadata.get("format", {}).get("duration", 0))
        if not 0 < duration <= 1800:
            raise RuntimeError("The downloaded video exceeds 30 minutes or has no known duration.")
        # The file server exposes only downloads whose validation has completed.
        (job / "ready.json").write_text(json.dumps({"size": video.stat().st_size,
                                                    "duration": duration}), encoding="utf-8")
        link = f"{PUBLIC_BASE}/{job_id}/video.mp4"
        return {"download_url": link + "?download=1", "preview_url": link,
                "markdown": f"[Download video]({link}?download=1)",
                "size_mb": round(video.stat().st_size / 1024 / 1024, 2),
                "duration_seconds": round(duration, 2)}
    except Exception:
        # Only this attempt's UUID directory is disposable; saved videos remain intact.
        if "job" in locals() and job.parent == FILES:
            shutil.rmtree(job)
        raise
    finally:
        DOWNLOAD_LOCK.release()


def parse_range(value: str | None, size: int) -> tuple[int, int, bool]:
    if value is None:
        return 0, size - 1, False
    match = re.fullmatch(r"bytes=(\d*)-(\d*)", value)
    if not match or not any(match.groups()):
        raise ValueError("Invalid range")
    first, last = match.groups()
    if first:
        start = int(first)
        end = min(int(last), size - 1) if last else size - 1
    else:
        length = int(last)
        if length <= 0:
            raise ValueError("Invalid range")
        start, end = max(0, size - length), size - 1
    if start >= size or start > end:
        raise ValueError("Invalid range")
    return start, end, True


class FileHandler(BaseHTTPRequestHandler):
    def do_HEAD(self):
        self.serve_file(head_only=True)

    def do_GET(self):
        self.serve_file(head_only=False)

    def serve_file(self, head_only: bool):
        parsed = urlsplit(self.path)
        if parsed.path == "/health":
            data = b'{"service":"heretic-media-files"}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            if not head_only:
                self.wfile.write(data)
            return
        match = re.fullmatch(r"/(?:files/)?([a-f0-9]{32})/video\.mp4", parsed.path)
        if not match:
            self.send_error(404)
            return
        folder = FILES / match[1]
        video = folder / "video.mp4"
        if (folder.is_symlink() or video.is_symlink() or not video.is_file()
                or not (folder / "ready.json").is_file()):
            self.send_error(404)
            return
        size = video.stat().st_size
        try:
            start, end, partial = parse_range(self.headers.get("Range"), size)
        except ValueError:
            self.send_response(416)
            self.send_header("Content-Range", f"bytes */{size}")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        self.send_response(206 if partial else 200)
        self.send_header("Content-Type", "video/mp4")
        self.send_header("Content-Length", str(end - start + 1))
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", "private, max-age=3600")
        self.send_header("Content-Disposition", 'attachment; filename="video.mp4"'
                         if parsed.query == "download=1" else 'inline; filename="video.mp4"')
        if partial:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.end_headers()
        if not head_only:
            with video.open("rb") as source:
                source.seek(start)
                remaining = end - start + 1
                try:
                    while remaining:
                        chunk = source.read(min(65536, remaining))
                        if not chunk:
                            break
                        self.wfile.write(chunk)
                        remaining -= len(chunk)
                except (BrokenPipeError, ConnectionResetError):
                    return

    def log_message(self, format, *args):
        return


if __name__ == "__main__":
    if sys.argv[1:] == ["--serve-files"]:
        ThreadingHTTPServer(("127.0.0.1", 8082), FileHandler).serve_forever()
    elif not sys.argv[1:]:
        MCP.run(transport="stdio")
    else:
        raise SystemExit("Unknown command")
