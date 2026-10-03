import json
import socket
import subprocess
from unittest.mock import patch

import backend
import pytest


@pytest.mark.parametrize("url", [
    "file:///C:/secret", "http://user:password@example.com", "http://example.com:8080/",
    "https://example.com/\nheader", "https://example.com/ space",
])
def test_rejects_non_public_web_inputs(url):
    with pytest.raises(ValueError):
        backend.public_url(url)


@pytest.mark.parametrize("address", ["127.0.0.1", "192.168.1.1", "100.91.115.41", "::1"])
def test_private_dns_resolution_is_rejected(address):
    with (
        patch.object(socket, "getaddrinfo", return_value=[(0, 0, 0, "", (address, 443))]),
        pytest.raises(ValueError),
    ):
        backend.public_url("https://example.com")


@pytest.mark.parametrize("url", [
    "https://youtu.be/BaW_jenozKc", "https://www.youtube.com/watch?v=BaW_jenozKc&list=other",
    "https://youtube.com/shorts/BaW_jenozKc",
])
def test_youtube_url_is_canonicalized(url):
    assert backend.youtube_url(url) == "https://www.youtube.com/watch?v=BaW_jenozKc"


@pytest.mark.parametrize("url", [
    "https://youtube.com.evil.test/watch?v=BaW_jenozKc", "file:///C:/x",
    "https://youtube.com/playlist?list=123", "https://user@youtube.com/watch?v=BaW_jenozKc",
])
def test_youtube_rejects_other_targets(url):
    with pytest.raises(ValueError):
        backend.youtube_url(url)


def test_youtube_search_passes_query_as_one_argument_without_shell():
    with patch.object(subprocess, "Popen") as popen:
        process = popen.return_value.__enter__.return_value
        process.communicate.return_value = (json.dumps({"entries": []}), "")
        process.returncode = 0
        assert backend.search_youtube('hello; echo secret', 2) == []
    args, kwargs = popen.call_args
    assert args[0][-2:] == ["--", "ytsearch2:hello; echo secret"]
    assert "--ignore-config" in args[0]
    assert kwargs["shell"] is False
    assert kwargs["stdin"] == subprocess.DEVNULL
    process.communicate.assert_called_once_with(timeout=45)


def test_youtube_timeout_is_explicit():
    with patch.object(subprocess, "Popen") as popen, patch.object(subprocess, "run") as run:
        process = popen.return_value.__enter__.return_value
        process.communicate.side_effect = [subprocess.TimeoutExpired("yt-dlp", 45), ("", "")]
        process.poll.return_value = None
        with pytest.raises(RuntimeError, match="45-second"):
            backend.search_youtube("test")
        assert "/T" in run.call_args.args[0]


def test_timeout_cleanup_still_kills_parent_when_taskkill_times_out():
    with patch.object(subprocess, "Popen") as popen, patch.object(
        subprocess, "run", side_effect=subprocess.TimeoutExpired("taskkill", 5)
    ):
        process = popen.return_value.__enter__.return_value
        process.communicate.side_effect = [subprocess.TimeoutExpired("yt-dlp", 45), ("", "")]
        process.poll.return_value = None
        with pytest.raises(subprocess.TimeoutExpired):
            backend.search_youtube("test")
        process.kill.assert_called_once()
        assert process.communicate.call_count == 2


def test_doctor_uses_only_the_read_only_diagnostic_command():
    with patch.object(backend, "run_backend_command", return_value='{"youtube": {}}') as run:
        assert backend.get_agent_reach_status() == {"youtube": {}}
    assert run.call_args.args[0][1:] == ["-m", "agent_reach.cli", "doctor", "--json"]


def test_caption_error_preserves_metadata_and_reports_failure():
    data = {"title": "Test video", "subtitles": {"en": [{"ext": "json3", "url":
        "https://www.youtube.com/api/timedtext?v=BaW_jenozKc"}]}}
    with patch.object(backend, "ytdlp", return_value=data), patch.object(
        backend, "fetch_text", return_value=""
    ):
        result = backend.read_youtube_video("https://youtu.be/BaW_jenozKc")
    assert result["title"] == "Test video"
    assert "failed" in result["caption_status"]
    assert "captions" not in result


def test_caption_endpoint_cannot_redirect_to_arbitrary_service():
    data = {"subtitles": {"en": [{"ext": "json3", "url": "https://127.0.0.1/private"}]}}
    with patch.object(backend, "ytdlp", return_value=data), patch.object(backend, "fetch_text") as fetch:
        with pytest.raises(ValueError, match="unsupported caption endpoint"):
            backend.read_youtube_video("https://youtu.be/BaW_jenozKc")
        fetch.assert_not_called()
