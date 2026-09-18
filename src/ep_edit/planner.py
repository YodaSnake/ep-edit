from __future__ import annotations

import codecs
import difflib
import hashlib
import stat
from dataclasses import dataclass
from enum import Enum
from pathlib import Path, PurePosixPath

from ep_edit.errors import (
    DeterministicEditError,
    EditDiagnostic,
    EditPreflightError,
    RepairCandidate,
    RepairMetadata,
)
from ep_edit.snapshot import NewlineStyle, TextSnapshot, load_text_snapshot
from ep_edit.specification import (
    BomDirective,
    EditOperation,
    EditSpecification,
    FinalNewlineDirective,
    NewlineDirective,
    SearchReplaceEdit,
    WholeFileEdit,
    WholeFileMode,
    normalize_target_path,
    parse_edit_specification,
)


class FileMutationOperation(str, Enum):
    CREATE = "CREATE"
    REPLACE = "REPLACE"
    DELETE = "DELETE"


@dataclass(frozen=True)
class ChangedRange:
    edit_ref: str
    start_line_index: int
    end_line_index: int
    replacement_line_count: int


@dataclass(frozen=True)
class PlanWarning:
    code: str
    edit_ref: str
    target: str
    message: str


@dataclass(frozen=True)
class CreateParentIdentity:
    relative_path: str
    device: int
    inode: int


@dataclass(frozen=True)
class FileMutation:
    target: str
    operation: FileMutationOperation
    before_exists: bool
    before_sha256: str | None
    before_bytes: bytes | None
    after_exists: bool
    after_sha256: str | None
    after_bytes: bytes | None
    newline_style: NewlineStyle | None
    final_newline: bool
    edit_refs: tuple[str, ...]
    changed_ranges: tuple[ChangedRange, ...]
    create_parent_directories: tuple[str, ...] = ()
    create_existing_parent_identities: tuple[
        CreateParentIdentity,
        ...,
    ] = ()


@dataclass(frozen=True)
class EditPlan:
    root: Path
    input_fingerprint: str
    files: tuple[FileMutation, ...]
    warnings: tuple[PlanWarning, ...] = ()
    root_device: int | None = None
    root_inode: int | None = None


@dataclass(frozen=True)
class _ResolvedEdit:
    edit: SearchReplaceEdit
    start_line_index: int
    end_line_index: int


def _diagnostic_for_edit(
    edit: EditOperation,
    error: DeterministicEditError,
) -> EditDiagnostic:
    return EditDiagnostic(
        code=error.code,
        edit_ref=edit.edit_ref,
        target=edit.target,
        message=error.message,
        label=edit.label,
        repair_metadata=(
            error.repair_metadata
        ),
    )


def plan_edit_text(
    root: Path,
    text: str,
) -> EditPlan:
    specification = parse_edit_specification(text)

    return plan_edit_specification(
        root,
        specification,
        input_fingerprint=hashlib.sha256(
            text.encode("utf-8")
        ).hexdigest(),
    )


def plan_edit_specification(
    root: Path,
    specification: EditSpecification,
    *,
    input_fingerprint: str,
) -> EditPlan:
    resolved_root = _resolve_root(root)

    try:
        resolved_root_stat = (
            resolved_root.lstat()
        )
    except OSError as exc:
        raise DeterministicEditError(
            "TARGET_INVALID_PATH",
            "root state cannot be captured safely",
        ) from exc

    if not stat.S_ISDIR(
        resolved_root_stat.st_mode
    ):
        raise DeterministicEditError(
            "TARGET_INVALID_PATH",
            "resolved root is no longer a directory",
        )

    edits_by_target: dict[str, list[EditOperation]] = {}

    for edit in specification.edits:
        edits_by_target.setdefault(edit.target, []).append(edit)

    mutations: list[FileMutation] = []
    warnings: list[PlanWarning] = []
    diagnostics: list[EditDiagnostic] = []

    for target in sorted(edits_by_target):
        target_edits = edits_by_target[target]

        if (
            len(target_edits) == 1
            and isinstance(
                target_edits[0],
                WholeFileEdit,
            )
        ):
            try:
                mutation, target_warnings = (
                    _plan_whole_file_edit(
                        resolved_root,
                        target_edits[0],
                    )
                )
            except DeterministicEditError as exc:
                diagnostics.append(
                    _diagnostic_for_edit(
                        target_edits[0],
                        exc,
                    )
                )
                continue

        else:
            if not all(
                isinstance(edit, SearchReplaceEdit)
                for edit in target_edits
            ):
                raise DeterministicEditError(
                    "INPUT_PARSE_ERROR",
                    (
                        "whole-file operation must be the sole edit "
                        f"for target {target!r}"
                    ),
                )

            search_edits = [
                edit
                for edit in target_edits
                if isinstance(edit, SearchReplaceEdit)
            ]

            try:
                snapshot = load_text_snapshot(
                    resolved_root,
                    target,
                )
            except DeterministicEditError as exc:
                diagnostics.extend(
                    _diagnostic_for_edit(
                        edit,
                        exc,
                    )
                    for edit in search_edits
                )
                continue

            try:
                mutation, target_warnings = (
                    _plan_target(
                        snapshot,
                        search_edits,
                    )
                )
            except EditPreflightError as exc:
                diagnostics.extend(
                    exc.diagnostics
                )
                continue

        warnings.extend(target_warnings)

        if mutation is not None:
            mutations.append(mutation)

    if diagnostics:
        raise EditPreflightError(
            tuple(
                diagnostics
            )
        )

    if not mutations:
        raise DeterministicEditError(
            "NO_CHANGE",
            "all edits produce byte-identical target state",
        )

    return EditPlan(
        root=resolved_root,
        input_fingerprint=input_fingerprint,
        files=tuple(mutations),
        root_device=resolved_root_stat.st_dev,
        root_inode=resolved_root_stat.st_ino,
        warnings=tuple(
            sorted(
                warnings,
                key=lambda warning: (
                    warning.target,
                    warning.edit_ref,
                    warning.code,
                ),
            )
        ),
    )


def _plan_whole_file_edit(
    root: Path,
    edit: WholeFileEdit,
) -> tuple[FileMutation | None, list[PlanWarning]]:
    if edit.mode is WholeFileMode.CREATE:
        (
            create_parent_directories,
            create_existing_parent_identities,
        ) = _plan_create_parent_directories(
            root,
            edit.target,
        )
        after_bytes, newline_style, final_newline = (
            _materialize_whole_file_bytes(
                edit,
                snapshot=None,
            )
        )

        return (
            FileMutation(
                target=edit.target,
                operation=FileMutationOperation.CREATE,
                before_exists=False,
                before_sha256=None,
                before_bytes=None,
                after_exists=True,
                after_sha256=hashlib.sha256(
                    after_bytes
                ).hexdigest(),
                after_bytes=after_bytes,
                newline_style=newline_style,
                final_newline=final_newline,
                edit_refs=(edit.edit_ref,),
                changed_ranges=(),
                create_parent_directories=(
                    create_parent_directories
                ),
                create_existing_parent_identities=(
                    create_existing_parent_identities
                ),
            ),
            [],
        )

    snapshot = load_text_snapshot(
        root,
        edit.target,
    )

    if edit.mode is WholeFileMode.DELETE:
        return (
            FileMutation(
                target=snapshot.target,
                operation=FileMutationOperation.DELETE,
                before_exists=True,
                before_sha256=snapshot.sha256,
                before_bytes=snapshot.raw_bytes,
                after_exists=False,
                after_sha256=None,
                after_bytes=None,
                newline_style=snapshot.newline_style,
                final_newline=snapshot.has_final_newline,
                edit_refs=(edit.edit_ref,),
                changed_ranges=(),
            ),
            [],
        )

    after_bytes, newline_style, final_newline = (
        _materialize_whole_file_bytes(
            edit,
            snapshot=snapshot,
        )
    )

    if after_bytes == snapshot.raw_bytes:
        return (
            None,
            [
                PlanWarning(
                    code="NO_CHANGE_EDIT",
                    edit_ref=edit.edit_ref,
                    target=edit.target,
                    message=(
                        "REPLACE_FILE candidate is byte-identical; "
                        "edit omitted from mutation plan"
                    ),
                )
            ],
        )

    return (
        FileMutation(
            target=snapshot.target,
            operation=FileMutationOperation.REPLACE,
            before_exists=True,
            before_sha256=snapshot.sha256,
            before_bytes=snapshot.raw_bytes,
            after_exists=True,
            after_sha256=hashlib.sha256(
                after_bytes
            ).hexdigest(),
            after_bytes=after_bytes,
            newline_style=newline_style,
            final_newline=final_newline,
            edit_refs=(edit.edit_ref,),
            changed_ranges=(),
        ),
        [],
    )


def _plan_create_parent_directories(
    root: Path,
    target: str,
) -> tuple[
    tuple[str, ...],
    tuple[CreateParentIdentity, ...],
]:
    canonical_target = normalize_target_path(
        target
    )
    relative = PurePosixPath(
        canonical_target
    )
    current = root
    missing_directories: list[str] = []
    existing_parent_identities: list[
        CreateParentIdentity
    ] = []

    for depth, part in enumerate(
        relative.parts[:-1],
        start=1,
    ):
        current = current / part
        current_relative = PurePosixPath(
            *relative.parts[:depth]
        ).as_posix()

        if missing_directories:
            missing_directories.append(
                current_relative
            )
            continue

        try:
            item_stat = current.lstat()
        except FileNotFoundError:
            missing_directories.append(
                current_relative
            )
            continue

        if stat.S_ISLNK(
            item_stat.st_mode
        ):
            raise DeterministicEditError(
                "TARGET_SYMLINK",
                (
                    "symbolic links are not allowed in target path: "
                    f"{canonical_target}"
                ),
            )

        if not stat.S_ISDIR(
            item_stat.st_mode
        ):
            raise DeterministicEditError(
                "TARGET_INVALID_PATH",
                (
                    "CREATE parent component is not a directory for target: "
                    f"{canonical_target}"
                ),
            )

        existing_parent_identities.append(
            CreateParentIdentity(
                relative_path=current_relative,
                device=item_stat.st_dev,
                inode=item_stat.st_ino,
            )
        )

    if missing_directories:
        return (
            tuple(
                missing_directories
            ),
            tuple(
                existing_parent_identities
            ),
        )

    target_path = current / relative.parts[-1]

    try:
        target_stat = target_path.lstat()
    except FileNotFoundError:
        return (
            (),
            tuple(
                existing_parent_identities
            ),
        )

    if stat.S_ISLNK(
        target_stat.st_mode
    ):
        raise DeterministicEditError(
            "TARGET_SYMLINK",
            f"CREATE target is a symbolic link: {canonical_target}",
        )

    raise DeterministicEditError(
        "TARGET_ALREADY_EXISTS",
        f"CREATE target already exists: {canonical_target}",
    )


def _materialize_whole_file_bytes(
    edit: WholeFileEdit,
    *,
    snapshot: TextSnapshot | None,
) -> tuple[bytes, NewlineStyle | None, bool]:
    if edit.content_lines is None:
        raise RuntimeError(
            "whole-file content is unavailable"
        )

    newline_style = _resolve_whole_file_newline_style(
        edit,
        snapshot=snapshot,
    )
    final_newline = _resolve_whole_file_final_newline(
        edit,
        snapshot=snapshot,
    )
    has_bom = _resolve_whole_file_bom(
        edit,
        snapshot=snapshot,
    )

    needs_separator = (
        len(edit.content_lines) > 1
        or final_newline
    )

    if newline_style is NewlineStyle.CRLF:
        separator = "\r\n"
    elif newline_style is NewlineStyle.LF:
        separator = "\n"
    else:
        separator = None

    if needs_separator and separator is None:
        raise DeterministicEditError(
            "UNSUPPORTED_NEWLINE",
            (
                f"EDIT {edit.edit_ref!r} requests PRESERVE newline "
                "semantics from a file with no established newline "
                "style, but the candidate requires a line separator"
            ),
        )

    if separator is None:
        if not edit.content_lines:
            body = ""
        else:
            body = edit.content_lines[0]
    else:
        body = separator.join(
            edit.content_lines
        )

        if final_newline:
            body += separator

    encoded = body.encode("utf-8")

    if has_bom:
        encoded = codecs.BOM_UTF8 + encoded

    actual_newline_style = (
        newline_style
        if needs_separator
        else None
    )

    return (
        encoded,
        actual_newline_style,
        final_newline,
    )


def _resolve_whole_file_newline_style(
    edit: WholeFileEdit,
    *,
    snapshot: TextSnapshot | None,
) -> NewlineStyle | None:
    if edit.newline is NewlineDirective.LF:
        return NewlineStyle.LF

    if edit.newline is NewlineDirective.CRLF:
        return NewlineStyle.CRLF

    if edit.newline is NewlineDirective.PRESERVE:
        if snapshot is None:
            raise RuntimeError(
                "CREATE cannot preserve newline state"
            )

        return snapshot.newline_style

    raise RuntimeError(
        "whole-file newline directive is unavailable"
    )


def _resolve_whole_file_final_newline(
    edit: WholeFileEdit,
    *,
    snapshot: TextSnapshot | None,
) -> bool:
    if edit.final_newline is FinalNewlineDirective.YES:
        return True

    if edit.final_newline is FinalNewlineDirective.NO:
        return False

    if edit.final_newline is FinalNewlineDirective.PRESERVE:
        if snapshot is None:
            raise RuntimeError(
                "CREATE cannot preserve final newline state"
            )

        return snapshot.has_final_newline

    raise RuntimeError(
        "whole-file final-newline directive is unavailable"
    )


def _resolve_whole_file_bom(
    edit: WholeFileEdit,
    *,
    snapshot: TextSnapshot | None,
) -> bool:
    if edit.bom is BomDirective.YES:
        return True

    if edit.bom is BomDirective.NO:
        return False

    if edit.bom is BomDirective.PRESERVE:
        if snapshot is None:
            raise RuntimeError(
                "CREATE cannot preserve BOM state"
            )

        return snapshot.has_utf8_bom

    raise RuntimeError(
        "whole-file BOM directive is unavailable"
    )


def _resolve_root(root: Path) -> Path:
    try:
        resolved = root.expanduser().resolve(strict=True)
    except OSError as exc:
        raise DeterministicEditError(
            "TARGET_INVALID_PATH",
            "root does not exist",
        ) from exc

    if not resolved.is_dir():
        raise DeterministicEditError(
            "TARGET_INVALID_PATH",
            "root is not a directory",
        )

    return resolved


def _plan_target(
    snapshot: TextSnapshot,
    edits: list[SearchReplaceEdit],
) -> tuple[FileMutation | None, list[PlanWarning]]:
    original_lines = _snapshot_logical_lines(snapshot)
    resolved_edits: list[
        _ResolvedEdit
    ] = []
    diagnostics: list[
        EditDiagnostic
    ] = []

    for edit in edits:
        try:
            resolved_edits.append(
                _resolve_edit(
                    original_lines,
                    edit,
                )
            )
        except DeterministicEditError as exc:
            diagnostics.append(
                _diagnostic_for_edit(
                    edit,
                    exc,
                )
            )

    if diagnostics:
        raise EditPreflightError(
            tuple(
                diagnostics
            )
        )

    changed: list[_ResolvedEdit] = []
    warnings: list[PlanWarning] = []

    for resolved in resolved_edits:
        if (
            resolved.edit.search_lines
            == resolved.edit.replace_lines
        ):
            warnings.append(
                PlanWarning(
                    code="NO_CHANGE_EDIT",
                    edit_ref=resolved.edit.edit_ref,
                    target=resolved.edit.target,
                    message=(
                        "SEARCH and REPLACE are identical; "
                        "edit omitted from mutation plan"
                    ),
                )
            )
            continue

        changed.append(resolved)

    if not changed:
        return None, warnings

    _require_non_overlapping(changed)

    updated_lines = list(original_lines)

    for resolved in sorted(
        changed,
        key=lambda item: item.start_line_index,
        reverse=True,
    ):
        updated_lines[
            resolved.start_line_index:
            resolved.end_line_index
        ] = resolved.edit.replace_lines

    after_bytes = _encode_partial_result(
        snapshot,
        updated_lines,
    )
    after_sha256 = hashlib.sha256(after_bytes).hexdigest()

    if after_bytes == snapshot.raw_bytes:
        return None, warnings

    ordered_ranges = tuple(
        ChangedRange(
            edit_ref=resolved.edit.edit_ref,
            start_line_index=resolved.start_line_index,
            end_line_index=resolved.end_line_index,
            replacement_line_count=len(
                resolved.edit.replace_lines
            ),
        )
        for resolved in sorted(
            changed,
            key=lambda item: (
                item.start_line_index,
                item.end_line_index,
                item.edit.edit_ref,
            ),
        )
    )

    return (
        FileMutation(
            target=snapshot.target,
            operation=FileMutationOperation.REPLACE,
            before_exists=True,
            before_sha256=snapshot.sha256,
            before_bytes=snapshot.raw_bytes,
            after_exists=True,
            after_sha256=after_sha256,
            after_bytes=after_bytes,
            newline_style=snapshot.newline_style,
            final_newline=snapshot.has_final_newline,
            edit_refs=tuple(
                changed_range.edit_ref
                for changed_range in ordered_ranges
            ),
            changed_ranges=ordered_ranges,
        ),
        warnings,
    )


def _resolve_edit(
    original_lines: tuple[str, ...],
    edit: SearchReplaceEdit,
) -> _ResolvedEdit:
    matches = _find_exact_matches(
        original_lines,
        edit.search_lines,
    )

    if not matches:
        raise DeterministicEditError(
            "SEARCH_ZERO_MATCH",
            (
                f"EDIT {edit.edit_ref!r} has no exact "
                f"logical-line match in {edit.target!r}"
            ),
            repair_metadata=(
                _zero_match_repair_metadata(
                    original_lines,
                    edit.search_lines,
                )
            ),
        )

    if len(matches) > 1:
        raise DeterministicEditError(
            "SEARCH_MULTIPLE_MATCH",
            (
                f"EDIT {edit.edit_ref!r} has "
                f"{len(matches)} exact logical-line matches "
                f"in {edit.target!r}"
            ),
            repair_metadata=(
                _multiple_match_repair_metadata(
                    matches,
                    search_length=len(
                        edit.search_lines
                    ),
                )
            ),
        )

    start = matches[0]

    return _ResolvedEdit(
        edit=edit,
        start_line_index=start,
        end_line_index=start + len(edit.search_lines),
    )


def _find_exact_matches(
    original_lines: tuple[str, ...],
    search_lines: tuple[str, ...],
) -> tuple[int, ...]:
    search_length = len(search_lines)

    if search_length == 0:
        return ()

    if search_length > len(original_lines):
        return ()

    matches: list[int] = []

    for start in range(
        len(original_lines) - search_length + 1
    ):
        if (
            original_lines[
                start:start + search_length
            ]
            == search_lines
        ):
            matches.append(start)

    return tuple(matches)


_REPAIR_GUIDANCE = (
    "Use the smallest exact SEARCH block that is unique "
    "in the declared target."
)
_REPAIR_MAX_CANDIDATES = 3
_REPAIR_MAX_EXACT_RANGES = 20
_REPAIR_MAX_EXCERPT_LINES = 8
_REPAIR_MAX_EXCERPT_CHARS = 240


def _zero_match_repair_metadata(
    original_lines: tuple[str, ...],
    search_lines: tuple[str, ...],
) -> RepairMetadata:
    candidates = _find_similarity_candidates(
        original_lines,
        search_lines,
    )
    total_candidate_count = (
        _similarity_window_count(
            original_lines,
            search_lines,
        )
    )

    return RepairMetadata(
        kind="ZERO_MATCH_SIMILARITY",
        guidance=_REPAIR_GUIDANCE,
        candidates=candidates,
        total_candidate_count=(
            total_candidate_count
        ),
        candidates_truncated=(
            total_candidate_count
            > len(candidates)
        ),
    )


def _similarity_window_count(
    original_lines: tuple[str, ...],
    search_lines: tuple[str, ...],
) -> int:
    if (
        not original_lines
        or not search_lines
    ):
        return 0

    window_length = min(
        len(search_lines),
        len(original_lines),
    )

    return (
        len(original_lines)
        - window_length
        + 1
    )


def _multiple_match_repair_metadata(
    matches: tuple[int, ...],
    *,
    search_length: int,
) -> RepairMetadata:
    return RepairMetadata(
        kind="MULTIPLE_MATCH_EXACT_RANGES",
        guidance=_REPAIR_GUIDANCE,
        candidates=tuple(
            RepairCandidate(
                start_line=start + 1,
                end_line=start + search_length,
            )
            for start in matches[
                :_REPAIR_MAX_EXACT_RANGES
            ]
        ),
        total_candidate_count=len(
            matches
        ),
        candidates_truncated=(
            len(matches)
            > _REPAIR_MAX_EXACT_RANGES
        ),
    )


def _find_similarity_candidates(
    original_lines: tuple[str, ...],
    search_lines: tuple[str, ...],
) -> tuple[RepairCandidate, ...]:
    if (
        not original_lines
        or not search_lines
    ):
        return ()

    window_length = min(
        len(search_lines),
        len(original_lines),
    )
    expected = "\n".join(
        search_lines
    )

    ranked: list[
        tuple[
            float,
            int,
            tuple[str, ...],
        ]
    ] = []

    for start in range(
        len(original_lines)
        - window_length
        + 1
    ):
        candidate_lines = (
            original_lines[
                start:
                start + window_length
            ]
        )
        actual = "\n".join(
            candidate_lines
        )
        similarity = (
            difflib.SequenceMatcher(
                None,
                expected,
                actual,
                autojunk=False,
            ).ratio()
        )

        ranked.append(
            (
                similarity,
                start,
                candidate_lines,
            )
        )

    ranked.sort(
        key=lambda item: (
            -item[0],
            item[1],
        )
    )

    candidates: list[
        RepairCandidate
    ] = []

    for (
        similarity,
        start,
        candidate_lines,
    ) in ranked[
        :_REPAIR_MAX_CANDIDATES
    ]:
        (
            excerpt,
            excerpt_truncated,
        ) = _bounded_repair_excerpt(
            candidate_lines
        )

        candidates.append(
            RepairCandidate(
                start_line=start + 1,
                end_line=(
                    start
                    + len(candidate_lines)
                ),
                similarity_basis_points=int(
                    similarity * 10000
                    + 0.5
                ),
                excerpt=excerpt,
                excerpt_truncated=(
                    excerpt_truncated
                ),
            )
        )

    return tuple(
        candidates
    )


def _bounded_repair_excerpt(
    lines: tuple[str, ...],
) -> tuple[
    tuple[str, ...],
    bool,
]:
    truncated = (
        len(lines)
        > _REPAIR_MAX_EXCERPT_LINES
    )
    excerpt: list[str] = []

    for line in lines[
        :_REPAIR_MAX_EXCERPT_LINES
    ]:
        if (
            len(line)
            > _REPAIR_MAX_EXCERPT_CHARS
        ):
            excerpt.append(
                line[
                    :_REPAIR_MAX_EXCERPT_CHARS
                    - 3
                ]
                + "..."
            )
            truncated = True
        else:
            excerpt.append(
                line
            )

    return (
        tuple(excerpt),
        truncated,
    )


def _require_non_overlapping(
    edits: list[_ResolvedEdit],
) -> None:
    ordered = sorted(
        edits,
        key=lambda item: (
            item.start_line_index,
            item.end_line_index,
            item.edit.edit_ref,
        ),
    )

    for previous, current in zip(
        ordered,
        ordered[1:],
        strict=False,
    ):
        if (
            current.start_line_index
            < previous.end_line_index
        ):
            raise DeterministicEditError(
                "EDIT_OVERLAP",
                (
                    f"EDIT {previous.edit.edit_ref!r} and "
                    f"{current.edit.edit_ref!r} overlap in "
                    f"{current.edit.target!r}"
                ),
            )


def _snapshot_logical_lines(
    snapshot: TextSnapshot,
) -> tuple[str, ...]:
    text = snapshot.text

    if snapshot.newline_style is NewlineStyle.CRLF:
        separator = "\r\n"
    elif snapshot.newline_style is NewlineStyle.LF:
        separator = "\n"
    else:
        if text == "":
            return ()
        return (text,)

    body = text

    if snapshot.has_final_newline:
        body = body[:-len(separator)]

    return tuple(body.split(separator))


def _encode_partial_result(
    snapshot: TextSnapshot,
    logical_lines: list[str],
) -> bytes:
    if snapshot.newline_style is NewlineStyle.CRLF:
        separator = "\r\n"
    elif snapshot.newline_style is NewlineStyle.LF:
        separator = "\n"
    else:
        if len(logical_lines) > 1:
            raise DeterministicEditError(
                "UNSUPPORTED_NEWLINE",
                (
                    f"target {snapshot.target!r} has no "
                    "established newline style, but the "
                    "replacement would introduce multiple lines"
                ),
            )
        separator = "\n"

    body = separator.join(logical_lines)

    if snapshot.has_final_newline:
        body += separator

    encoded = body.encode("utf-8")

    if snapshot.has_utf8_bom:
        return codecs.BOM_UTF8 + encoded

    return encoded
