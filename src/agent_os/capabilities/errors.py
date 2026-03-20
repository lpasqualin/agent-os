"""Structured validation error type for capability loader/validator."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional


@dataclass(frozen=True)
class ValidationError:
    """A single validation failure or warning.

    code       — stable machine-readable key; never changes between versions
    message    — human-readable description; suitable for operator output
    source_file — path of the file where the problem originates
    source_path — dotted/indexed path within the document (e.g. "capabilities[2].id")
    line        — 1-based line number if available; None otherwise
    severity    — "error" blocks validation; "warning" is advisory only
    """

    code: str
    message: str
    source_file: Optional[str] = None
    source_path: Optional[str] = None
    line: Optional[int] = None
    severity: Literal["error", "warning"] = "error"

    def __str__(self) -> str:
        parts: list[str] = []
        if self.source_file:
            parts.append(self.source_file)
        if self.source_path:
            parts.append(self.source_path)
        prefix = ": ".join(parts)
        if prefix:
            return f"{prefix}: {self.message}"
        return self.message
