"""Any OpenAI-compatible /chat/completions endpoint, over the standard library.

No SDK on purpose. A QA tool that drags in a vendor client becomes unrunnable the
next time that client makes a breaking change, and this one needs to still work a
year from now with no maintenance.

Configuration is environment-only, so a target's credentials never end up in a
committed config file:

    REVGATE_TARGET_BASE_URL   e.g. https://api.openai.com/v1
    REVGATE_TARGET_MODEL      e.g. gpt-4o-mini
    REVGATE_TARGET_API_KEY    optional; omitted for local servers that need no key
    REVGATE_TARGET_TIMEOUT    seconds, default 60
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request


class TargetError(RuntimeError):
    """Raised when the target cannot be reached or answers unusably."""


class OpenAICompatTarget:
    name = "openai"
    description = "OpenAI-compatible /chat/completions endpoint"

    def __init__(self, system: str = "") -> None:
        base = (os.environ.get("REVGATE_TARGET_BASE_URL") or "").strip().rstrip("/")
        model = (os.environ.get("REVGATE_TARGET_MODEL") or "").strip()
        if not base or not model:
            raise TargetError(
                "the openai target needs REVGATE_TARGET_BASE_URL and REVGATE_TARGET_MODEL set. "
                "For a local server, a base URL of http://localhost:11434/v1 and any model name works."
            )
        self.base = base
        self.model = model
        self.api_key = (os.environ.get("REVGATE_TARGET_API_KEY") or "").strip()
        try:
            self.timeout = float(os.environ.get("REVGATE_TARGET_TIMEOUT", "60"))
        except ValueError:
            self.timeout = 60.0
        self.system = system

    def reply(self, history: list[dict[str, str]]) -> str:
        messages: list[dict[str, str]] = []
        if self.system:
            messages.append({"role": "system", "content": self.system})
        messages.extend(history)

        payload = json.dumps({
            "model": self.model,
            "messages": messages,
            "temperature": 0,
        }).encode("utf-8")

        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        request = urllib.request.Request(
            f"{self.base}/chat/completions", data=payload, headers=headers, method="POST"
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                body = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:400]
            raise TargetError(f"target returned HTTP {exc.code}: {detail}") from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise TargetError(f"could not reach {self.base}: {exc}") from exc
        except json.JSONDecodeError as exc:
            raise TargetError(f"target returned output that is not JSON: {exc}") from exc

        try:
            content = body["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise TargetError(
                f"target response had no choices[0].message.content: {json.dumps(body)[:400]}"
            ) from exc
        return content or ""
