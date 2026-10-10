"""Skip the jury for greetings and other throwaway chat.

A "hi" is not a question. Convening the panel for it wastes the token budget
and produces a nonsense verdict. Detect these locally — no model call.
"""

from __future__ import annotations

import re

_PUNCT = re.compile(r"[^\w\s']+", re.UNICODE)
_SPACE = re.compile(r"\s+")

_CASUAL = re.compile(
    r"""
    ^
    (
        (hi+|h+ello+|hey+|heya|hiya|yo+|sup|howdy|hola|namaste)
            (\s+there)?
      | good\s*(morning|afternoon|evening|night)
      | (thanks?|thank\s+you|thx|ty)(\s+(so\s+)?much)?
      | (bye+|goodbye|good\s+bye|see\s+y(a|ou)|cya|later)
      | how\s+are\s+you(\s+doing)?
      | how('?s|\s+is)\s+it\s+going
      | what('?s|\s+is)\s+up
      | (ok|okay|cool|nice)
      | who\s+are\s+you
      | what\s+(is|are)\s+(this|you)
    )
    $
    """,
    re.IGNORECASE | re.VERBOSE,
)


def _normalize(text: str) -> str:
    cleaned = _PUNCT.sub(" ", text.strip().lower())
    return _SPACE.sub(" ", cleaned).strip()


def casual_reply(text: str) -> str | None:
    """Return a one-line reply if `text` is small-talk, otherwise None."""
    normalized = _normalize(text)
    if not normalized or not _CASUAL.match(normalized):
        return None
    if normalized.startswith(("thank", "thx", "ty")):
        return "You're welcome."
    if normalized.startswith(("bye", "goodbye", "good bye", "see ", "cya", "later")):
        return "Goodbye."
    if "how are you" in normalized or "it going" in normalized:
        return "Hello. Send a question when you want the panel to deliberate."
    if normalized.startswith(("who are", "what is", "what are")):
        return "I'm AI Jury. Send a real question and the panel will deliberate."
    return "Hello."
