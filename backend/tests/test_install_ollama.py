"""Exercise install recovery without network access or running Ollama."""

from __future__ import annotations

import hashlib
import io
import json
import zipfile

import pytest

from scripts import install_ollama


def archive_bytes() -> bytes:
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as package:
        package.writestr("ollama.exe", b"example binary")
        package.writestr("lib/ollama/example.dll", b"example library")
    return stream.getvalue()


def release_asset(content: bytes) -> dict:
    return {
        "name": "ollama-windows-amd64.zip",
        "browser_download_url": "https://example.invalid/ollama.zip",
        "size": len(content),
        "digest": f"sha256:{hashlib.sha256(content).hexdigest()}",
    }


def response(data: bytes, status: int, length: int, content_range: str | None = None) -> io.BytesIO:
    stream = io.BytesIO(data)
    stream.status = status
    stream.headers = {"Content-Length": str(length)}
    if content_range:
        stream.headers["Content-Range"] = content_range
    return stream


@pytest.fixture
def windows_installer(tmp_path, monkeypatch):
    monkeypatch.setattr(install_ollama, "ROOT", tmp_path)
    monkeypatch.setattr(install_ollama.sys, "platform", "win32")
    monkeypatch.setattr(install_ollama.platform, "machine", lambda: "AMD64")
    monkeypatch.setattr(install_ollama.shutil, "which", lambda _: None)
    return tmp_path / ".runtime"


def test_install_download_resumes_and_reuses_verified_cache(tmp_path, monkeypatch):
    content = archive_bytes()
    size, split = len(content), 40
    asset = release_asset(content)
    archive = tmp_path / asset["name"]
    responses = iter((
        response(content[:split], 200, size),
        response(content[split:], 206, size - split, f"bytes {split}-{size - 1}/{size}"),
    ))
    ranges = []

    def urlopen(request, timeout):
        ranges.append(request.get_header("Range"))
        return next(responses)

    monkeypatch.setattr(install_ollama.urllib.request, "urlopen", urlopen)
    with pytest.raises(RuntimeError, match="下载中断"):
        install_ollama.obtain_archive(archive, "v-test", asset)
    assert not archive.exists()
    assert next(tmp_path.glob("*.part")).read_bytes() == content[:split]

    install_ollama.obtain_archive(archive, "v-test", asset)
    install_ollama.obtain_archive(archive, "v-test", asset)
    assert ranges == [None, f"bytes={split}-"]
    assert archive.read_bytes() == content
    assert not list(tmp_path.glob("*.part"))


def test_legacy_partial_does_not_accept_unexpected_range(tmp_path, monkeypatch):
    content = archive_bytes()
    size, split = len(content), 40
    asset = release_asset(content)
    archive = tmp_path / asset["name"]
    archive.write_bytes(content[:split])

    def urlopen(request, timeout):
        assert request.get_header("Range") == f"bytes={split}-"
        return response(content[split + 1:], 206, size - split - 1, f"bytes {split + 1}-{size - 1}/{size}")

    monkeypatch.setattr(install_ollama.urllib.request, "urlopen", urlopen)
    with pytest.raises(RuntimeError, match="续传范围"):
        install_ollama.obtain_archive(archive, "v-test", asset)
    assert next(tmp_path.glob("*.part")).read_bytes() == content[:split]


def test_resume_restarts_safely_when_server_sends_full_response(tmp_path, monkeypatch):
    content = archive_bytes()
    asset = release_asset(content)
    archive = tmp_path / asset["name"]
    split = 40
    archive.write_bytes(content[:split])

    def urlopen(request, timeout):
        assert request.get_header("Range") == f"bytes={split}-"
        return response(content, 200, len(content))

    monkeypatch.setattr(install_ollama.urllib.request, "urlopen", urlopen)
    install_ollama.obtain_archive(archive, "v-test", asset)
    assert archive.read_bytes() == content


def test_install_does_not_extract_invalid_digest(windows_installer, monkeypatch):
    content = archive_bytes()
    asset = release_asset(content)
    monkeypatch.setattr(install_ollama, "release_asset", lambda: ("v-test", asset))
    monkeypatch.setattr(install_ollama, "extract_archive", lambda *_: pytest.fail("unverified extraction"))
    wrong = b"x" + content[1:]
    monkeypatch.setattr(install_ollama.urllib.request, "urlopen", lambda *_, **__: response(wrong, 200, len(wrong)))

    with pytest.raises(RuntimeError, match="SHA-256 校验失败"):
        install_ollama.install()
    assert not (windows_installer / asset["name"]).exists()
    assert not list(windows_installer.glob("*.part"))


def test_failed_extraction_keeps_verified_zip_ready_for_retry(windows_installer, monkeypatch):
    content = archive_bytes()
    asset = release_asset(content)
    runtime = windows_installer
    runtime.mkdir()
    archive = runtime / asset["name"]
    archive.write_bytes(content)
    monkeypatch.setattr(install_ollama, "release_asset", lambda: ("v-test", asset))
    monkeypatch.setattr(install_ollama.urllib.request, "urlopen", lambda *_, **__: pytest.fail("unexpected download"))
    original_extract = install_ollama.extract_archive

    def interrupted_extract(archive, destination):
        (destination / "ollama.exe").write_bytes(b"incomplete")
        raise OSError("disk error")

    monkeypatch.setattr(install_ollama, "extract_archive", interrupted_extract)
    with pytest.raises(OSError, match="disk error"):
        install_ollama.install()
    assert archive.read_bytes() == content
    assert not (runtime / "ollama").exists()

    monkeypatch.setattr(install_ollama, "release_asset", lambda: pytest.fail("unexpected latest release lookup"))
    monkeypatch.setattr(install_ollama, "extract_archive", original_extract)
    install_ollama.install()
    assert (runtime / "ollama" / "ollama.exe").read_bytes() == b"example binary"
    assert (runtime / "ollama" / "lib" / "ollama" / "example.dll").is_file()


def test_interrupted_install_keeps_original_release_metadata(windows_installer, monkeypatch):
    content = archive_bytes()
    asset = release_asset(content)
    split, size = 40, len(content)
    requests = []
    responses = iter((
        response(content[:split], 200, size),
        response(content[split:], 206, size - split, f"bytes {split}-{size - 1}/{size}"),
    ))

    def urlopen(request, timeout):
        requests.append((request.full_url, request.get_header("Range")))
        return next(responses)

    monkeypatch.setattr(install_ollama, "release_asset", lambda: ("v-original", asset))
    monkeypatch.setattr(install_ollama.urllib.request, "urlopen", urlopen)
    with pytest.raises(RuntimeError, match="下载中断"):
        install_ollama.install()

    saved = json.loads((windows_installer / "ollama-package.json").read_text(encoding="utf-8"))
    assert saved == {"version": "v-original", "asset": asset["name"], "size": size, "digest": asset["digest"]}
    monkeypatch.setattr(install_ollama, "release_asset", lambda: pytest.fail("must resume recorded release"))
    install_ollama.install()

    url = f"https://github.com/ollama/ollama/releases/download/v-original/{asset['name']}"
    assert requests == [(url, None), (url, f"bytes={split}-")]
    assert (windows_installer / "ollama/ollama.exe").read_bytes() == b"example binary"


def test_existing_release_record_recovers_verified_archive_offline(windows_installer, monkeypatch):
    content = archive_bytes()
    asset = release_asset(content)
    windows_installer.mkdir()
    (windows_installer / asset["name"]).write_bytes(content)
    (windows_installer / "ollama-version.json").write_text(
        json.dumps({"version": "v-legacy", "asset": asset["name"], "digest": asset["digest"]}),
        encoding="utf-8",
    )
    monkeypatch.setattr(install_ollama.urllib.request, "urlopen", lambda *_, **__: pytest.fail("offline cache used network"))

    install_ollama.install()
    assert (windows_installer / "ollama/ollama.exe").read_bytes() == b"example binary"
    saved = json.loads((windows_installer / "ollama-package.json").read_text(encoding="utf-8"))
    assert saved["version"] == "v-legacy" and saved["size"] == len(content)
