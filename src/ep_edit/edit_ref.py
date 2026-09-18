from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence


_EDIT_REF_SCHEMA = "ep-edit-ref-v1"
_EDIT_REF_PREFIX = "e_"
_EDIT_REF_HEX_LENGTH = 16


def generate_edit_ref(
    *,
    target: str,
    operation: str,
    search_lines: Sequence[str] | None = None,
    replace_lines: Sequence[str] | None = None,
    content_lines: Sequence[str] | None = None,
    newline: str | None = None,
    final_newline: str | None = None,
    bom: str | None = None,
) -> str:
    payload = {
        "schema": _EDIT_REF_SCHEMA,
        "target": target,
        "operation": operation,
        "search_lines": (
            list(search_lines)
            if search_lines is not None
            else None
        ),
        "replace_lines": (
            list(replace_lines)
            if replace_lines is not None
            else None
        ),
        "content_lines": (
            list(content_lines)
            if content_lines is not None
            else None
        ),
        "newline": newline,
        "final_newline": final_newline,
        "bom": bom,
    }

    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode(
        "utf-8"
    )

    digest = hashlib.sha256(
        canonical
    ).hexdigest()

    return (
        f"{_EDIT_REF_PREFIX}"
        f"{digest[:_EDIT_REF_HEX_LENGTH]}"
    )


def is_generated_edit_ref(
    value: str,
) -> bool:
    if not value.startswith(
        _EDIT_REF_PREFIX
    ):
        return False

    digest = value[
        len(_EDIT_REF_PREFIX):
    ]

    return (
        len(digest)
        == _EDIT_REF_HEX_LENGTH
        and all(
            character
            in "0123456789abcdef"
            for character in digest
        )
    )
