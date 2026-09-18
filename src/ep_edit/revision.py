from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import Enum

from ep_edit.edit_ref import (
    is_generated_edit_ref,
)
from ep_edit.errors import DeterministicEditError
from ep_edit.specification import (
    parse_edit_specification,
)
from ep_edit.structural_escape import (
    REVISION_EDIT_PAYLOAD_MARKERS,
    decode_structural_payload_line,
)


class RevisionOperationKind(str, Enum):
    REVISE = "REVISE_EDIT"
    REMOVE = "REMOVE_EDIT"
    ADD = "ADD_EDIT"


@dataclass(frozen=True)
class RevisionOperation:
    kind: RevisionOperationKind
    edit_ref: str
    edit_block: str | None
    replacement_edit_ref: str | None = None


@dataclass(frozen=True)
class RevisionSpecification:
    operations: tuple[RevisionOperation, ...]


@dataclass(frozen=True)
class RevisionResult:
    revised_text: str
    base_fingerprint: str
    revised_fingerprint: str
    revised_edit_refs: tuple[str, ...]
    removed_edit_refs: tuple[str, ...]
    added_edit_refs: tuple[str, ...]
    revised_edit_ref_mappings: tuple[
        tuple[str, str],
        ...
    ] = ()


@dataclass(frozen=True)
class _BaseEditBlock:
    edit_ref: str
    start_offset: int
    end_offset: int
    ends_with_newline: bool


def parse_revision_specification(
    text: str,
) -> RevisionSpecification:
    lines = _split_revision_lines(
        text
    )
    index = _skip_blank_lines(
        lines,
        0,
    )

    operations: list[
        RevisionOperation
    ] = []
    targeted_refs: set[str] = set()
    added_refs: set[str] = set()

    while True:
        index = _skip_blank_lines(
            lines,
            index,
        )

        if index >= len(lines):
            break

        operation_line = lines[index]
        kind = _parse_operation_kind(
            operation_line
        )

        if kind is None:
            raise DeterministicEditError(
                "REVISION_PARSE_ERROR",
                (
                    "expected REVISE_EDIT, "
                    "REMOVE_EDIT, or ADD_EDIT "
                    f"at line {index + 1}"
                ),
            )

        raw_selector = (
            operation_line
            .partition(":")[2]
            .strip()
        )
        index += 1

        if kind is RevisionOperationKind.ADD:
            if raw_selector:
                raise DeterministicEditError(
                    "REVISION_PARSE_ERROR",
                    (
                        "ADD_EDIT must not contain "
                        "an authored identifier"
                    ),
                )

            edit_block, index = (
                _read_edit_block(
                    lines,
                    index,
                    kind=kind,
                )
            )
            added_ref = (
                _embedded_edit_ref(
                    edit_block
                )
            )

            if added_ref in added_refs:
                raise DeterministicEditError(
                    "REVISION_DUPLICATE_TARGET",
                    (
                        "same generated EditRef "
                        "added more than once: "
                        f"{added_ref}"
                    ),
                )

            added_refs.add(
                added_ref
            )
            operations.append(
                RevisionOperation(
                    kind=kind,
                    edit_ref=added_ref,
                    edit_block=edit_block,
                    replacement_edit_ref=(
                        added_ref
                    ),
                )
            )
            continue

        selector = _require_edit_ref(
            raw_selector,
            kind=kind,
        )

        if selector in targeted_refs:
            raise DeterministicEditError(
                "REVISION_DUPLICATE_TARGET",
                (
                    "same EditRef targeted "
                    f"more than once: {selector}"
                ),
            )

        targeted_refs.add(
            selector
        )

        if (
            kind
            is RevisionOperationKind.REMOVE
        ):
            operations.append(
                RevisionOperation(
                    kind=kind,
                    edit_ref=selector,
                    edit_block=None,
                )
            )
            continue

        edit_block, index = (
            _read_edit_block(
                lines,
                index,
                kind=kind,
            )
        )
        replacement_ref = (
            _embedded_edit_ref(
                edit_block
            )
        )
        operations.append(
            RevisionOperation(
                kind=kind,
                edit_ref=selector,
                edit_block=edit_block,
                replacement_edit_ref=(
                    replacement_ref
                ),
            )
        )

    if not operations:
        raise DeterministicEditError(
            "REVISION_PARSE_ERROR",
            (
                "revision specification must "
                "contain at least one operation"
            ),
        )

    return RevisionSpecification(
        operations=tuple(
            operations
        ),
    )


def _read_edit_block(
    lines: list[str],
    index: int,
    *,
    kind: RevisionOperationKind,
) -> tuple[str, int]:
    index = _skip_blank_lines(
        lines,
        index,
    )

    if (
        index >= len(lines)
        or lines[index]
        != "<<<<<<< EDIT"
    ):
        raise DeterministicEditError(
            "REVISION_PARSE_ERROR",
            (
                f"{kind.value} must contain "
                "<<<<<<< EDIT"
            ),
        )

    index += 1
    block_lines: list[str] = []

    while (
        index < len(lines)
        and lines[index]
        != ">>>>>>> EDIT"
    ):
        block_lines.append(
            decode_structural_payload_line(
                lines[index],
                markers=(
                    REVISION_EDIT_PAYLOAD_MARKERS
                ),
            )
        )
        index += 1

    if index >= len(lines):
        raise DeterministicEditError(
            "REVISION_PARSE_ERROR",
            (
                f"{kind.value} is missing "
                ">>>>>>> EDIT"
            ),
        )

    edit_block = "\n".join(
        block_lines
    )

    if not edit_block.strip():
        raise DeterministicEditError(
            "REVISION_PARSE_ERROR",
            (
                f"{kind.value} contains "
                "an empty EDIT block"
            ),
        )

    return edit_block, index + 1


def _embedded_edit_ref(
    edit_block: str,
) -> str:
    try:
        specification = (
            parse_edit_specification(
                edit_block
            )
        )
    except DeterministicEditError as exc:
        raise DeterministicEditError(
            "REVISION_PARSE_ERROR",
            (
                "embedded EDIT block "
                f"is invalid: {exc}"
            ),
        ) from exc

    if len(
        specification.edits
    ) != 1:
        raise DeterministicEditError(
            "REVISION_PARSE_ERROR",
            (
                "embedded EDIT block "
                "must contain exactly one edit"
            ),
        )

    return (
        specification
        .edits[0]
        .edit_ref
    )


def _require_edit_ref(
    value: str,
    *,
    kind: RevisionOperationKind,
) -> str:
    if not value:
        raise DeterministicEditError(
            "REVISION_PARSE_ERROR",
            (
                f"{kind.value} requires "
                "an EditRef selector"
            ),
        )

    if not is_generated_edit_ref(
        value
    ):
        raise DeterministicEditError(
            "REVISION_PARSE_ERROR",
            (
                f"{kind.value} selector must "
                "be a generated EditRef"
            ),
        )

    return value


def revise_edit_specification(
    base_text: str,
    revision_text: str,
) -> RevisionResult:
    try:
        base_specification = (
            parse_edit_specification(
                base_text
            )
        )
    except DeterministicEditError as exc:
        raise DeterministicEditError(
            "REVISION_PARSE_ERROR",
            (
                "base Edit Specification "
                f"is invalid: {exc}"
            ),
        ) from exc

    revision = (
        parse_revision_specification(
            revision_text
        )
    )

    ordered_base_refs = tuple(
        edit.edit_ref
        for edit in base_specification.edits
    )

    base_blocks = _locate_base_edit_blocks(
        base_text,
        edit_refs=ordered_base_refs,
    )

    base_refs = set(
        ordered_base_refs
    )

    if {
        block.edit_ref
        for block in base_blocks
    } != base_refs:
        raise DeterministicEditError(
            "REVISION_PARSE_ERROR",
            (
                "base Edit Specification "
                "block identity scan disagrees "
                "with parsed EditRef identities"
            ),
        )

    operations_by_ref = {
        operation.edit_ref: operation
        for operation in revision.operations
    }

    for operation in revision.operations:
        if (
            operation.kind
            in {
                RevisionOperationKind.REVISE,
                RevisionOperationKind.REMOVE,
            }
            and operation.edit_ref not in base_refs
        ):
            raise DeterministicEditError(
                "REVISION_EDIT_NOT_FOUND",
                (
                    "base Edit Specification "
                    "does not contain EditRef "
                    f"{operation.edit_ref!r}"
                ),
            )

        if (
            operation.kind
            is RevisionOperationKind.ADD
            and operation.edit_ref in base_refs
        ):
            raise DeterministicEditError(
                "REVISION_EDIT_ALREADY_EXISTS",
                (
                    "base Edit Specification "
                    "already contains EditRef "
                    f"{operation.edit_ref!r}"
                ),
            )

    newline = _preferred_newline(
        base_text
    )
    parts: list[str] = []
    cursor = 0

    for block in base_blocks:
        parts.append(
            base_text[
                cursor:block.start_offset
            ]
        )

        operation = operations_by_ref.get(
            block.edit_ref
        )

        if operation is None:
            parts.append(
                base_text[
                    block.start_offset:
                    block.end_offset
                ]
            )
        elif (
            operation.kind
            is RevisionOperationKind.REVISE
        ):
            assert operation.edit_block is not None
            parts.append(
                _render_replacement_block(
                    operation.edit_block,
                    newline=newline,
                    ends_with_newline=(
                        block.ends_with_newline
                    ),
                )
            )
        elif (
            operation.kind
            is RevisionOperationKind.REMOVE
        ):
            pass
        else:
            parts.append(
                base_text[
                    block.start_offset:
                    block.end_offset
                ]
            )

        cursor = block.end_offset

    parts.append(
        base_text[cursor:]
    )
    revised_text = "".join(
        parts
    )

    additions = sorted(
        (
            operation
            for operation in revision.operations
            if (
                operation.kind
                is RevisionOperationKind.ADD
            )
        ),
        key=lambda operation: operation.edit_ref,
    )

    if additions:
        revised_text = _append_added_blocks(
            revised_text,
            additions,
            newline=newline,
        )

    try:
        parse_edit_specification(
            revised_text
        )
    except DeterministicEditError as exc:
        raise DeterministicEditError(
            "REVISION_PARSE_ERROR",
            (
                "revised Edit Specification "
                f"is invalid: {exc}"
            ),
        ) from exc

    mappings: list[
        tuple[str, str]
    ] = []

    for operation in revision.operations:
        if (
            operation.kind
            is not RevisionOperationKind.REVISE
        ):
            continue

        if (
            operation.replacement_edit_ref
            is None
        ):
            raise DeterministicEditError(
                "REVISION_PARSE_ERROR",
                (
                    "REVISE_EDIT is missing "
                    "its replacement EditRef"
                ),
            )

        mappings.append(
            (
                operation.edit_ref,
                operation.replacement_edit_ref,
            )
        )

    revised_edit_ref_mappings = tuple(
        sorted(
            mappings
        )
    )

    revised_refs = tuple(
        sorted(
            operation.edit_ref
            for operation in revision.operations
            if (
                operation.kind
                is RevisionOperationKind.REVISE
            )
        )
    )
    removed_refs = tuple(
        sorted(
            operation.edit_ref
            for operation in revision.operations
            if (
                operation.kind
                is RevisionOperationKind.REMOVE
            )
        )
    )
    added_refs = tuple(
        sorted(
            operation.edit_ref
            for operation in revision.operations
            if (
                operation.kind
                is RevisionOperationKind.ADD
            )
        )
    )

    return RevisionResult(
        revised_text=revised_text,
        base_fingerprint=_text_fingerprint(
            base_text
        ),
        revised_fingerprint=_text_fingerprint(
            revised_text
        ),
        revised_edit_refs=revised_refs,
        removed_edit_refs=removed_refs,
        added_edit_refs=added_refs,
        revised_edit_ref_mappings=(
            revised_edit_ref_mappings
        ),
    )


def _parse_operation_kind(
    line: str,
) -> RevisionOperationKind | None:
    for kind in RevisionOperationKind:
        if line.startswith(
            f"{kind.value}:"
        ):
            return kind

    return None


def _locate_base_edit_blocks(
    text: str,
    *,
    edit_refs: tuple[str, ...],
) -> tuple[_BaseEditBlock, ...]:
    raw_lines = text.splitlines(
        keepends=True
    )
    logical_lines = [
        _logical_line(
            line
        )
        for line in raw_lines
    ]

    offsets = [0]

    for line in raw_lines:
        offsets.append(
            offsets[-1]
            + len(line)
        )

    index = _skip_blank_lines(
        logical_lines,
        0,
    )

    blocks: list[_BaseEditBlock] = []
    block_position = 0

    while True:
        index = _skip_blank_lines(
            logical_lines,
            index,
        )

        if index >= len(logical_lines):
            break

        start_line = index

        if not logical_lines[index].startswith(
            "FILE:"
        ):
            raise DeterministicEditError(
                "REVISION_PARSE_ERROR",
                (
                    "could not locate base "
                    f"FILE block at line {index + 1}"
                ),
            )

        index += 1
        index = _skip_blank_lines(
            logical_lines,
            index,
        )

        if block_position >= len(
            edit_refs
        ):
            raise DeterministicEditError(
                "REVISION_PARSE_ERROR",
                (
                    "base Edit Specification "
                    "contains more raw edit blocks "
                    "than parsed edits"
                ),
            )

        edit_ref = edit_refs[
            block_position
        ]

        if (
            index < len(logical_lines)
            and logical_lines[
                index
            ].startswith(
                "LABEL:"
            )
        ):
            index += 1
            index = _skip_blank_lines(
                logical_lines,
                index,
            )

        if index >= len(logical_lines):
            raise DeterministicEditError(
                "REVISION_PARSE_ERROR",
                (
                    f"EDIT {edit_ref!r} "
                    "has no edit body"
                ),
            )

        if (
            logical_lines[index]
            == "<<<<<<< SEARCH"
        ):
            end_line = (
                _locate_search_replace_end(
                    logical_lines,
                    index,
                    edit_ref=edit_ref,
                )
            )
        elif logical_lines[index].startswith(
            "MODE:"
        ):
            end_line = (
                _locate_whole_file_end(
                    logical_lines,
                    index,
                    edit_ref=edit_ref,
                )
            )
        else:
            raise DeterministicEditError(
                "REVISION_PARSE_ERROR",
                (
                    f"EDIT {edit_ref!r} "
                    "has neither SEARCH nor MODE body"
                ),
            )

        raw_closing_line = raw_lines[
            end_line - 1
        ]

        blocks.append(
            _BaseEditBlock(
                edit_ref=edit_ref,
                start_offset=offsets[
                    start_line
                ],
                end_offset=offsets[
                    end_line
                ],
                ends_with_newline=(
                    raw_closing_line.endswith(
                        "\n"
                    )
                ),
            )
        )

        index = end_line
        block_position += 1

    if (
        block_position
        != len(edit_refs)
    ):
        raise DeterministicEditError(
            "REVISION_PARSE_ERROR",
            (
                "base Edit Specification "
                "raw block count disagrees "
                "with parsed edit count"
            ),
        )

    return tuple(
        blocks
    )


def _locate_search_replace_end(
    logical_lines: list[str],
    opening_index: int,
    *,
    edit_ref: str,
) -> int:
    index = opening_index + 1

    while (
        index < len(logical_lines)
        and logical_lines[index]
        != "======="
    ):
        if (
            logical_lines[index]
            == ">>>>>>> REPLACE"
        ):
            raise DeterministicEditError(
                "REVISION_PARSE_ERROR",
                (
                    f"EDIT {edit_ref!r} "
                    "has no SEARCH separator"
                ),
            )

        index += 1

    if index >= len(logical_lines):
        raise DeterministicEditError(
            "REVISION_PARSE_ERROR",
            (
                f"EDIT {edit_ref!r} "
                "has no SEARCH separator"
            ),
        )

    index += 1

    while (
        index < len(logical_lines)
        and logical_lines[index]
        != ">>>>>>> REPLACE"
    ):
        index += 1

    if index >= len(logical_lines):
        raise DeterministicEditError(
            "REVISION_PARSE_ERROR",
            (
                f"EDIT {edit_ref!r} "
                "has no REPLACE closing marker"
            ),
        )

    return index + 1


def _locate_whole_file_end(
    logical_lines: list[str],
    mode_index: int,
    *,
    edit_ref: str,
) -> int:
    mode = (
        logical_lines[mode_index]
        .partition(":")[2]
        .strip()
    )

    if mode == "DELETE":
        return mode_index + 1

    if mode not in {
        "CREATE",
        "REPLACE_FILE",
    }:
        raise DeterministicEditError(
            "REVISION_PARSE_ERROR",
            (
                f"EDIT {edit_ref!r} "
                f"has unsupported MODE: {mode}"
            ),
        )

    index = mode_index + 1

    while True:
        index = _skip_blank_lines(
            logical_lines,
            index,
        )

        if index >= len(logical_lines):
            raise DeterministicEditError(
                "REVISION_PARSE_ERROR",
                (
                    f"EDIT {edit_ref!r} "
                    "has no CONTENT opening marker"
                ),
            )

        line = logical_lines[index]

        if line == "<<<<<<< CONTENT":
            break

        if (
            line.startswith("NEWLINE:")
            or line.startswith(
                "FINAL_NEWLINE:"
            )
            or line.startswith("BOM:")
        ):
            index += 1
            continue

        raise DeterministicEditError(
            "REVISION_PARSE_ERROR",
            (
                f"EDIT {edit_ref!r} "
                "has invalid whole-file body"
            ),
        )

    index += 1

    while (
        index < len(logical_lines)
        and logical_lines[index]
        != ">>>>>>> CONTENT"
    ):
        index += 1

    if index >= len(logical_lines):
        raise DeterministicEditError(
            "REVISION_PARSE_ERROR",
            (
                f"EDIT {edit_ref!r} "
                "has no CONTENT closing marker"
            ),
        )

    return index + 1


def _append_added_blocks(
    base_text: str,
    additions: list[RevisionOperation],
    *,
    newline: str,
) -> str:
    result = base_text

    if (
        result
        and not result.endswith(
            ("\n", "\r")
        )
    ):
        result += newline

    if (
        result
        and not result.endswith(
            newline + newline
        )
    ):
        result += newline

    for position, operation in enumerate(
        additions
    ):
        assert operation.edit_block is not None

        rendered = (
            operation.edit_block
            .replace(
                "\n",
                newline,
            )
        )

        if not rendered.endswith(
            newline
        ):
            rendered += newline

        result += rendered

        if (
            position
            < len(additions) - 1
        ):
            result += newline

    return result


def _render_replacement_block(
    edit_block: str,
    *,
    newline: str,
    ends_with_newline: bool,
) -> str:
    rendered = edit_block.replace(
        "\n",
        newline,
    )

    if (
        ends_with_newline
        and not rendered.endswith(
            newline
        )
    ):
        rendered += newline

    if (
        not ends_with_newline
        and rendered.endswith(
            newline
        )
    ):
        rendered = rendered[
            : -len(newline)
        ]

    return rendered


def _preferred_newline(
    text: str,
) -> str:
    has_crlf = "\r\n" in text
    without_crlf = text.replace(
        "\r\n",
        "",
    )

    if (
        has_crlf
        and "\n" not in without_crlf
    ):
        return "\r\n"

    return "\n"


def _split_revision_lines(
    text: str,
) -> list[str]:
    normalized = text.replace(
        "\r\n",
        "\n",
    )

    if "\r" in normalized:
        raise DeterministicEditError(
            "REVISION_PARSE_ERROR",
            (
                "revision specification "
                "contains unsupported lone CR"
            ),
        )

    return normalized.splitlines()


def _logical_line(
    raw_line: str,
) -> str:
    if raw_line.endswith(
        "\r\n"
    ):
        return raw_line[:-2]

    if raw_line.endswith(
        "\n"
    ):
        return raw_line[:-1]

    if raw_line.endswith(
        "\r"
    ):
        raise DeterministicEditError(
            "REVISION_PARSE_ERROR",
            (
                "base Edit Specification "
                "contains unsupported lone CR"
            ),
        )

    return raw_line


def _skip_blank_lines(
    lines: list[str],
    index: int,
) -> int:
    while (
        index < len(lines)
        and lines[index] == ""
    ):
        index += 1

    return index


def _text_fingerprint(
    text: str,
) -> str:
    return hashlib.sha256(
        text.encode(
            "utf-8"
        )
    ).hexdigest()
