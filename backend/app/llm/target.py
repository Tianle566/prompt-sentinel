"""Real Ollama/OpenAI-compatible calls; no synthetic fallback responses."""
from __future__ import annotations

import copy
import threading

import httpx
import ollama
import psutil

from backend.app.core.config import get_config, resolve_path
from backend.app.core.target_credentials import CredentialError, credential_for, normalize_base_url
from backend.app.detectors.runtime import model_load_lock

_tokenizers = {}
_tokenizer_lock = threading.RLock()


class TargetError(RuntimeError):
    pass


class TargetLLM:
    def __init__(self, config: dict | None = None, client: httpx.Client | None = None, api_key_override: str | None = None):
        self.config = copy.deepcopy(config if config is not None else get_config())
        self.settings = self.config["target"]
        self.model = self.settings["model"]
        if self.settings.get("provider", "ollama") == "ollama" and psutil.virtual_memory().total < 16 * 1024 ** 3:
            self.model = self.settings.get("small_model", "qwen3:0.6b")
        self._client = client
        self._api_key_override = api_key_override

    def _load_tokenizer(self):
        """The exact Qwen chat tokenizer is downloaded beside local GGUFs."""
        model_settings = self.config["models"]["target"]
        small = self.model == self.settings.get("small_model", "qwen3:0.6b")
        path = resolve_path(model_settings["small_path" if small else "path"])
        if not (path / "tokenizer_config.json").is_file():
            raise TargetError("目标模型本地 tokenizer 未安装；请运行 python scripts/download_models.py")
        key = str(path.resolve())
        with _tokenizer_lock, model_load_lock:
            if key not in _tokenizers:
                try:
                    from transformers import AutoTokenizer
                    _tokenizers[key] = AutoTokenizer.from_pretrained(str(path), local_files_only=True, trust_remote_code=False)
                except Exception as exc:
                    raise TargetError(f"目标模型本地 tokenizer 加载失败：{type(exc).__name__}") from exc
            return _tokenizers[key]

    def _prompt_token_count(self, messages: list[dict[str, str]]) -> int:
        tokenizer = self._load_tokenizer()
        tokens = tokenizer.apply_chat_template(messages, tokenize=True, add_generation_prompt=True, enable_thinking=False)
        return len(tokens)

    def validate_context(self, messages: list[dict[str, str]]) -> int | None:
        """Reject overflow before Ollama can silently discard old prompt text.

        OpenAI-compatible servers own the tokenizer for their configured model;
        a Qwen tokenizer would provide a false count for arbitrary API models.
        """
        if self.settings.get("provider", "ollama") != "ollama":
            return None
        count = self._prompt_token_count(messages)
        reserve = int(self.settings.get("max_tokens", 192))
        context = int(self.settings.get("context_length", 4096))
        if count + reserve > context:
            raise TargetError(f"输入与回复预留空间共 {count + reserve} token，超过目标模型 {context} token 上下文；请缩短输入或分段摘要")
        return count

    def _request(self, method: str, path: str, **kwargs):
        base_url = self.settings["base_url"].rstrip("/")
        if self.settings.get("provider") == "openai":
            base_url = normalize_base_url(base_url)
        url = base_url + path
        if self._client is not None:
            response = self._client.request(method, url, **kwargs)
        else:
            with httpx.Client(timeout=float(self.settings.get("timeout_seconds", 120))) as client:
                response = client.request(method, url, **kwargs)
        response.raise_for_status()
        return response.json()

    def _headers(self) -> dict:
        try:
            key = self._api_key_override if self._api_key_override is not None else credential_for(self.settings)[0]
        except CredentialError as exc:
            raise TargetError(str(exc)) from None
        return {"Content-Type": "application/json", **({"Authorization": "Bearer " + key} if key else {})}

    @staticmethod
    def _http_error(status: int) -> str:
        if status in (401, 403):
            return f"接口鉴权失败（HTTP {status}），请检查 API Key 和模型调用权限"
        if status == 429:
            return "接口额度或请求频率受限（HTTP 429），请检查配额或稍后重试"
        return f"目标模型服务返回 HTTP {status}；请检查服务地址、模型名称及调用权限"

    def list_models(self) -> list[str]:
        try:
            local = self.settings.get("provider", "ollama") == "ollama"
            data = self._request("GET", "/api/tags" if local else "/models", headers={} if local else self._headers())
            rows = data["models" if local else "data"]
            if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
                raise ValueError
            field = "name" if local else "id"
            return sorted({row[field] for row in rows if isinstance(row.get(field), str) and 0 < len(row[field]) <= 200})
        except TargetError:
            raise
        except httpx.HTTPStatusError as exc:
            raise TargetError(self._http_error(exc.response.status_code)) from None
        except httpx.TimeoutException:
            raise TargetError("获取模型列表超时，请检查服务地址") from None
        except httpx.RequestError:
            raise TargetError("无法连接模型服务，请检查服务地址和网络") from None
        except (KeyError, IndexError, TypeError, ValueError, AttributeError):
            raise TargetError("服务返回了不兼容的模型列表，可手动填写模型名称") from None

    def generate(self, messages: list[dict[str, str]]) -> str:
        try:
            self.validate_context(messages)
            if self.settings.get("provider", "ollama") == "ollama":
                body = {"model": self.model, "messages": messages, "stream": False, "think": False, "options": {"temperature": float(self.settings.get("temperature", 0)), "num_predict": int(self.settings.get("max_tokens", 192)), "num_ctx": int(self.settings.get("context_length", 4096)), "seed": int(self.config.get("evaluation", {}).get("seed", 42))}}
                if self.config.get("models", {}).get("device") == "cpu":
                    # Ollama defaults to Metal/CUDA independently of torch;
                    # force its GPU layers off for a genuine CPU experiment.
                    body["options"].update(num_gpu=0, num_thread=max(1, int(self.config["models"].get("cpu_threads", 4))))
                if self._client is not None:
                    data = self._request("POST", "/api/chat", json=body)
                else:
                    # Use the official SDK in production. The injected httpx
                    # transport above also exercises the exact wire contract.
                    with ollama.Client(host=self.settings["base_url"], timeout=float(self.settings.get("timeout_seconds", 120))) as client:
                        data = client.chat(**body)
                content = data["message"]["content"]
            elif self.settings["provider"] == "openai":
                headers = self._headers()
                # base_url may include /v1, as in OpenAI's official SDK.
                body = {"model": self.model, "messages": messages, "max_tokens": int(self.settings.get("max_tokens", 192)), "temperature": float(self.settings.get("temperature", 0))}
                data = self._request("POST", "/chat/completions", json=body, headers=headers)
                content = data["choices"][0]["message"]["content"]
            else:
                raise TargetError("未知目标模型提供方")
            if not isinstance(content, str) or not content.strip():
                raise TargetError("目标模型返回了空回复")
            return content
        except TargetError:
            raise
        except ollama.ResponseError as exc:
            raise TargetError(f"目标模型服务返回 HTTP {exc.status_code}；请检查本地服务与模型名称") from exc
        except ConnectionError as exc:
            raise TargetError("无法连接目标模型服务，请检查 Ollama 是否启动") from exc
        except httpx.HTTPStatusError as exc:
            raise TargetError(self._http_error(exc.response.status_code)) from None
        except httpx.TimeoutException as exc:
            raise TargetError("目标模型响应超时，请检查服务或增加超时配置") from exc
        except httpx.RequestError as exc:
            raise TargetError("无法连接目标模型服务，请检查 Ollama/兼容接口是否启动") from exc
        except (KeyError, IndexError, TypeError, ValueError, AttributeError) as exc:
            raise TargetError("目标模型返回了不兼容的响应格式") from exc

    def health(self) -> dict:
        info = {"provider": self.settings.get("provider", "ollama"), "model": self.model, "ready": False}
        try:
            if info["provider"] == "ollama":
                data = self._request("GET", "/api/tags")
                models = [item.get("name", "") for item in data.get("models", [])]
                info["ready"] = self.model in models or self.model + ":latest" in models
                if not info["ready"]:
                    info["error"] = "Ollama 中尚未导入目标本地模型"
            else:
                info["ready"] = self.model in self.list_models()
            return info
        except Exception as exc:
            info["error"] = f"目标模型健康检查失败：{type(exc).__name__}"
            return info
