"""Small DeepSeek API client using only the Python standard library."""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any


class DeepSeekError(RuntimeError):
    """Raised when the DeepSeek API request or JSON parsing fails."""


def _extract_json_object(text: str) -> dict[str, Any]:
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            raise
        data = json.loads(text[start : end + 1])
    if not isinstance(data, dict):
        raise DeepSeekError("DeepSeek returned JSON, but the root is not an object")
    return data


@dataclass
class DeepSeekClient:
    api_key: str
    model: str = "deepseek-v4-flash"
    base_url: str = "https://api.deepseek.com"
    timeout_sec: int = 180
    max_retries: int = 4
    retry_base_delay_sec: float = 2.0
    thinking: str | None = None
    reasoning_effort: str | None = None

    def chat_json(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.1,
        max_tokens: int = 8192,
    ) -> dict[str, Any]:
        """Call /chat/completions in JSON mode and return parsed JSON."""

        url = self.base_url.rstrip("/") + "/chat/completions"
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
            "response_format": {"type": "json_object"},
        }
        if self.thinking:
            payload["thinking"] = {"type": self.thinking}
        if self.reasoning_effort:
            payload["reasoning_effort"] = self.reasoning_effort
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "User-Agent": "sci-evo-competition-pipeline/0.1",
        }

        last_error: str | None = None
        for attempt in range(1, self.max_retries + 1):
            req = urllib.request.Request(url, data=body, headers=headers, method="POST")
            try:
                with urllib.request.urlopen(req, timeout=self.timeout_sec) as resp:
                    raw = resp.read().decode("utf-8", errors="replace")
                parsed = json.loads(raw)
                choice = parsed.get("choices", [{}])[0]
                message = choice.get("message") or {}
                content = (message.get("content") or "").strip()
                if not content:
                    last_error = "empty message content"
                    raise DeepSeekError(last_error)
                output = _extract_json_object(content)
                output["_api_usage"] = parsed.get("usage", {})
                output["_api_model"] = parsed.get("model", self.model)
                output["_api_finish_reason"] = choice.get("finish_reason")
                return output
            except urllib.error.HTTPError as exc:
                error_body = exc.read().decode("utf-8", errors="replace")
                last_error = f"HTTP {exc.code}: {error_body[:1000]}"
                if exc.code not in {408, 409, 429, 500, 502, 503, 504}:
                    break
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, DeepSeekError) as exc:
                last_error = str(exc)

            if attempt < self.max_retries:
                time.sleep(self.retry_base_delay_sec * (2 ** (attempt - 1)))

        raise DeepSeekError(last_error or "unknown DeepSeek API failure")
