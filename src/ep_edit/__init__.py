"""Deterministic, review-first text file editing primitives."""

from ep_edit.errors import DeterministicEditError
from ep_edit.snapshot import (
    NewlineStyle,
    TextSnapshot,
    load_text_snapshot,
)
from ep_edit.specification import (
    EDIT_SPEC_VERSION,
    EditSpecification,
    SearchReplaceEdit,
    normalize_target_path,
    parse_edit_specification,
)

__all__ = [
    "EDIT_SPEC_VERSION",
    "DeterministicEditError",
    "EditSpecification",
    "NewlineStyle",
    "SearchReplaceEdit",
    "TextSnapshot",
    "load_text_snapshot",
    "normalize_target_path",
    "parse_edit_specification",
]
