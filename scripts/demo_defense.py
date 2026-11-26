"""Run the opening-defense demo with fixed, harmless fixtures."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import webbrowser
from getpass import getpass
from ipaddress import ip_address
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import urlsplit

import httpx
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app.core.config import get_config
from backend.app.detectors.rules import RuleDetector


NOTES = "项目组周一召开例会。测试组负责整理系统测试结果，周三提交。全组周五汇总演示材料并完成排练。"
RULE_ID = "DEMO_MARKER"
MARKER = "DEFENSE_DEMO_2026"


class DemoError(Exception):
    """A demo step could not be verified."""


def loopback_url(value: str) -> str:
    try:
        parts = urlsplit(value)
        local = parts.hostname == "localhost" or ip_address(parts.hostname or "").is_loopback
        if (local and parts.scheme == "http" and parts.username is None and parts.port != 0
                and parts.path in ("", "/") and not parts.query and not parts.fragment):
            return value.rstrip("/")
    except ValueError:
        pass
    raise DemoError("演示需要本机 HTTP 地址，例如 http://127.0.0.1:8000。")


def step(number: int, title: str, pause: bool) -> None:
    print(f"\n[{number}/4] {title}", flush=True)
    if pause:
        input("按回车开始这一步… ")


def demonstrate_rule() -> None:
    # Run the project's detector against a temporary rule scoped to this demo.
    rule = {"id": RULE_ID, "category": "demo", "pattern": MARKER, "enabled": True}
    with TemporaryDirectory(prefix="sentinel-demo-") as folder:
        path = Path(folder) / "rules.yaml"
        path.write_text(yaml.safe_dump({"version": 1, "rules": [rule]}), encoding="utf-8")
        detector = RuleDetector(rules_path=path)
        control = detector.detect(NOTES)
        marked = detector.detect(f"演示标签：{MARKER}")
    if (control.status != "ok" or control.rule_ids or marked.status != "ok"
            or not marked.is_attack or marked.rule_ids != [RULE_ID]):
        raise DemoError("临时规则的检测结果与预期不符。")
    print("原始会议纪要 → L1 未命中")
    print(f"演示标签 {MARKER} → L1 命中规则 {RULE_ID}")
    print("此步骤使用独立规则库，展示 L1 的匹配结果。")


def sign_in(client: httpx.Client, username: str | None) -> int:
    if username:
        credentials = {"username": username, "password": getpass("请输入演示账号密码：")}
    else:
        try:
            accounts = json.loads((ROOT / ".runtime" / "credentials.json").read_text(encoding="utf-8"))
            account = accounts["user"]
            credentials = {"username": account["username"], "password": account["password"]}
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise DemoError("找不到本地演示账号，请使用 --username 用户名 手动登录。") from exc

    response = client.post("/auth/login", json=credentials)
    if response.status_code == 401:
        raise DemoError("演示账号登录失败，请使用 --username 用户名 输入当前密码。")
    response.raise_for_status()
    login = response.json()
    client.headers["Authorization"] = f"Bearer {login['access_token']}"
    return login["user"]["id"]


def run_demo(args: argparse.Namespace) -> bool:
    config = get_config()
    app = config["app"]
    api_url = loopback_url(args.backend or f"http://{app['host']}:{app['port']}")
    frontend_port = app.get("frontend_port", 5173)
    project_id = hashlib.sha256(str(ROOT).encode()).hexdigest()[:16]
    if config["target"]["provider"] != "ollama":
        raise DemoError("完整演示使用本地 Ollama，请先在当前项目中选用本地目标模型。")
    loopback_url(config["target"]["base_url"])

    with httpx.Client(base_url=f"{api_url}/api", timeout=10, trust_env=False) as client:
        response = client.get("/health")
        response.raise_for_status()
        health = response.json()
        if health.get("app") != "Prompt Sentinel" or health.get("project_id") != project_id:
            raise DemoError("该地址未对应当前项目。请启动此目录的 start.bat，核对后端端口。")
        target = health["target"]
        if target["provider"] != "ollama":
            raise DemoError("运行中的后端需要配置本地 Ollama 目标模型。")
        user_id = sign_in(client, args.username)

        step(1, "开启防护并摘要正常 TXT", args.pause)
        print(f"原文：{NOTES}", flush=True)
        result = None
        if target["ready"]:
            print(f"正在等待本地模型 {target['model']}…", flush=True)
            try:
                response = client.post(
                    "/document/summarize",
                    data={"protected": "true"},
                    files={"file": ("会议纪要.txt", NOTES.encode("utf-8"), "text/plain")},
                    timeout=httpx.Timeout(300, connect=10),
                )
                response.raise_for_status()
                result = response.json()["result"]
            except httpx.HTTPError as exc:
                print(f"摘要请求失败（{type(exc).__name__}）。")
        else:
            print(f"本地模型 {target['model']} 尚未就绪，跳过摘要请求。")

        summary_ok = bool(result and not result["blocked"] and not result.get("error") and result.get("output"))
        if summary_ok:
            print(f"生成摘要：{result['output']}")
            layers = [*result["detection"]["layer_results"], result.get("hardening"), result.get("output_check")]
            completed_layers = [layer["layer"] for layer in layers if layer and layer["status"] == "ok"]
            print(f"本次运行完成的防护层：{'、'.join(completed_layers) or '无'}")
        elif result:
            print(f"摘要未通过：{result.get('error') or result.get('output') or '模型没有返回摘要'}")

        step(2, "用固定标记演示 L1 规则命中", args.pause)
        demonstrate_rule()

        step(3, "验证上传格式限制", args.pause)
        response = client.post(
            "/document/summarize",
            data={"protected": "true"},
            files={"file": ("会议纪要.pdf", b"%PDF-1.4\n%%EOF\n", "application/pdf")},
        )
        format_ok = (response.status_code == 415
                     and response.json().get("detail") == "仅支持 UTF-8 编码的 .txt 文档")
        print(f"HTTP {response.status_code} · "
              f"{'仅支持 UTF-8 编码的 .txt 文档' if format_ok else '格式校验结果与预期不符'}")

        step(4, "按请求编号查阅自己的摘要日志", args.pause)
        log_ok = False
        if result:
            request_id = result["id"]
            response = client.get(f"/logs/{request_id}")
            response.raise_for_status()
            log = response.json()
            log_ok = (log["id"] == request_id and log["user_id"] == user_id and log["kind"] == "document"
                      and log["protected"] is True and log["blocked"] == result["blocked"]
                      and (not summary_ok or log["status"] == "allowed"))
            print(f"请求编号 {request_id} · 状态 {log['status']} · 耗时 {log['latency_ms']:.0f} ms")
            log_url = f"http://127.0.0.1:{frontend_port}/logs?request={request_id}"
            print(f"页面 {log_url} （需登录同一账号）")
            if log_ok and args.open_log:
                try:
                    if not webbrowser.open(log_url):
                        print("无法自动打开浏览器，可以使用上方链接。")
                except (OSError, webbrowser.Error):
                    print("无法自动打开浏览器，可以使用上方链接。")
        else:
            print("摘要请求未返回编号，本轮无法按编号查询日志。")
        return summary_ok and format_ok and log_ok


def main() -> int:
    parser = argparse.ArgumentParser(description="Prompt Sentinel 开题答辩演示")
    parser.add_argument("--pause", action="store_true", help="每一步开始前等候回车")
    parser.add_argument("--open-log", action="store_true", help="核对日志后打开浏览器中的详情页")
    parser.add_argument("--rule-only", action="store_true", help="离线演示 L1 规则匹配")
    parser.add_argument("--backend", help="本机后端地址（默认读取项目配置）")
    parser.add_argument("--username", help="交互输入此账号的密码（默认使用本地普通演示账号）")
    args = parser.parse_args()
    print("Prompt Sentinel · 开题答辩演示", flush=True)
    try:
        if args.rule_only:
            demonstrate_rule()
            return 0
        complete = run_demo(args)
    except DemoError as exc:
        print(f"\n演示失败：{exc}", file=sys.stderr)
        return 1
    except httpx.HTTPStatusError as exc:
        print(f"\n演示失败：后端返回 HTTP {exc.response.status_code}。", file=sys.stderr)
        return 1
    except httpx.RequestError as exc:
        print(f"\n后端连接失败（{type(exc).__name__}），请先运行 start.bat。", file=sys.stderr)
        return 1
    except (KeyError, TypeError, ValueError):
        print("\n演示所需的数据格式异常，请检查项目配置和后端版本。", file=sys.stderr)
        return 1
    except (KeyboardInterrupt, EOFError):
        print("\n演示已结束。", file=sys.stderr)
        return 130
    print("\n四项演示完成。" if complete else "\n本轮存在未通过的项目，请查看上方结果。")
    return 0 if complete else 1


if __name__ == "__main__":
    raise SystemExit(main())
