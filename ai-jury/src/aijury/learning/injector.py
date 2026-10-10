"""Phase 6c: lesson injection.

Lessons enter agent context as explicit constraints. Two rules keep this from
degrading the system:

1. Only active lessons are injected. The regression gate deactivates any lesson
   that makes eval scores worse — lessons routinely fix one failure mode and
   open another, so nothing ships unvalidated.
2. The injected set is capped. Prompts stuffed with accumulated corrections
   perform worse than clean ones; past a handful, lessons should be promoted
   into code (new verifiers, new termination rules) rather than more prose.
"""

from __future__ import annotations

from aijury.config import Settings

MAX_INJECTED_LESSONS = 6


def load_lessons(settings: Settings, *, agent: str | None = None) -> list[str]:
    from aijury.learning.repository import get_repository

    return get_repository(settings).active_lesson_instructions(agent=agent)
