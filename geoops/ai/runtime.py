"""OpenAI-compatible model runtime.

The runtime is configured from the process environment, never from a browser
field, so an API key does not have to pass through the console or be stored in
the repository:

    GEOOPS_MODEL_BASE_URL   https://host/v1  (or an endpoint ending in
                                             /chat/completions)
    GEOOPS_MODEL_API_KEY    optional for local servers, required by most hosts
    GEOOPS_MODEL_NAME       model identifier accepted by that host
    GEOOPS_MODEL_TIMEOUT    optional seconds, default 60

If the base URL or model name is missing, ``invoke`` raises ``NOT_CONFIGURED``
with the missing variable names. There is no canned answer and no placeholder
completion: a caller either reaches a real endpoint or receives an explicit
failure.

A local operator may instead keep the same keys in ``var/model-runtime.env``
(KEY=VALUE, one per line) so the launcher does not have to inject environment
variables; a real environment variable still wins over the file.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from typing import Any, Dict, Optional
from urllib.parse import urlsplit

MODEL_ENV_KEYS = (
    "GEOOPS_MODEL_BASE_URL",
    "GEOOPS_MODEL_API_KEY",
    "GEOOPS_MODEL_NAME",
    "GEOOPS_MODEL_TIMEOUT",
)


class ModelRuntimeError(RuntimeError):
    """A model call failed; ``code`` is stable and safe to show in a UI."""

    def __init__(self, code: str, message: str, status: int = 0) -> None:
        super().__init__(message)
        self.code = code
        self.status = status


def default_env_file() -> str:
    """The launcher's optional local model configuration."""
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(root, "var", "model-runtime.env")


def read_env_file(path: str) -> Dict[str, str]:
    """Read KEY=VALUE lines; unknown keys are refused, comments are allowed."""
    values: Dict[str, str] = {}
    if not path:
        return values
    if not os.path.isfile(path):
        return values
    try:
        with open(path, encoding="utf-8-sig") as handle:
            lines = handle.readlines()
    except OSError as exc:
        raise ValueError("cannot read model config %s: %s" % (path, exc)) from exc
    for number, raw in enumerate(lines, start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ValueError("model config line %d is not KEY=VALUE" % number)
        key, value = line.split("=", 1)
        key = key.strip().upper()
        if key not in MODEL_ENV_KEYS:
            raise ValueError("model config line %d has unknown key %s" % (number, key))
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        values[key] = value
    return values


class ModelRuntime:
    PROVIDER = "openai-compatible"

    def __init__(
        self,
        base_url: str = "",
        api_key: str = "",
        model: str = "",
        timeout_s: float = 60.0,
        config_file: str = "",
        config_error: str = "",
    ) -> None:
        self.base_url = str(base_url or "").strip().rstrip("/")
        self.api_key = str(api_key or "").strip()
        self.model = str(model or "").strip()
        try:
            self.timeout_s = max(1.0, min(300.0, float(timeout_s)))
        except (TypeError, ValueError):
            self.timeout_s = 60.0
        self.config_file = str(config_file or "").strip()
        self.config_error = str(config_error or "").strip()

    @classmethod
    def from_env(cls, env_file: Optional[str] = None) -> "ModelRuntime":
        path = default_env_file() if env_file is None else str(env_file)
        config_error = ""
        try:
            file_values = read_env_file(path)
        except ValueError as exc:
            file_values = {}
            config_error = str(exc)
        values = {
            key: os.environ.get(key) or file_values.get(key, "")
            for key in MODEL_ENV_KEYS
        }
        return cls(
            base_url=values["GEOOPS_MODEL_BASE_URL"],
            api_key=values["GEOOPS_MODEL_API_KEY"],
            model=values["GEOOPS_MODEL_NAME"],
            timeout_s=values["GEOOPS_MODEL_TIMEOUT"] or "60",
            config_file=path if os.path.isfile(path) else "",
            config_error=config_error,
        )

    # ------------------------------------------------------------ status
    def _display_endpoint(self) -> str:
        """Return scheme/host/path only; never echo query strings or userinfo."""
        if not self.base_url:
            return ""
        try:
            parts = urlsplit(self.base_url)
        except ValueError:
            return ""
        host = parts.hostname or ""
        if parts.port:
            host = "%s:%d" % (host, parts.port)
        return "%s://%s%s" % (parts.scheme, host, parts.path)

    def _valid_base(self) -> bool:
        try:
            parts = urlsplit(self.base_url)
        except ValueError:
            return False
        return parts.scheme in ("http", "https") and bool(parts.netloc)

    def status(self) -> Dict[str, Any]:
        missing = [
            name
            for name, value in (
                ("GEOOPS_MODEL_BASE_URL", self.base_url),
                ("GEOOPS_MODEL_NAME", self.model),
            )
            if not value
        ]
        configured = not missing and self._valid_base()
        reason = ""
        state = "READY" if configured else "NOT_CONFIGURED"
        if self.config_error:
            configured = False
            state = "CONFIG_ERROR"
            reason = self.config_error
        elif missing:
            reason = "missing: " + ", ".join(missing)
        elif not self._valid_base():
            reason = "GEOOPS_MODEL_BASE_URL must be an http(s) URL"
        return {
            "provider": self.PROVIDER,
            "configured": configured,
            "state": state,
            "reason": reason,
            "endpoint": self._display_endpoint(),
            "model": self.model,
            "authentication": "bearer" if self.api_key else "none",
            "api_key_configured": bool(self.api_key),
            "timeout_s": self.timeout_s,
            "config_file": self.config_file,
        }

    # ----------------------------------------------------------- request
    def _chat_url(self) -> str:
        if not self._valid_base():
            raise ModelRuntimeError(
                "NOT_CONFIGURED", "GEOOPS_MODEL_BASE_URL must be an http(s) URL"
            )
        if self.base_url.endswith("/chat/completions"):
            return self.base_url
        return self.base_url + "/chat/completions"

    @staticmethod
    def _content_text(content: Any) -> str:
        if isinstance(content, str):
            return content.strip()
        if isinstance(content, list):
            parts = []
            for item in content:
                if isinstance(item, dict) and isinstance(item.get("text"), str):
                    parts.append(item["text"])
            return "".join(parts).strip()
        return ""

    def invoke(
        self,
        prompt: str,
        system: str = "",
        temperature: Optional[float] = None,
        max_tokens: int = 512,
        timeout_s: Optional[float] = None,
    ) -> Dict[str, Any]:
        status = self.status()
        if not status["configured"]:
            raise ModelRuntimeError("NOT_CONFIGURED", status["reason"] or "model runtime is not configured")
        prompt = str(prompt or "").strip()
        if not prompt:
            raise ModelRuntimeError("EMPTY_PROMPT", "prompt is empty")
        messages = []
        if str(system or "").strip():
            messages.append({"role": "system", "content": str(system).strip()})
        messages.append({"role": "user", "content": prompt})

        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "max_tokens": max(1, min(8192, int(max_tokens))),
        }
        if temperature is not None:
            payload["temperature"] = max(0.0, min(2.0, float(temperature)))

        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers = {
            "Content-Type": "application/json; charset=utf-8",
            "Accept": "application/json",
            "User-Agent": "Bumao-GeoOps/0.1 model-runtime",
        }
        if self.api_key:
            headers["Authorization"] = "Bearer " + self.api_key
        request = urllib.request.Request(
            self._chat_url(), data=data, headers=headers, method="POST"
        )
        started = time.monotonic()
        try:
            with urllib.request.urlopen(
                request, timeout=timeout_s or self.timeout_s
            ) as response:
                body = response.read(2 * 1024 * 1024).decode("utf-8", "replace")
        except urllib.error.HTTPError as exc:
            body = exc.read(1200).decode("utf-8", "replace")
            raise ModelRuntimeError(
                "PROVIDER_HTTP_ERROR",
                "provider returned HTTP %d: %s" % (exc.code, _provider_message(body)),
                exc.code,
            ) from exc
        except (TimeoutError, urllib.error.URLError, OSError) as exc:
            reason = getattr(exc, "reason", None) or str(exc)
            raise ModelRuntimeError(
                "PROVIDER_UNREACHABLE",
                "model endpoint unreachable: %s" % reason,
            ) from exc

        try:
            parsed = json.loads(body)
        except json.JSONDecodeError as exc:
            raise ModelRuntimeError(
                "PROVIDER_BAD_RESPONSE", "provider did not return JSON"
            ) from exc
        choices = parsed.get("choices") if isinstance(parsed, dict) else None
        if not isinstance(choices, list) or not choices:
            raise ModelRuntimeError(
                "PROVIDER_BAD_RESPONSE", "provider response has no choices"
            )
        message = choices[0].get("message") if isinstance(choices[0], dict) else None
        text = self._content_text(message.get("content") if isinstance(message, dict) else "")
        if not text:
            raise ModelRuntimeError(
                "PROVIDER_BAD_RESPONSE", "provider returned an empty message"
            )
        usage = parsed.get("usage") if isinstance(parsed.get("usage"), dict) else {}
        return {
            "text": text,
            "model": str(parsed.get("model") or self.model),
            "provider": self.PROVIDER,
            "usage": {
                "prompt_tokens": usage.get("prompt_tokens"),
                "completion_tokens": usage.get("completion_tokens"),
                "total_tokens": usage.get("total_tokens"),
            },
            "elapsed_ms": int((time.monotonic() - started) * 1000),
        }

    def probe(self) -> Dict[str, Any]:
        result = self.invoke(
            "Reply with exactly: OK", system="You are a health check.", temperature=0, max_tokens=8
        )
        return {
            "ok": True,
            "state": "READY",
            "text": result["text"][:200],
            "model": result["model"],
            "elapsed_ms": result["elapsed_ms"],
            "usage": result["usage"],
        }


def _provider_message(body: str) -> str:
    """Pull the provider's message out of an error body without leaking headers."""
    try:
        parsed = json.loads(body)
    except json.JSONDecodeError:
        return body.strip()[:300] or "no body"
    if isinstance(parsed, dict):
        error = parsed.get("error")
        if isinstance(error, dict):
            return str(error.get("message") or error.get("type") or "")[:300]
        if isinstance(error, str):
            return error[:300]
    return body.strip()[:300] or "no body"
