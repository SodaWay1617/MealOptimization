from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional
from uuid import uuid4
from urllib import error, request
from urllib.parse import urlsplit

from app.sync.prompt import build_llm_messages


class LLMParseError(RuntimeError):
    pass


@dataclass(frozen=True)
class LLMSettings:
    provider: str
    model: str
    api_key: Optional[str]
    api_base: str
    api_path: str
    temperature: float
    timeout_seconds: int
    json_mode: bool
    log_path: Path
    openrouter_provider: str = ""

    @classmethod
    def from_env(cls) -> "LLMSettings":
        return cls(
            provider=os.getenv("LLM_PROVIDER", "mock"),
            model=os.getenv("LLM_MODEL", "gpt-4o-mini"),
            api_key=os.getenv("LLM_API_KEY"),
            api_base=os.getenv("LLM_API_BASE", "https://api.openai.com/v1"),
            api_path=os.getenv("LLM_API_PATH", "/chat/completions"),
            temperature=_float_from_env("LLM_TEMPERATURE", default=0.0),
            timeout_seconds=_int_from_env("LLM_TIMEOUT_SECONDS", default=120),
            json_mode=_bool_from_env("LLM_JSON_MODE", default=True),
            log_path=_log_path_from_env(),
            openrouter_provider=os.getenv("LLM_OPENROUTER_PROVIDER", "").strip(),
        )


class LLMClient:
    def __init__(self, settings: LLMSettings) -> None:
        self.settings = settings

    def parse_recipe(
        self,
        markdown_text: str,
        *,
        source_path: str,
        category_hint: Optional[str],
    ) -> Dict[str, Any]:
        provider = self.settings.provider.lower()
        if provider == "mock":
            return _mock_parse(markdown_text, source_path=source_path, category_hint=category_hint)
        if provider in {"openai", "openai_compatible", "openai-compatible"}:
            return self._parse_with_openai(
                markdown_text,
                source_path=source_path,
                category_hint=category_hint,
            )
        raise LLMParseError(f"Unsupported LLM_PROVIDER: {self.settings.provider}")

    def _parse_with_openai(
        self,
        markdown_text: str,
        *,
        source_path: str,
        category_hint: Optional[str],
    ) -> Dict[str, Any]:
        return self.complete_json(
            build_llm_messages(markdown_text, source_path=source_path, category_hint=category_hint),
            log_context={"source_path": source_path, "category_hint": category_hint},
        )

    def complete_json(
        self, messages: list[dict], *, log_context: dict | None = None
    ) -> Dict[str, Any]:
        if self.settings.provider.lower() not in {"openai", "openai_compatible", "openai-compatible"}:
            raise LLMParseError("An OpenAI-compatible provider is required")
        if not self.settings.api_key:
            raise LLMParseError("LLM_API_KEY is required for LLM_PROVIDER=openai")

        url = _build_url(self.settings.api_base, self.settings.api_path)
        request_id = uuid4().hex
        payload = {
            "model": self.settings.model,
            "messages": messages,
            "temperature": self.settings.temperature,
        }
        if self.settings.json_mode:
            payload["response_format"] = {"type": "json_object"}
        if self.settings.openrouter_provider and urlsplit(url).hostname == "openrouter.ai":
            payload["provider"] = {
                "only": [self.settings.openrouter_provider],
                "allow_fallbacks": False,
            }
        def log(payload: dict) -> None:
            if log_context is not None:
                self._write_log({**log_context, **payload})

        log(
            {
                "event": "llm_call",
                "request_id": request_id,
                "provider": self.settings.provider,
                "model": self.settings.model,
                "url": url,
                "request": payload,
            }
        )
        body = json.dumps(payload).encode("utf-8")
        req = request.Request(
            url=url,
            data=body,
            headers={
                "Authorization": f"Bearer {self.settings.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with request.urlopen(req, timeout=self.settings.timeout_seconds) as response:
                status_code = getattr(response, "status", None)
                raw = response.read().decode("utf-8")
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            log(
                {
                    "event": "llm_error",
                    "request_id": request_id,
                    "provider": self.settings.provider,
                    "model": self.settings.model,
                    "url": url,
                    "error_type": "http_error",
                    "status_code": exc.code,
                    "error": detail,
                }
            )
            raise LLMParseError(f"LLM HTTP error {exc.code}: {detail}") from exc
        except error.URLError as exc:
            log(
                {
                    "event": "llm_error",
                    "request_id": request_id,
                    "provider": self.settings.provider,
                    "model": self.settings.model,
                    "url": url,
                    "error_type": "connection_error",
                    "error": str(exc.reason),
                }
            )
            raise LLMParseError(f"LLM connection error: {exc.reason}") from exc

        log(
            {
                "event": "llm_response",
                "request_id": request_id,
                "provider": self.settings.provider,
                "model": self.settings.model,
                "url": url,
                "status_code": status_code,
                "response": _safe_json_or_text(raw),
            }
        )

        try:
            decoded = json.loads(raw)
            content = _extract_content(decoded)
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            raise LLMParseError("Unexpected OpenAI response payload") from exc

        return _parse_json_object(content)

    def _write_log(self, payload: Dict[str, Any]) -> None:
        record = {
            "ts": datetime.now(timezone.utc).isoformat(),
            **payload,
        }
        self.settings.log_path.parent.mkdir(parents=True, exist_ok=True)
        with self.settings.log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False))
            handle.write("\n")


def _mock_parse(
    markdown_text: str,
    *,
    source_path: str,
    category_hint: Optional[str],
) -> Dict[str, Any]:
    title = Path(source_path).stem
    for line in markdown_text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            header = stripped.lstrip("#").strip()
            if header:
                title = header
                break
    category = category_hint or "main"
    return {
        "title": title,
        "category": category,
        "servings": None,
        "ingredients": [
            {
                "name": "unspecified ingredient",
                "amount": None,
                "unit": "по вкусу",
                "note": "mock parser fallback",
            }
        ],
        "steps": ["Review source markdown to replace mock extraction."],
        "source_path": source_path,
        "notes": "mock parsing mode",
        "confidence": 0.1,
    }


def _build_url(api_base: str, api_path: str) -> str:
    return api_base.rstrip("/") + "/" + api_path.lstrip("/")


def _extract_content(payload: Dict[str, Any]) -> str:
    content = payload["choices"][0]["message"]["content"]
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text" and isinstance(item.get("text"), str):
                parts.append(item["text"])
        if parts:
            return "\n".join(parts)
    raise LLMParseError("Model content must be a string or text parts")


def _parse_json_object(content: str) -> Dict[str, Any]:
    normalized = content.strip()
    if normalized.startswith("```"):
        lines = normalized.splitlines()
        if len(lines) >= 3 and lines[-1].strip() == "```":
            normalized = "\n".join(lines[1:-1]).strip()
            if normalized.lower().startswith("json"):
                normalized = normalized[4:].lstrip()
    try:
        parsed = json.loads(normalized)
    except json.JSONDecodeError as exc:
        raise LLMParseError("Model returned non-JSON content") from exc
    if not isinstance(parsed, dict):
        raise LLMParseError("Model output must be a JSON object")
    return parsed


def _safe_json_or_text(raw: str) -> Any:
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


def _log_path_from_env() -> Path:
    raw = os.getenv("LLM_LOG_PATH")
    if raw:
        return Path(raw).expanduser()
    return Path(__file__).resolve().parents[2] / "logs" / "llm.log"


def _bool_from_env(name: str, *, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    value = raw.strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    raise LLMParseError(f"{name} must be a boolean value")


def _float_from_env(name: str, *, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise LLMParseError(f"{name} must be a number") from exc


def _int_from_env(name: str, *, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise LLMParseError(f"{name} must be an integer") from exc
