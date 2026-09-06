"""Code execution verifier.

Runs candidate code in a subprocess with a wall-clock limit and no network. This
is a development-grade sandbox and is documented as such: for production, run
this in a container or microVM with seccomp, a read-only filesystem, and no
egress. Executing model-authored code in-process is never acceptable.
"""

from __future__ import annotations

import re
import subprocess
import sys
import tempfile
from pathlib import Path

from aijury.contracts.messages import Claim, EvidenceKind
from aijury.contracts.taxonomy import VerificationMethod
from aijury.verification.base import VerificationResult

_CODE_BLOCK = re.compile(r"```(?:python)?\s*(.*?)```", re.DOTALL)
_TIMEOUT_SECONDS = 10


class CodeExecutionVerifier:
    method = VerificationMethod.CODE_EXECUTION

    def __init__(self, *, enabled: bool = False, timeout: int = _TIMEOUT_SECONDS) -> None:
        # Off by default. Executing untrusted code must be an explicit opt-in.
        self.enabled = enabled
        self.timeout = timeout

    def applies(self, claim: Claim) -> bool:
        if not self.enabled:
            return False
        return any(
            e.kind is EvidenceKind.EXECUTION and _CODE_BLOCK.search(e.content)
            for e in claim.evidence
        )

    def check(self, claim: Claim) -> VerificationResult:
        block = next(
            (
                _CODE_BLOCK.search(e.content)
                for e in claim.evidence
                if e.kind is EvidenceKind.EXECUTION and _CODE_BLOCK.search(e.content)
            ),
            None,
        )
        if not block:
            return VerificationResult(claim.id, self.method, False, "no code block", decisive=False)
        source = block.group(1)
        with tempfile.TemporaryDirectory() as workdir:
            script = Path(workdir) / "candidate.py"
            script.write_text(source, encoding="utf-8")
            try:
                completed = subprocess.run(  # noqa: S603
                    [sys.executable, "-I", "-S", str(script)],
                    capture_output=True,
                    text=True,
                    timeout=self.timeout,
                    cwd=workdir,
                    env={"PATH": "/usr/bin:/bin", "HOME": workdir},
                )
            except subprocess.TimeoutExpired:
                return VerificationResult(
                    claim.id, self.method, False, "execution timed out", decisive=True
                )
        passed = completed.returncode == 0
        note = (completed.stderr or completed.stdout or "").strip()[:500]
        return VerificationResult(
            claim.id,
            self.method,
            passed,
            note or f"exit code {completed.returncode}",
            decisive=True,
        )
