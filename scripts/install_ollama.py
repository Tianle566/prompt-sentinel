#!/usr/bin/env python3
"""Install an official Ollama release into .runtime without modifying system apps."""
import hashlib
import json
import platform
import shutil
import sys
import tarfile
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def install():
    if shutil.which("ollama"):
        print(shutil.which("ollama"))
        return
    destination = ROOT / ".runtime" / "ollama"
    binary = destination / ("ollama.exe" if sys.platform == "win32" else "ollama")
    if binary.exists():
        print(binary)
        return
    request = urllib.request.Request("https://api.github.com/repos/ollama/ollama/releases/latest", headers={"User-Agent": "PromptSentinel-local-setup"})
    with urllib.request.urlopen(request, timeout=30) as response:
        release = json.load(response)
    arm = platform.machine().lower() in ("arm64", "aarch64")
    if sys.platform == "darwin":
        name = "ollama-darwin.tgz"
    elif sys.platform == "win32":
        name = "ollama-windows-arm64.zip" if arm else "ollama-windows-amd64.zip"
    else:
        name = "ollama-linux-arm64.tar.zst" if arm else "ollama-linux-amd64.tar.zst"
        if not any(asset["name"] == name for asset in release["assets"]):
            name = name.replace(".tar.zst", ".tgz")
    asset = next((item for item in release["assets"] if item["name"] == name), None)
    if not asset:
        raise RuntimeError(f"当前平台没有可自动安装的官方包，请从 https://ollama.com/download 安装：{name}")
    archive = ROOT / ".runtime" / name
    archive.parent.mkdir(parents=True, exist_ok=True)
    print(f"下载官方 Ollama {release['tag_name']} ({name})", flush=True)
    urllib.request.urlretrieve(asset["browser_download_url"], archive)
    expected = asset.get("digest", "")
    if expected.startswith("sha256:"):
        digest = hashlib.file_digest(archive.open("rb"), "sha256").hexdigest()
        if digest != expected.split(":", 1)[1]:
            raise RuntimeError("Ollama 安装包校验失败")
    destination.mkdir(parents=True, exist_ok=True)
    if name.endswith(".zip"):
        with zipfile.ZipFile(archive) as package:
            for entry in package.infolist():
                if not (destination / entry.filename).resolve().is_relative_to(destination.resolve()):
                    raise RuntimeError("安装包路径不合法")
            package.extractall(destination)
    elif name.endswith(".zst"):
        import subprocess
        subprocess.run(["tar", "--zstd", "-xf", str(archive), "-C", str(destination)], check=True)
    else:
        with tarfile.open(archive) as package:
            package.extractall(destination, filter="data")
    if not binary.exists() and (destination / "bin" / "ollama").exists():
        binary = destination / "bin" / "ollama"
    (ROOT / ".runtime" / "ollama-version.json").write_text(json.dumps({"version": release["tag_name"], "asset": asset["name"], "digest": expected}, indent=2))
    print(binary)


if __name__ == "__main__":
    install()
