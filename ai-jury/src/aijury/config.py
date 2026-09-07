"""Central configuration. Everything tunable lives here, sourced from env.

No module outside this one reads os.environ. That keeps the system testable and
makes the full set of knobs discoverable in one place.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def load_dotenv(path: str | Path | None = None, *, override: bool = False) -> dict[str, str]:
    """Load a .env file into os.environ.

    Deliberately dependency-free: one small function beats pulling python-dotenv
    in for this. Walks up from the current directory so the CLI works from any
    subdirectory of the project.

    later lines in the same file win; a value already in the process
    environment still wins unless override=True.
    """
    if path is None:
        here = Path.cwd().resolve()
        for candidate in [here, *here.parents]:
            if (candidate / ".env").is_file():
                path = candidate / ".env"
                break
        else:
            return {}

    env_path = Path(path)
    if not env_path.is_file():
        return {}

    loaded: dict[str, str] = {}
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip().removeprefix("export ").strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if not key:
            continue
        already = key in os.environ
        from_this_file = key in loaded
        if override or not already or from_this_file:
            os.environ[key] = value
        loaded[key] = value
    return loaded


def _int(key: str, default: int) -> int:
    raw = os.environ.get(key)
    return int(raw) if raw else default


def _float(key: str, default: float) -> float:
    raw = os.environ.get(key)
    return float(raw) if raw else default


@dataclass(frozen=True)
class Budget:
    """Hard ceilings. Exceeding any of these terminates deliberation immediately."""

    max_rounds: int = 16
    max_jurors: int = 8
    max_tokens: int = 200_000
    max_wall_clock_seconds: float = 300.0
    max_llm_calls: int = 120


@dataclass(frozen=True)
class Settings:
    provider: str = "mock"
    model: str = ""
    # Distinct models for distinct jurors. Model diversity is the point of a jury;
    # five copies of one model share one set of blind spots.
    model_pool: tuple[str, ...] = ()
    budget: Budget = field(default_factory=Budget)
    # Below this confidence the system reports unresolved rather than asserting.
    confidence_floor: float = 0.45
    # Rounds of stable-but-divergent positions before we call it a genuine grey area.
    stability_window: int = 2
    trace_dir: str = ".traces"
    failure_dir: str = ".failures"
    seed: int = 7
    hcnsec_api_key: str = ""
    openai_base_url: str = "https://api.hcnsec.cn/v1"
    #: Local gateway book (keys, URLs). Never commit this file.
    gateways_path: str = ".aijury/gateways.json"

    @classmethod
    def from_env(cls, *, dotenv: bool = True) -> Settings:
        """Build settings from the environment, loading .env first if present."""
        if dotenv:
            load_dotenv()
        pool = os.environ.get("AIJURY_MODEL_POOL", "")
        return cls(
            provider=os.environ.get("AIJURY_PROVIDER", "mock"),
            model=os.environ.get("AIJURY_MODEL", ""),
            model_pool=tuple(m.strip() for m in pool.split(",") if m.strip()),
            budget=Budget(
                max_rounds=_int("AIJURY_MAX_ROUNDS", 16),
                max_jurors=_int("AIJURY_MAX_JURORS", 8),
                max_tokens=_int("AIJURY_TOKEN_BUDGET", 200_000),
                max_wall_clock_seconds=_float("AIJURY_WALL_CLOCK_SECONDS", 300.0),
                max_llm_calls=_int("AIJURY_MAX_LLM_CALLS", 120),
            ),
            confidence_floor=_float("AIJURY_CONFIDENCE_FLOOR", 0.45),
            stability_window=_int("AIJURY_STABILITY_WINDOW", 2),
            trace_dir=os.environ.get("AIJURY_TRACE_DIR", ".traces"),
            failure_dir=os.environ.get("AIJURY_FAILURE_DIR", ".failures"),
            seed=_int("AIJURY_SEED", 7),
            hcnsec_api_key=os.environ.get("HCNSEC_API_KEY")
            or os.environ.get("AIJURY_API_KEY")
            or os.environ.get("OPENAI_API_KEY")
            or "",
            openai_base_url=os.environ.get(
                "AIJURY_OPENAI_BASE_URL", "https://api.hcnsec.cn/v1"
            ),
            gateways_path=os.environ.get("AIJURY_GATEWAYS", ".aijury/gateways.json"),
        )
