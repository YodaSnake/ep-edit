from __future__ import annotations

import codecs
import difflib
import hashlib
from dataclasses import dataclass

from ep_edit.errors import DeterministicEditError
from ep_edit.planner import (
    EditPlan,
    FileMutation,
    FileMutationOperation,
)
from ep_edit.validators import (
    CandidateValidator,
    ValidationReport,
    validate_edit_plan,
)


@dataclass(frozen=True)
class CombinedPreview:
    text: str
    sha256: str
    validation_report: ValidationReport


@dataclass(frozen=True)
class _RepresentationState:
    exists: bool
    newline_style: str
    final_newline: str
    bom: bool | None


def build_validated_preview(
    plan: EditPlan,
    *,
    additional_validators: tuple[
        CandidateValidator,
        ...,
    ] = (),
) -> CombinedPreview:
    validation_report = validate_edit_plan(
        plan,
        additional_validators=additional_validators,
    )

    text = _render_combined_preview(
        plan,
        validation_report,
    )

    return CombinedPreview(
        text=text,
        sha256=hashlib.sha256(
            text.encode("utf-8")
        ).hexdigest(),
        validation_report=validation_report,
    )


def _render_combined_preview(
    plan: EditPlan,
    validation_report: ValidationReport,
) -> str:
    output: list[str] = [
        "=== PLAN ===",
        "Root: .",
        f"Files: {len(plan.files)}",
        f"Edits: {_edit_count(plan)}",
        (
            "Input fingerprint: "
            f"{_short_sha(plan.input_fingerprint)}"
        ),
        "",
    ]

    for file_index, mutation in enumerate(
        plan.files,
        start=1,
    ):
        before_state = _representation_state(
            mutation.before_bytes
            if mutation.before_exists
            else None
        )
        after_state = _representation_state(
            mutation.after_bytes
            if mutation.after_exists
            else None
        )
        removed_lines, added_lines = (
            _changed_line_counts(
                mutation
            )
        )

        output.extend(
            [
                (
                    f"=== FILE {file_index}/"
                    f"{len(plan.files)} ==="
                ),
                f"Target: {mutation.target}",
                (
                    "Operation: "
                    f"{mutation.operation.value}"
                ),
                (
                    "Edits: "
                    + ", ".join(
                        mutation.edit_refs
                    )
                ),
                (
                    "Before SHA-256: "
                    f"{_short_sha(mutation.before_sha256)}"
                ),
                (
                    "After SHA-256: "
                    f"{_short_sha(mutation.after_sha256)}"
                ),
                (
                    "Changed lines: "
                    f"-{removed_lines} +{added_lines}"
                ),
                (
                    "Newline: "
                    f"before={before_state.newline_style} "
                    f"after={after_state.newline_style}"
                ),
                (
                    "Final newline: "
                    f"before={before_state.final_newline} "
                    f"after={after_state.final_newline}"
                ),
            ]
        )

        if (
            before_state.bom is True
            or after_state.bom is True
        ):
            output.append(
                (
                    "BOM: "
                    f"before={_bom_label(before_state)} "
                    f"after={_bom_label(after_state)}"
                )
            )

        if mutation.create_parent_directories:
            output.append(
                (
                    "Create parent directories: "
                    + ", ".join(
                        mutation.create_parent_directories
                    )
                )
            )

        if (
            mutation.operation
            is FileMutationOperation.DELETE
        ):
            output.append(
                "DELETE TARGET: YES"
            )

        output.extend(
            [
                "Unified diff:",
                _render_unified_diff(
                    mutation
                ).rstrip("\n"),
                "",
            ]
        )

    output.append(
        "=== WARNINGS ==="
    )

    if plan.warnings:
        for warning in plan.warnings:
            output.append(
                (
                    f"{warning.target} "
                    f"[{warning.code}] "
                    f"EDIT {warning.edit_ref}: "
                    f"{warning.message}"
                )
            )
    else:
        output.append(
            "None"
        )

    output.extend(
        [
            "",
            "=== VALIDATION ===",
        ]
    )

    for result in validation_report.results:
        output.append(
            (
                f"{result.target} "
                f"[{result.validator}] "
                f"{result.status.value}: "
                f"{result.message}"
            )
        )

    output.append(
        ""
    )

    return "\n".join(
        output
    )


def _edit_count(
    plan: EditPlan,
) -> int:
    edit_refs: set[str] = set()

    for mutation in plan.files:
        edit_refs.update(
            mutation.edit_refs
        )

    for warning in plan.warnings:
        edit_refs.add(
            warning.edit_ref
        )

    return len(
        edit_refs
    )


def _short_sha(
    value: str | None,
) -> str:
    if value is None:
        return "ABSENT"

    return value[:12]


def _representation_state(
    raw: bytes | None,
) -> _RepresentationState:
    if raw is None:
        return _RepresentationState(
            exists=False,
            newline_style="ABSENT",
            final_newline="ABSENT",
            bom=None,
        )

    has_bom = raw.startswith(
        codecs.BOM_UTF8
    )
    body = (
        raw[len(codecs.BOM_UTF8):]
        if has_bom
        else raw
    )

    _decode_text_body(
        body
    )

    has_crlf = (
        b"\r\n" in body
    )
    without_crlf = body.replace(
        b"\r\n",
        b"",
    )

    if b"\r" in without_crlf:
        raise DeterministicEditError(
            "PREVIEW_RENDER_ERROR",
            "candidate contains unsupported lone CR",
        )

    has_lf = (
        b"\n" in without_crlf
    )

    if has_crlf and has_lf:
        raise DeterministicEditError(
            "PREVIEW_RENDER_ERROR",
            "candidate contains mixed LF / CRLF newlines",
        )

    if has_crlf:
        newline_style = "CRLF"
    elif has_lf:
        newline_style = "LF"
    else:
        newline_style = "NONE"

    return _RepresentationState(
        exists=True,
        newline_style=newline_style,
        final_newline=(
            "YES"
            if body.endswith(b"\n")
            else "NO"
        ),
        bom=has_bom,
    )


def _bom_label(
    state: _RepresentationState,
) -> str:
    if not state.exists:
        return "ABSENT"

    return (
        "YES"
        if state.bom
        else "NO"
    )


def _render_unified_diff(
    mutation: FileMutation,
) -> str:
    before_lines = _display_lines_keepends(
        mutation.before_bytes
        if mutation.before_exists
        else None
    )
    after_lines = _display_lines_keepends(
        mutation.after_bytes
        if mutation.after_exists
        else None
    )

    from_file = (
        f"a/{mutation.target}"
        if mutation.before_exists
        else "/dev/null"
    )
    to_file = (
        f"b/{mutation.target}"
        if mutation.after_exists
        else "/dev/null"
    )

    diff_items = list(
        difflib.unified_diff(
            before_lines,
            after_lines,
            fromfile=from_file,
            tofile=to_file,
            lineterm="\n",
        )
    )

    if not diff_items:
        if (
            mutation.before_exists
            != mutation.after_exists
        ):
            return (
                "(no logical-line diff; "
                "file existence changes)\n"
            )

        return (
            "(no logical-line diff; "
            "byte change is representation-only; "
            "see representation metadata)\n"
        )

    rendered: list[str] = []

    for item in diff_items:
        rendered.append(
            item
        )

        if not item.endswith(
            "\n"
        ):
            rendered.append(
                "\n"
            )
            rendered.append(
                "\\ No newline at end of file\n"
            )

    return "".join(
        rendered
    )


def _changed_line_counts(
    mutation: FileMutation,
) -> tuple[int, int]:
    before_lines = _display_logical_lines(
        mutation.before_bytes
        if mutation.before_exists
        else None
    )
    after_lines = _display_logical_lines(
        mutation.after_bytes
        if mutation.after_exists
        else None
    )

    matcher = difflib.SequenceMatcher(
        a=before_lines,
        b=after_lines,
        autojunk=False,
    )

    removed = 0
    added = 0

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag in {
            "replace",
            "delete",
        }:
            removed += (
                i2 - i1
            )

        if tag in {
            "replace",
            "insert",
        }:
            added += (
                j2 - j1
            )

    return (
        removed,
        added,
    )


def _display_lines_keepends(
    raw: bytes | None,
) -> list[str]:
    text = _normalized_display_text(
        raw
    )

    return text.splitlines(
        keepends=True
    )


def _display_logical_lines(
    raw: bytes | None,
) -> list[str]:
    text = _normalized_display_text(
        raw
    )

    return text.splitlines()


def _normalized_display_text(
    raw: bytes | None,
) -> str:
    if raw is None:
        return ""

    body = (
        raw[len(codecs.BOM_UTF8):]
        if raw.startswith(
            codecs.BOM_UTF8
        )
        else raw
    )
    text = _decode_text_body(
        body
    )
    normalized = text.replace(
        "\r\n",
        "\n",
    )

    if "\r" in normalized:
        raise DeterministicEditError(
            "PREVIEW_RENDER_ERROR",
            "preview text contains unsupported lone CR",
        )

    return normalized


def _decode_text_body(
    body: bytes,
) -> str:
    try:
        return body.decode(
            "utf-8"
        )
    except UnicodeDecodeError as exc:
        raise DeterministicEditError(
            "PREVIEW_RENDER_ERROR",
            "preview candidate is not valid UTF-8",
        ) from exc
