"""Schema validator — Pass A: structural validation.

Validates that an agent spec has the correct shape, types, and required fields.
This is handled by Pydantic parsing in the loader. This module wraps that
with clear error reporting.
"""

from pathlib import Path
from dataclasses import dataclass, field

from pydantic import ValidationError

from agent_os.loaders.yaml_loader import load_agent_spec
from agent_os.contracts.models import AgentSpec


@dataclass
class ValidationResult:
    """Result of a validation pass."""

    passed: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def __bool__(self) -> bool:
        return self.passed


def validate_schema(spec_path: str | Path) -> tuple[AgentSpec | None, ValidationResult]:
    """Pass A: Validate agent spec structure.

    Returns the parsed AgentSpec if valid, None if not.
    """
    result = ValidationResult(passed=True)

    try:
        spec = load_agent_spec(spec_path)
    except FileNotFoundError as e:
        return None, ValidationResult(passed=False, errors=[str(e)])
    except ValidationError as e:
        errors = []
        for err in e.errors():
            loc = " → ".join(str(x) for x in err["loc"])
            errors.append(f"[{loc}] {err['msg']}")
        return None, ValidationResult(passed=False, errors=errors)
    except Exception as e:
        return None, ValidationResult(
            passed=False, errors=[f"Unexpected error: {e}"]
        )

    # Additional structural checks beyond Pydantic
    if not spec.capabilities:
        result.passed = False
        result.errors.append("Agent must declare at least one capability.")

    return spec, result
