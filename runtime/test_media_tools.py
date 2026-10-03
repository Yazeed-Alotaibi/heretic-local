import json
import socket
import subprocess
import threading
from unittest.mock import patch
from urllib.request import Request, urlopen

import media_tools
import pytest


@pytest.mark.parametrize("url", ["file:///C:/secret", "http://example.com/video.mp4",
                                 "https://user:pass@example.com/video.mp4", "https://example.com:8080/x",
                                 "https://example.com/\nheader"])
def test_invalid_urls_cannot_start_downloads(url):
    with patch.object(subprocess, "Popen") as popen, pytest.raises(ValueError):
        media_tools.download_video(url)
    popen.assert_not_called()


@pytest.mark.parametrize("address", ["127.0.0.1", "192.168.1.1", "100.91.115.41", "::1"])
def test_private_dns_is_rejected(address):
    with patch.object(socket, "getaddrinfo", return_value=[(0, 0, 0, "", (address, 443))]), pytest.raises(ValueError):
        media_tools.resolve_public("https://example.com/video.mp4")


@pytest.mark.parametrize("header,expected", [(None, (0, 99, False)), ("bytes=0-9", (0, 9, True)),
                                           ("bytes=90-", (90, 99, True)), ("bytes=-5", (95, 99, True))])
def test_video_ranges(header, expected):
    assert media_tools.parse_range(header, 100) == expected


@pytest.mark.parametrize("header", ["bytes=100-", "bytes=50-10", "bytes=-0", "bytes=0-1,3-4", "bytes=-"])
def test_bad_ranges_are_rejected(header):
    with pytest.raises(ValueError):
        media_tools.parse_range(header, 100)


def test_downloader_url_is_one_argument(tmp_path):
    with patch.object(media_tools.shutil, "which", return_value="ffmpeg.exe"):
        command = media_tools.video_command("https://youtube.com/watch?v=x;echo", tmp_path)
    assert command[-2:] == ["--", "https://youtube.com/watch?v=x;echo"]
    assert "--ignore-config" in command
    assert "default,-generic" in command
    assert command[command.index("-f") + 1].count("[protocol=https]") == 3


def test_proxy_rejects_private_destination_before_connecting():
    handler = object.__new__(media_tools.PublicProxy)
    handler.path = "127.0.0.1:443"
    with patch.object(socket, "getaddrinfo", return_value=[(0, 0, 0, "", ("127.0.0.1", 443))]), patch.object(socket, "create_connection") as connect:
        handler.do_CONNECT()
    connect.assert_not_called()


def test_failed_download_cleans_only_its_own_directory(tmp_path):
    saved = tmp_path / "existing-user-video"
    saved.mkdir()
    (saved / "video.mp4").write_bytes(b"keep")
    with patch.object(media_tools, "FILES", tmp_path), patch.object(media_tools, "resolve_public"), patch.object(media_tools, "download_direct", side_effect=RuntimeError("failed")), pytest.raises(RuntimeError):
        media_tools.download_video("https://example.com/video.mp4")
    assert list(tmp_path.iterdir()) == [saved]
    assert (saved / "video.mp4").read_bytes() == b"keep"


def test_redirect_to_private_network_is_rejected_before_next_request(tmp_path):
    (tmp_path / "headers.txt").write_text("HTTP/1.1 302 Found\r\nLocation: https://127.0.0.1/a.mp4\r\n")
    with patch.object(media_tools, "run_download") as run, patch.object(
        socket, "getaddrinfo", side_effect=[[(0, 0, 0, "", ("93.184.216.34", 443))],
                                           [(0, 0, 0, "", ("127.0.0.1", 443))]]
    ), pytest.raises(ValueError):
        media_tools.download_direct("https://example.com/video.mp4", tmp_path, media_tools.time.monotonic()+30)
    assert run.call_count == 1


def test_file_delivery_requires_validated_video_and_supports_range(tmp_path):
    folder = tmp_path / ("a" * 32)
    folder.mkdir()
    (folder / "video.mp4").write_bytes(b"0123456789")
    with patch.object(media_tools, "FILES", tmp_path):
        server = media_tools.ThreadingHTTPServer(("127.0.0.1", 0), media_tools.FileHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{server.server_port}/files/{folder.name}/video.mp4"
        try:
            from urllib.error import HTTPError
            with pytest.raises(HTTPError) as error:
                urlopen(base)
            assert error.value.code == 404
            (folder / "ready.json").write_text(json.dumps({"size": 10}))
            with urlopen(Request(base+"?download=1", headers={"Range": "bytes=2-5"})) as response:
                assert response.status == 206
                assert response.read() == b"2345"
                assert response.headers["Content-Disposition"].startswith("attachment")
                assert response.headers["Content-Range"] == "bytes 2-5/10"
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)
