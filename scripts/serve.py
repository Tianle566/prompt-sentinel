#!/usr/bin/env python3
"""Cross-platform launcher with project-owned Ollama storage and bounded cleanup."""
from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import httpx
import psutil
from backend.app.core.config import get_config, resolve_path, save_config
from scripts.doctor import diagnose, node_version, supported_node


def healthy(url):
    try:
        return httpx.get(url, timeout=2).is_success
    except httpx.HTTPError:
        return False


def project_store(url):
    try:
        tags = httpx.get(url + "/api/tags", timeout=3).json().get("models", [])
        if not tags:
            return False
        data = httpx.post(url + "/api/show", json={"model": tags[0]["name"]}, timeout=3).json()
        return str(ROOT / "models" / "ollama") in data.get("modelfile", "")
    except (httpx.HTTPError, ValueError, KeyError):
        return False


def project_api(url):
    try:
        response = httpx.get(url.rstrip("/") + "/api/health", timeout=3)
        data = response.json()
        return response.is_success and data.get("app") == "Prompt Sentinel" and data.get("project_id") == hashlib.sha256(str(ROOT.resolve()).encode()).hexdigest()[:16]
    except (httpx.HTTPError, ValueError):
        return False


def free_port(start):
    for port in range(start, start + 100):
        with socket.socket() as sock:
            try:
                sock.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise RuntimeError("未找到空闲的本地 Ollama 端口")


def run(setup=False, check=False):
    os.chdir(ROOT)
    config = get_config()
    if check:
        report = diagnose()
        for row in report["checks"]:
            print(f"[{'通过' if row['ok'] else '待处理'}] {row['name']}：{row['detail']}")
        if not report["ok"]:
            raise RuntimeError("环境尚未准备完整，运行 start.bat 或 ./start.sh 完成初始化")
        return
    print("[1/5] 检查本机环境与前端依赖…", flush=True)
    npm = shutil.which("npm.cmd" if os.name == "nt" else "npm")
    version = node_version()
    if not npm or not version or not supported_node(version):
        raise RuntimeError("请先安装 Node.js 20.19+ / 22.12+（含 npm）")
    lock = ROOT / "frontend" / "package-lock.json"
    fingerprint = hashlib.sha256(lock.read_bytes()).hexdigest()
    stamp = ROOT / ".runtime" / "frontend-lock.sha256"
    frontend_ready = (ROOT / "frontend" / "node_modules" / ".package-lock.json").is_file()
    if setup or not frontend_ready or not stamp.is_file() or stamp.read_text(encoding="utf-8").strip() != fingerprint:
        subprocess.run([npm, "ci"], cwd=ROOT / "frontend", check=True, shell=os.name == "nt")
        stamp.parent.mkdir(parents=True, exist_ok=True)
        stamp.write_text(fingerprint, encoding="utf-8")
    (ROOT / ".runtime").mkdir(exist_ok=True)
    stop_request = ROOT / ".runtime" / "stop.request"
    stop_request.unlink(missing_ok=True)
    owned, streams = [], []
    stop = threading.Event()
    for name in ("SIGINT", "SIGTERM"):
        signal.signal(getattr(signal, name), lambda *_: stop.set())

    def launch(command, log_name, cwd=ROOT, env=None):
        stream = (ROOT / ".runtime" / log_name).open("a", encoding="utf-8")
        streams.append(stream)
        process = subprocess.Popen(command, cwd=cwd, env=env, stdout=stream, stderr=subprocess.STDOUT, shell=os.name == "nt" and str(command[0]).lower().endswith(".cmd"))
        owned.append(process)
        return process

    def ready(url, process):
        until = time.monotonic() + 60
        while time.monotonic() < until and not stop.is_set():
            if healthy(url):
                return
            if process.poll() is not None:
                raise RuntimeError(f"服务启动失败，请检查 .runtime 日志：{url}")
            stop.wait(.5)
        raise RuntimeError(f"服务未就绪：{url}")

    try:
        print("[2/5] 检查本地检测模型，缺失文件将从官方源下载…", flush=True)
        from scripts.download_models import download, import_local_target
        for key in ("deberta", "qwen_guard"):
            path = resolve_path(config["models"][key]["path"])
            if setup or not (path / "config.json").is_file() or not (path / "tokenizer_config.json").is_file() or not list(path.glob("*.safetensors")):
                download(key)
        if config["target"]["provider"] == "ollama":
            print("[3/5] 准备本地 Ollama 与目标模型…", flush=True)
            from scripts.install_ollama import install
            name = "ollama.exe" if os.name == "nt" else "ollama"
            executable = shutil.which(name)
            if not executable:
                install()
                executable = str(ROOT / ".runtime" / "ollama" / name)
                if not Path(executable).is_file():
                    executable = str(ROOT / ".runtime" / "ollama" / "bin" / name)
            url = config["target"]["base_url"].rstrip("/")
            address = urlparse(url)
            if address.scheme != "http" or address.hostname not in ("localhost", "127.0.0.1", "::1"):
                raise RuntimeError("一键启动使用本机 HTTP Ollama；远端兼容服务请配置 provider=openai")
            if healthy(url + "/api/version") and not project_store(url):
                url = f"http://127.0.0.1:{free_port((address.port or 11434) + 1)}"
                config = save_config({"target": {"base_url": url}})
                print(f"原端口属于其他 Ollama，项目改用 {url}，已保存到 backend/config.yaml", flush=True)
            if not healthy(url + "/api/version"):
                env = {**os.environ, "OLLAMA_MODELS": str(ROOT / "models" / "ollama"), "OLLAMA_HOST": url}
                process = launch([executable, "serve"], "ollama.log", env=env)
                ready(url + "/api/version", process)
            small = psutil.virtual_memory().total < 16 * 1024**3
            entry = config["models"]["target"]
            path = resolve_path(entry["small_path"] if small else entry["path"])
            filename = entry["small_filename"] if small else entry["filename"]
            if setup or not (path / filename).is_file() or not (path / "tokenizer_config.json").is_file():
                download("target")
            model = config["target"]["small_model"] if small else config["target"]["model"]
            tags = httpx.get(url + "/api/tags", timeout=5).json().get("models", [])
            if setup or model not in [item["name"] for item in tags]:
                import_local_target(config, executable)
        print("[4/5] 检查评测数据…", flush=True)
        if setup or not all(resolve_path(config["data"][key]).is_file() for key in ("detect_path", "asr_path")):
            from scripts.build_dataset import build_dataset
            build_dataset(config)
        print("[5/5] 启动应用服务…", flush=True)
        host, port = config["app"]["host"], int(config["app"]["port"])
        api_url = f"http://{host}:{port}"
        if healthy(api_url + "/api/health") and not project_api(api_url):
            raise RuntimeError(f"{api_url} 已属于另一个项目，请修改 backend/config.yaml 的 app.port")
        if not project_api(api_url):
            process = launch([sys.executable, "-m", "uvicorn", "backend.app.main:app", "--host", host, "--port", str(port)], "backend.log", env={**os.environ, "PYTHONUNBUFFERED": "1"})
            ready(api_url + "/api/health", process)
        frontend_port = int(config["app"].get("frontend_port", 5173))
        frontend_url = f"http://127.0.0.1:{frontend_port}"
        if healthy(frontend_url) and not project_api(frontend_url):
            raise RuntimeError(f"{frontend_url} 已属于另一个前端，请修改 app.frontend_port")
        if not healthy(frontend_url):
            process = launch([npm, "run", "dev", "--", "--host", "127.0.0.1", "--port", str(frontend_port), "--strictPort"], "frontend.log", cwd=ROOT / "frontend", env={**os.environ, "SENTINEL_BACKEND_URL": api_url})
            ready(frontend_url, process)
        print(f"\nPrompt Sentinel 已就绪\n前端：{frontend_url}\nSwagger：{api_url}/docs\n初始账户：{ROOT / '.runtime' / 'credentials.json'}\nCtrl+C 仅停止本次启动的服务。\n", flush=True)
        while not stop.wait(1):
            if stop_request.exists():
                stop.set()
                break
            for process in owned:
                if process.poll() is not None:
                    raise RuntimeError(f"服务退出（{process.returncode}），请检查 .runtime 日志")
    finally:
        descendants = []
        for process in owned:
            try:
                descendants.extend(psutil.Process(process.pid).children(recursive=True))
            except psutil.NoSuchProcess:
                pass
        for child in reversed(descendants):
            try:
                child.terminate()
            except psutil.NoSuchProcess:
                pass
        for process in reversed(owned):
            if process.poll() is None:
                process.terminate()
        for process in reversed(owned):
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        _, survivors = psutil.wait_procs(descendants, timeout=3)
        for child in survivors:
            try:
                child.kill()
            except psutil.NoSuchProcess:
                pass
        for stream in streams:
            stream.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--setup", action="store_true")
    parser.add_argument("--check", action="store_true", help="Validate configuration without changing or starting services")
    args = parser.parse_args()
    try:
        run(args.setup, args.check)
    except (RuntimeError, OSError, ValueError, subprocess.CalledProcessError) as exc:
        print(f"\n启动未完成：{exc}\n可运行启动脚本 --check 查看环境；服务日志位于 .runtime/。", file=sys.stderr)
        raise SystemExit(1)
