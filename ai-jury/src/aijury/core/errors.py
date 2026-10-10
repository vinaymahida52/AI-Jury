"""Error taxonomy. Distinguishes our failures from the model's."""

from __future__ import annotations


class AIJuryError(Exception):
    """Base for everything this system raises deliberately."""


class DeliberationError(AIJuryError):
    """Orchestration could not proceed."""


class VerificationError(AIJuryError):
    """A verifier could not run, as distinct from a claim failing verification."""


class UnsafeInputError(AIJuryError):
    """Input rejected by the security layer before reaching any agent."""
