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

import json
import os

from aijury.config import Settings
from aijury.learning.lesson_extractor import Lesson

MAX_INJECTED_LESSONS = 6


def load_lessons(settings: Settings, *, agent: str | None = None) -> list[str]:
    path = os.path.join(settings.failure_dir, "lessons.json")
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as handle:
        raw = json.load(handle)
    lessons = [Lesson(**item) for item in raw]
    selected = [
        lesson
        for lesson in lessons
        if lesson.active and (agent is None or not lesson.applies_to or agent in lesson.applies_to)
    ]
    selected.sort(key=lambda lesson: -lesson.occurrences)
    return [lesson.instruction for lesson in selected[:MAX_INJECTED_LESSONS]]
