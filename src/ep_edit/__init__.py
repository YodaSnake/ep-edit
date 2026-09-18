"""Deterministic, review-first text file editing primitives."""

from ep_edit.errors import DeterministicEditError
from ep_edit.snapshot import (
    NewlineStyle,
    TextSnapshot,
    load_text_snapshot,
)
from ep_edit.specification import (
    EditSpecification,
    SearchReplaceEdit,
    normalize_target_path,
    parse_edit_specification,
)

__all__ = [
    "DeterministicEditError",
    "EditSpecification",
    "NewlineStyle",
    "SearchReplaceEdit",
    "TextSnapshot",
    "load_text_snapshot",
    "normalize_target_path",
    "parse_edit_specification",
]
