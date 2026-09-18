from __future__ import annotations

from ep_edit.edit_ref import (
    is_generated_edit_ref,
)
from ep_edit.errors import DeterministicEditError
from ep_edit.revision import (
    REVISION_SPEC_VERSION_V2,
    RevisionOperation,
    RevisionOperationKind,
    RevisionSpecification,
    _parse_operation_kind,
    _skip_blank_lines,
    _split_revision_lines,
)
from ep_edit.specification import (
    parse_edit_specification,
)
from ep_edit.structural_escape import (
    REVISION_EDIT_PAYLOAD_MARKERS,
    decode_structural_payload_line,
)


def parse_v2_revision_specification(
    text: str,
) -> RevisionSpecification:
    lines = _split_revision_lines(
        text
    )
    index = _skip_blank_lines(
        lines,
        0,
    )

    if (
        index >= len(lines)
        or lines[index]
        != "REVISION_SPEC_VERSION: 2"
    ):
        raise DeterministicEditError(
            "REVISION_PARSE_ERROR",
            (
                "Revision Specification v2 "
                "requires "
                "REVISION_SPEC_VERSION: 2"
            ),
        )

    index += 1

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
                        "ADD_EDIT in Revision "
                        "Specification v2 must not "
                        "contain an authored identifier"
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
                _embedded_v2_edit_ref(
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
                    edit_id=added_ref,
                    edit_block=edit_block,
                    replacement_edit_id=(
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
                    edit_id=selector,
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
            _embedded_v2_edit_ref(
                edit_block
            )
        )

        operations.append(
            RevisionOperation(
                kind=kind,
                edit_id=selector,
                edit_block=edit_block,
                replacement_edit_id=(
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
        version=REVISION_SPEC_VERSION_V2,
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
                markers=REVISION_EDIT_PAYLOAD_MARKERS,
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


def _embedded_v2_edit_ref(
    edit_block: str,
) -> str:
    embedded = (
        "EDIT_SPEC_VERSION: 2\n\n"
        + edit_block
    )

    try:
        specification = (
            parse_edit_specification(
                embedded
            )
        )
    except DeterministicEditError as exc:
        raise DeterministicEditError(
            "REVISION_PARSE_ERROR",
            (
                "embedded v2 EDIT block "
                f"is invalid: {exc}"
            ),
        ) from exc

    if len(
        specification.edits
    ) != 1:
        raise DeterministicEditError(
            "REVISION_PARSE_ERROR",
            (
                "embedded v2 EDIT block "
                "must contain exactly one edit"
            ),
        )

    return (
        specification
        .edits[0]
        .edit_id
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
