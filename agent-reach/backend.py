"""Read-only MCP adapters for Agent Reach's documented public-content backends."""

import ipaddress
import json
import re
import socket
import subprocess
import sys
import time
from urllib.parse import parse_qs, urlsplit

import requests
from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

mcp = FastMCP("agent-reach-backends")
READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=True)
MAX_RESPONSE_BYTES = 2_000_000


def public_url(url: str) -> str:
    """Reject credentials, non-web schemes and private targets before sending to a reader."""
    if len(url) > 2048 or any(ord(char) < 33 for char in url):
        raise ValueError("Use a public HTTP(S) URL without whitespace.")
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("Only public HTTP(S) URLs are supported.")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("URLs containing credentials are not supported.")
    if parsed.port not in {None, 80, 443}:
        raise ValueError("Only standard web ports are supported.")
    addresses = socket.getaddrinfo(parsed.hostname, parsed.port or 443, type=socket.SOCK_STREAM)
    if not addresses or any(not ipaddress.ip_address(item[4][0]).is_global for item in addresses):
        raise ValueError("Private, loopback and reserved network addresses are not supported.")
    return url


def fetch_text(url: str, *, params: dict | None = None, headers: dict | None = None,
               deadline_at: float | None = None) -> str:
    """Fetch from a caller-selected fixed public backend, with bounded output and no redirects."""
    deadline = min(time.monotonic() + 35, deadline_at or float("inf"))
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("Backend exceeded its response deadline.")
    with requests.Session() as session:
        # Do not consume ambient proxy settings or .netrc credentials.
        session.trust_env = False
        with session.get(
            url, params=params, headers={"User-Agent": "Heretic-Agent-Reach/0.1", **(headers or {})},
            timeout=(min(8, remaining / 2), min(15, remaining / 2)),
            allow_redirects=False, stream=True,
        ) as response:
            response.raise_for_status()
            if 300 <= response.status_code < 400:
                raise ValueError("Backend redirected the request; use its final public URL.")
            chunks = []
            size = 0
            while True:
                if time.monotonic() >= deadline:
                    raise TimeoutError("Backend exceeded its response deadline.")
                chunk = response.raw.read1(65536, decode_content=True)
                if not chunk:
                    break
                size += len(chunk)
                if size > MAX_RESPONSE_BYTES:
                    raise ValueError("Backend response exceeded the 2 MB limit.")
                chunks.append(chunk)
            return b"".join(chunks).decode("utf-8", errors="replace")


def check_query(query: str) -> str:
    if not query.strip() or len(query) > 300:
        raise ValueError("Query must contain 1–300 characters.")
    return query.strip()


@mcp.tool(annotations=READ_ONLY)
def read_webpage(url: str) -> dict:
    """Read a public webpage as text using Agent Reach's Jina Reader backend. URL is sent to Jina."""
    text = fetch_text("https://r.jina.ai/" + public_url(url))
    if not text.strip():
        raise ValueError("Jina returned no page content.")
    return {"url": url, "text": text[:18000], "truncated": len(text) > 18000}


@mcp.tool(annotations=READ_ONLY)
def search_github_repositories(query: str, limit: int = 5) -> list[dict]:
    """Search public GitHub repositories without using an account or credentials."""
    if not 1 <= limit <= 10:
        raise ValueError("Limit must be between 1 and 10.")
    data = json.loads(fetch_text(
        "https://api.github.com/search/repositories",
        params={"q": check_query(query), "per_page": limit, "sort": "stars"},
        headers={"Accept": "application/vnd.github+json"},
    ))
    return [{"name": item["full_name"], "url": item["html_url"],
             "description": item.get("description"), "stars": item["stargazers_count"]}
            for item in data["items"]]


def youtube_url(url: str) -> str:
    parsed = urlsplit(url)
    if parsed.scheme != "https" or parsed.username is not None or parsed.port not in {None, 443}:
        raise ValueError("Provide an HTTPS YouTube video URL.")
    host = (parsed.hostname or "").lower()
    if host == "youtu.be":
        video_id = parsed.path.removeprefix("/")
    elif host in {"youtube.com", "www.youtube.com", "m.youtube.com"}:
        if parsed.path == "/watch":
            video_id = parse_qs(parsed.query).get("v", [""])[0]
        elif re.fullmatch(r"/(shorts|live|embed)/[A-Za-z0-9_-]{11}", parsed.path):
            video_id = parsed.path.rsplit("/", 1)[-1]
        else:
            video_id = ""
    else:
        video_id = ""
    if not re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id):
        raise ValueError("Provide one YouTube video, not a playlist or another website.")
    return "https://www.youtube.com/watch?v=" + video_id


def ytdlp(target: str, *, flat: bool = False) -> dict:
    command = [sys.executable, "-m", "yt_dlp", "--ignore-config", "--skip-download",
               "--no-playlist", "--dump-single-json", "--no-warnings", "--socket-timeout", "12",
               "--retries", "0", "--extractor-retries", "0", "--js-runtimes", "node"]
    if flat:
        command.append("--flat-playlist")
    command.extend(["--", target])
    return json.loads(run_backend_command(command, "YouTube"))


def run_backend_command(command: list[str], label: str) -> str:
    """Run a fixed backend command without inheriting the MCP input pipe."""
    with subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          text=True, encoding="utf-8", errors="replace", shell=False,
                          creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)) as process:
        try:
            stdout, stderr = process.communicate(timeout=45)
        except subprocess.TimeoutExpired as exc:
            # Keep the parent alive until taskkill can identify its Node descendants.
            try:
                if sys.platform == "win32" and process.poll() is None:
                    subprocess.run(["C:\\Windows\\System32\\taskkill.exe", "/PID", str(process.pid),
                                    "/T", "/F"], capture_output=True, timeout=5, check=False,
                                   creationflags=subprocess.CREATE_NO_WINDOW)
            finally:
                if process.poll() is None:
                    process.kill()
                process.communicate(timeout=5)
            raise RuntimeError(f"{label} backend exceeded its 45-second limit.") from exc
        if process.returncode:
            raise RuntimeError(f"{label} backend failed: " + stderr[-1500:])
    if len(stdout) > 8_000_000:
        raise ValueError(f"{label} output exceeded the size limit.")
    return stdout


@mcp.tool(annotations=READ_ONLY)
def get_agent_reach_status() -> dict:
    """Check Agent Reach backend availability. Installation checks do not prove live access."""
    return json.loads(run_backend_command(
        [sys.executable, "-m", "agent_reach.cli", "doctor", "--json"], "Agent Reach"))


def video_summary(data: dict) -> dict:
    return {"title": data.get("title"), "url": data.get("webpage_url") or data.get("url"),
            "channel": data.get("channel"), "duration_seconds": data.get("duration"),
            "description": (data.get("description") or "")[:4000]}


@mcp.tool(annotations=READ_ONLY)
def search_youtube(query: str, limit: int = 3) -> list[dict]:
    """Search public YouTube videos using Agent Reach's yt-dlp backend. Does not download video."""
    if not 1 <= limit <= 5:
        raise ValueError("Limit must be between 1 and 5.")
    data = ytdlp(f"ytsearch{limit}:{check_query(query)}", flat=True)
    return [video_summary(item) for item in data.get("entries", []) if item]


@mcp.tool(annotations=READ_ONLY)
def read_youtube_video(url: str, language: str = "en", include_captions: bool = True) -> dict:
    """Read public YouTube metadata and available captions. No login, video download or paid ASR."""
    if not re.fullmatch(r"[A-Za-z0-9-]{2,20}", language):
        raise ValueError("Use a language code such as en, ar or en-US.")
    deadline = time.monotonic() + 50
    data = ytdlp(youtube_url(url))
    result = video_summary(data)
    result["available_caption_languages"] = sorted(
        set(data.get("subtitles", {})) | set(data.get("automatic_captions", {})))
    if not include_captions:
        return result
    captions = data.get("subtitles", {}).get(language) or data.get("automatic_captions", {}).get(language, [])
    track = next((item for item in captions if item.get("ext") == "json3"), None)
    if not track:
        result["caption_status"] = "No JSON captions available in the requested language."
        return result
    parsed = urlsplit(track["url"])
    if (parsed.scheme != "https" or parsed.hostname != "www.youtube.com"
            or parsed.path != "/api/timedtext" or parsed.username is not None
            or parsed.port not in {None, 443}):
        raise ValueError("YouTube returned an unsupported caption endpoint.")
    try:
        caption_data = json.loads(fetch_text(track["url"], deadline_at=deadline))
        lines = ["".join(segment.get("utf8", "") for segment in event.get("segs", []))
                 for event in caption_data.get("events", [])]
        text = "\n".join(line.strip() for line in lines if line.strip())
        result["captions"] = text[:18000]
        result["captions_truncated"] = len(text) > 18000
        result["caption_status"] = "Retrieved" if text else "YouTube returned empty captions."
    except (requests.RequestException, ValueError, TimeoutError) as exc:
        # Preserve useful metadata while explicitly reporting caption failure.
        result["caption_status"] = f"Caption retrieval failed ({type(exc).__name__})."
    return result


if __name__ == "__main__":
    mcp.run(transport="stdio")
