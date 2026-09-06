"""Question taxonomy. Classification drives jury composition and verification."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class QuestionType(str, Enum):
    """How a question can be settled determines how we should argue about it."""

    FACTUAL = "factual"                # settled by retrieval against sources
    VERIFIABLE_TECHNICAL = "technical"  # settled by execution, tests, computation
    ANALYTICAL = "analytical"          # settled by reasoning over agreed premises
    GREY_NORMATIVE = "grey_normative"  # not settleable; correct output is the mapped disagreement


class VerificationMethod(str, Enum):
    RETRIEVAL = "retrieval"
    CODE_EXECUTION = "code_execution"
    RECOMPUTATION = "recomputation"
    CONSISTENCY = "consistency"
    STEELMAN_BALANCE = "steelman_balance"
    NONE = "none"


#: Which verifiers are meaningful for each question type. The Verifier agent
#: refuses to claim it checked something it structurally cannot check.
VERIFICATION_MATRIX: dict[QuestionType, tuple[VerificationMethod, ...]] = {
    QuestionType.FACTUAL: (VerificationMethod.RETRIEVAL, VerificationMethod.CONSISTENCY),
    QuestionType.VERIFIABLE_TECHNICAL: (
        VerificationMethod.CODE_EXECUTION,
        VerificationMethod.RECOMPUTATION,
        VerificationMethod.CONSISTENCY,
    ),
    QuestionType.ANALYTICAL: (
        VerificationMethod.CONSISTENCY,
        VerificationMethod.RECOMPUTATION,
    ),
    QuestionType.GREY_NORMATIVE: (
        VerificationMethod.CONSISTENCY,
        VerificationMethod.STEELMAN_BALANCE,
    ),
}


class Frame(BaseModel):
    """Output of the Intake/Framer agent: the case file before anyone argues."""

    question: str
    question_type: QuestionType
    restated_question: str = Field(description="The question as the system understands it.")
    hidden_assumptions: list[str] = Field(default_factory=list)
    success_criteria: list[str] = Field(
        default_factory=list, description="What a correct answer must satisfy."
    )
    required_perspectives: list[str] = Field(
        default_factory=list,
        description="Perspectives the Spawner turns into jurors, e.g. 'security', 'cost'.",
    )
    decomposition: list[str] = Field(
        default_factory=list, description="Sub-questions that must each be resolved."
    )

    @property
    def is_grey(self) -> bool:
        return self.question_type is QuestionType.GREY_NORMATIVE
