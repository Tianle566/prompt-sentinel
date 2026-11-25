#!/usr/bin/env python3
"""Install an official Ollama release into .runtime without modifying system apps."""
from __future__ import annotations

import hashlib
import json
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
import zipfile
from http.client import HTTPException
from pathlib import Path

from filelock import FileLock

ROOT = Path(__file__).resolve().parents[1]
USER_AGENT = "PromptSentinel-local-setup"


def platform_archives() -> tuple[str, ...]:
    arm = platform.machine().lower() in ("arm64", "aarch64")
    if sys.platform == "darwin":
        return ("ollama-darwin.tgz",)
    if sys.platform == "win32":
        return ("ollama-windows-arm64.zip" if arm else "ollama-windows-amd64.zip",)
    base = "ollama-linux-arm64" if arm else "ollama-linux-amd64"
    return f"{base}.tar.zst", f"{base}.tgz"


def release_asset() -> tuple[str, dict]:
    request = urllib.request.Request(
        "https://api.github.com/repos/ollama/ollama/releases/latest",
        headers={"User-Agent": USER_AGENT},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        release = json.load(response)
    assets = {item["name"]: item for item in release["assets"]}
    names = platform_archives()
    for name in names:
        if name in assets:
            return release["tag_name"], assets[name]
    raise RuntimeError(f"当前平台没有可自动安装的官方包，请从 https://ollama.com/download 安装：{names[0]}")


def file_sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def read_package_record(path: Path) -> dict:
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return {}
    return record if isinstance(record, dict) else {}


def package_from_record(record: dict, runtime: Path, *, legacy: bool = False) -> tuple[str, dict] | None:
    version = record.get("version")
    name = record.get("asset")
    digest = record.get("digest")
    if (
        not isinstance(version, str)
        or not re.fullmatch(r"[0-9A-Za-z][0-9A-Za-z.+_-]*", version)
        or name not in platform_archives()
        or not isinstance(digest, str)
        or not re.fullmatch(r"sha256:[0-9a-fA-F]{64}", digest)
    ):
        return None
    size = record.get("size")
    if legacy and size is None:
        archive = runtime / name
        # Older installations only recorded the digest. A matching archive supplies the size.
        if archive.is_file() and file_sha256(archive) == digest[7:].lower():
            size = archive.stat().st_size
    if type(size) is not int or size <= 0:
        return None
    url = f"https://github.com/ollama/ollama/releases/download/{version}/{name}"
    return version, {"name": name, "size": size, "digest": digest, "browser_download_url": url}


def install_asset(runtime: Path) -> tuple[str, dict]:
    path = runtime / "ollama-package.json"
    saved = package_from_record(read_package_record(path), runtime)
    if saved is not None:
        return saved
    saved = package_from_record(read_package_record(runtime / "ollama-version.json"), runtime, legacy=True)
    if saved is None:
        version, asset = release_asset()
        saved = package_from_record(
            {"version": version, "asset": asset["name"], "size": asset.get("size"), "digest": asset.get("digest")},
            runtime,
        )
        if saved is None:
            raise RuntimeError("官方发布信息缺少有效的 Ollama 安装包大小或 SHA-256")
    version, asset = saved
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps({"version": version, "asset": asset["name"], "size": asset["size"], "digest": asset["digest"]}, indent=2),
        encoding="utf-8",
    )
    temporary.replace(path)
    return saved


def transfer_archive(url: str, partial: Path, offset: int, size: int) -> int:
    headers = {"User-Agent": USER_AGENT, "Accept-Encoding": "identity"}
    if offset:
        headers["Range"] = f"bytes={offset}-"
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=60) as response:
        end = size
        if response.status == 206:
            match = re.fullmatch(r"bytes (\d+)-(\d+)/(\d+)", response.headers.get("Content-Range", ""))
            if not match:
                raise RuntimeError("Ollama 安装包续传响应缺少有效的文件范围")
            start, last, total = map(int, match.groups())
            if start != offset or total != size or not start <= last < total:
                raise RuntimeError("Ollama 安装包续传范围与本地进度不符")
            end = last + 1
        elif response.status == 200:
            offset = 0  # The server may return the entire archive instead of a range.
        else:
            raise RuntimeError(f"Ollama 安装包下载返回 HTTP {response.status}")
        remaining = end - offset
        content_length = response.headers.get("Content-Length")
        if content_length is not None and content_length != str(remaining):
            raise RuntimeError("Ollama 安装包响应长度与发布信息不符")
        with partial.open("ab" if offset else "wb") as stream:
            while remaining:
                chunk = response.read(min(remaining, 1024 * 1024))
                if not chunk:
                    raise RuntimeError("Ollama 安装包下载中断，重新运行启动脚本可继续下载")
                stream.write(chunk)
                remaining -= len(chunk)
    return end


def obtain_archive(archive: Path, version: str, asset: dict) -> None:
    match = re.fullmatch(r"sha256:([0-9a-fA-F]{64})", asset.get("digest") or "")
    size = asset.get("size")
    if not match or type(size) is not int or size <= 0:
        raise RuntimeError("官方发布信息缺少有效的 Ollama 安装包大小或 SHA-256")
    digest = match[1].lower()
    if archive.is_file() and archive.stat().st_size == size and file_sha256(archive) == digest:
        print(f"复用已校验的 Ollama 安装包 {archive.name}", flush=True)
        return

    partial = archive.with_name(f"ollama-{digest[:20]}.part")
    if (
        not partial.exists()
        and archive.suffix == ".zip"
        and archive.is_file()
        and 0 < archive.stat().st_size < size
        and not zipfile.is_zipfile(archive)
    ):
        archive.replace(partial)  # Older installations stored partial downloads at the final path.
    offset = partial.stat().st_size if partial.is_file() else 0
    if offset > size:
        offset = 0
    print(f"下载官方 Ollama {version} ({archive.name})，已下载 {offset:,}/{size:,} 字节", flush=True)
    try:
        while offset < size:
            offset = transfer_archive(asset["browser_download_url"], partial, offset, size)
    except HTTPException as error:
        raise RuntimeError("Ollama 安装包下载中断，重新运行启动脚本可继续下载") from error
    if file_sha256(partial) != digest:
        partial.unlink()
        raise RuntimeError("Ollama 安装包 SHA-256 校验失败，重新运行启动脚本可重新下载")
    partial.replace(archive)


def installed_binary(directory: Path, name: str) -> Path | None:
    return next((path for path in (directory / name, directory / "bin" / name) if path.is_file()), None)


def extract_archive(archive: Path, destination: Path) -> None:
    if archive.name.endswith(".zip"):
        with zipfile.ZipFile(archive) as package:
            root = destination.resolve()
            for entry in package.infolist():
                if not (destination / entry.filename).resolve().is_relative_to(root):
                    raise RuntimeError("安装包路径不合法")
            package.extractall(destination)
    elif archive.name.endswith(".zst"):
        subprocess.run(["tar", "--zstd", "-xf", str(archive), "-C", str(destination)], check=True)
    else:
        with tarfile.open(archive) as package:
            package.extractall(destination, filter="data")


def install() -> None:
    name = "ollama.exe" if sys.platform == "win32" else "ollama"
    executable = shutil.which(name)
    if executable:
        print(executable)
        return
    runtime = ROOT / ".runtime"
    runtime.mkdir(exist_ok=True)
    destination = runtime / "ollama"
    with FileLock(str(runtime / "ollama-install.lock")):
        binary = installed_binary(destination, name)
        if binary:
            print(binary)
            return
        version, asset = install_asset(runtime)
        archive = runtime / asset["name"]
        obtain_archive(archive, version, asset)
        with tempfile.TemporaryDirectory(prefix="ollama-extract-", dir=runtime) as directory:
            staged = Path(directory) / "package"
            staged.mkdir()
            extract_archive(archive, staged)
            binary = installed_binary(staged, name)
            if not binary:
                raise RuntimeError("官方 Ollama 安装包中未找到可执行文件")
            # Preserve any incomplete directory left by an older installer.
            previous = staged.parent.with_name(f"{staged.parent.name}-previous")
            if destination.exists():
                destination.replace(previous)
            try:
                staged.replace(destination)
            except OSError:
                if previous.exists():
                    previous.replace(destination)
                raise
            print(destination / binary.relative_to(staged))
        (runtime / "ollama-version.json").write_text(
            json.dumps({"version": version, "asset": asset["name"], "size": asset["size"], "digest": asset["digest"]}, indent=2),
            encoding="utf-8",
        )


if __name__ == "__main__":
    install()
