"""OpenAI-compatible gateways as data, not as new client classes.

HCNSEC, Tokenera, OpenAI, or a random `/v1` host all speak the same protocol.
The console stores them in a local book; `OpenAICompatClient` is the only adapter.
Adding a provider is: label, base URL, key, model — then seat it.
"""

from __future__ import annotations

import json
import os
import re
import stat
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any

from aijury.config import Settings

_SLUG = re.compile(r"[^a-z0-9]+")
_RESERVED = {"mock", "anthropic"}


@dataclass(frozen=True)
class Preset:
    id: str
    label: str
    base_url: str
    model: str
    hint: str = ""


#: Click-to-fill templates. Keys never live here.
PRESETS: tuple[Preset, ...] = (
    Preset(
        "hcnsec",
        "HCNSEC",
        "https://api.hcnsec.cn/v1",
        "Qwen3.8-27B",
        "The gateway this project already uses.",
    ),
    Preset(
        "tokenera",
        "Tokenera",
        "",
        "",
        "Paste Tokenera's OpenAI-compatible base URL (usually …/v1), key, and model.",
    ),
    Preset(
        "openai",
        "OpenAI",
        "https://api.openai.com/v1",
        "gpt-4o-mini",
        "Official OpenAI API.",
    ),
    Preset(
        "custom",
        "Custom",
        "",
        "",
        "Any host that implements POST /v1/chat/completions.",
    ),
)


@dataclass
class Gateway:
    id: str
    label: str
    base_url: str
    model: str = ""
    model_pool: list[str] = field(default_factory=list)
    api_key: str = ""

    def public(self) -> dict[str, Any]:
        """Wire shape. Never includes the raw key."""
        tail = self.api_key[-4:] if len(self.api_key) >= 4 else ""
        return {
            "id": self.id,
            "label": self.label,
            "base_url": self.base_url,
            "model": self.model,
            "model_pool": list(self.model_pool),
            "key_set": bool(self.api_key),
            "key_hint": f"…{tail}" if tail else "",
        }


def slug(label: str) -> str:
    cleaned = _SLUG.sub("-", label.strip().lower()).strip("-")[:40]
    return cleaned or "gateway"


def is_openai_compat(provider: str) -> bool:
    return provider not in _RESERVED


def apply_gateway(settings: Settings, gateway: Gateway) -> Settings:
    """Point the running jury at this gateway. No process restart."""
    pool = tuple(m.strip() for m in gateway.model_pool if m.strip())
    return replace(
        settings,
        provider=gateway.id,
        model=gateway.model,
        model_pool=pool,
        openai_base_url=gateway.base_url.rstrip("/"),
        hcnsec_api_key=gateway.api_key,
    )


def apply_mock(settings: Settings) -> Settings:
    return replace(settings, provider="mock")


class GatewayBook:
    """On-disk roster of gateways. Keys stay on this machine, mode 600."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.gateways: dict[str, Gateway] = {}
        self.active: str = "mock"
        self.load()

    def load(self) -> None:
        if not self.path.is_file():
            return
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        self.active = str(raw.get("active") or "mock")
        self.gateways = {}
        for item in raw.get("gateways") or []:
            gw = Gateway(
                id=str(item["id"]),
                label=str(item.get("label") or item["id"]),
                base_url=str(item.get("base_url") or ""),
                model=str(item.get("model") or ""),
                model_pool=[str(m) for m in item.get("model_pool") or [] if str(m).strip()],
                api_key=str(item.get("api_key") or ""),
            )
            self.gateways[gw.id] = gw

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "active": self.active,
            "gateways": [asdict(g) for g in self.gateways.values()],
        }
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        tmp.replace(self.path)
        try:
            os.chmod(self.path, stat.S_IRUSR | stat.S_IWUSR)
        except OSError:
            pass

    def hydrate_from_settings(self, settings: Settings) -> None:
        """First run: if .env already named a live gateway, remember it."""
        if self.gateways or settings.provider in _RESERVED:
            return
        if not settings.openai_base_url and not settings.hcnsec_api_key:
            return
        gw = Gateway(
            id=settings.provider,
            label="HCNSEC" if settings.provider == "hcnsec" else settings.provider,
            base_url=settings.openai_base_url,
            model=settings.model,
            model_pool=list(settings.model_pool),
            api_key=settings.hcnsec_api_key,
        )
        self.gateways[gw.id] = gw
        self.active = gw.id
        self.save()

    def catalog(self) -> dict[str, Any]:
        return {
            "active": self.active,
            "presets": [asdict(p) for p in PRESETS],
            "gateways": [g.public() for g in self.gateways.values()],
        }

    def upsert(
        self,
        *,
        label: str,
        base_url: str,
        model: str,
        model_pool: list[str] | None = None,
        api_key: str = "",
        gateway_id: str | None = None,
    ) -> Gateway:
        label = label.strip()
        if not label:
            raise ValueError("label is required")
        ident = (gateway_id or "").strip() or slug(label)
        if ident in _RESERVED:
            raise ValueError(f"{ident!r} is reserved")
        existing = self.gateways.get(ident)
        key = api_key.strip() if api_key.strip() else (existing.api_key if existing else "")
        gw = Gateway(
            id=ident,
            label=label,
            base_url=base_url.strip().rstrip("/"),
            model=model.strip(),
            model_pool=[m.strip() for m in (model_pool or []) if m.strip()],
            api_key=key,
        )
        if not gw.base_url:
            raise ValueError("base_url is required")
        self.gateways[ident] = gw
        self.save()
        return gw

    def get(self, gateway_id: str) -> Gateway:
        if gateway_id not in self.gateways:
            raise KeyError(gateway_id)
        return self.gateways[gateway_id]

    def drop(self, gateway_id: str) -> None:
        self.gateways.pop(gateway_id, None)
        if self.active == gateway_id:
            self.active = "mock"
        self.save()

    def seat(self, gateway_id: str) -> None:
        if gateway_id == "mock":
            self.active = "mock"
            self.save()
            return
        if gateway_id not in self.gateways:
            raise KeyError(gateway_id)
        self.active = gateway_id
        self.save()


def list_remote_models(base_url: str, api_key: str) -> list[str]:
    """Ask the gateway which models it serves. Fast path for the dock."""
    try:
        from openai import OpenAI
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("openai package not installed") from exc
    client = OpenAI(base_url=base_url, api_key=api_key, timeout=20.0)
    page = client.models.list()
    names = sorted({getattr(item, "id", "") for item in page.data if getattr(item, "id", "")})
    return names[:80]
