"""Arithmetic recomputation.

Catches the most common and most embarrassing class of confident error. Uses a
restricted AST evaluator rather than eval(); a verifier that can be made to
execute arbitrary code by a claim it is checking is an injection vector.
"""

from __future__ import annotations

import ast
import operator
import re

from aijury.contracts.messages import Claim
from aijury.contracts.taxonomy import VerificationMethod
from aijury.verification.base import VerificationResult

_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}

_EQUATION = re.compile(r"([0-9][0-9\s()+\-*/%.^]*?)\s*=\s*(-?[0-9][0-9,.]*)")
_MAX_POW = 1_000_000


def safe_eval(expression: str) -> float:
    """Evaluate a pure arithmetic expression. Raises on anything else."""
    tree = ast.parse(expression.replace("^", "**"), mode="eval")
    return _eval_node(tree.body)


def _eval_node(node: ast.AST) -> float:
    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
            raise ValueError("non-numeric constant")
        return float(node.value)
    if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
        left, right = _eval_node(node.left), _eval_node(node.right)
        if isinstance(node.op, ast.Pow) and abs(right) > 64:
            raise ValueError("exponent too large")
        result = _OPS[type(node.op)](left, right)
        if abs(result) > _MAX_POW**4:
            raise ValueError("result out of range")
        return float(result)
    if isinstance(node, ast.UnaryOp) and type(node.op) in _OPS:
        return float(_OPS[type(node.op)](_eval_node(node.operand)))
    raise ValueError(f"disallowed expression node: {type(node).__name__}")


class RecomputationVerifier:
    method = VerificationMethod.RECOMPUTATION

    def applies(self, claim: Claim) -> bool:
        return bool(_EQUATION.search(claim.text))

    def check(self, claim: Claim) -> VerificationResult:
        match = _EQUATION.search(claim.text)
        if not match:
            return VerificationResult(claim.id, self.method, False, "no equation found")
        expression, stated = match.group(1), match.group(2).replace(",", "")
        try:
            computed = safe_eval(expression)
            expected = float(stated)
        except (ValueError, SyntaxError, ZeroDivisionError, OverflowError) as exc:
            return VerificationResult(
                claim.id, self.method, False, f"could not recompute: {exc}", decisive=False
            )
        tolerance = max(1e-9, abs(expected) * 1e-6)
        ok = abs(computed - expected) <= tolerance
        return VerificationResult(
            claim.id,
            self.method,
            ok,
            f"{expression.strip()} = {computed:g}, claim stated {expected:g}",
            decisive=True,
        )
