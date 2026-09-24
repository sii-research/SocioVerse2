"""The single chokepoint that makes 'skills pass only typed artifacts' literally true.

Every workflow skill loads its input via validate_handoff(path, Schema) and writes its
output via write_artifact(path, model). A half-formed dict cannot cross a stage boundary:
if the artifact does not satisfy the contract, the pipeline stops here with a typed error.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Type, TypeVar

from pydantic import BaseModel, ValidationError

T = TypeVar("T", bound=BaseModel)


class HandoffError(Exception):
    """Raised when an inter-skill artifact is missing, unparseable, or off-contract."""


def validate_handoff(path: str | Path, schema: Type[T]) -> T:
    """Load + validate a workspace artifact against its schema. Raises HandoffError."""
    p = Path(path)
    if not p.exists():
        raise HandoffError(f"Handoff artifact missing: {p}")
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise HandoffError(f"Handoff artifact is not valid JSON: {p}\n  {e}") from e
    try:
        return schema.model_validate(data)
    except ValidationError as e:
        raise HandoffError(
            f"Handoff artifact {p} violates the {schema.__name__} contract:\n{e}"
        ) from e


def write_artifact(path: str | Path, model: BaseModel) -> Path:
    """Serialize a validated model to a workspace artifact (creates parent dirs)."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(model.model_dump_json(indent=2), encoding="utf-8")
    return p
