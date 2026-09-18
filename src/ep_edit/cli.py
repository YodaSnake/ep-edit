from __future__ import annotations

import argparse
import codecs
import json
import shutil
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, TextIO

from ep_edit.display import operator_path
from ep_edit.draft import revise_draft_file
from ep_edit.errors import (
    DeterministicEditError,
    EditPreflightError,
    RepairMetadata,
)
from ep_edit.planner import plan_edit_text
from ep_edit.preview import build_validated_preview
from ep_edit.publisher import publish_edit_plan
from ep_edit.validators import validate_edit_plan


ApprovalReader = Callable[[str], str]


@dataclass(frozen=True)
class _SpecificationInput:
    text: str
    specification_path: Path | None
    provider: str


def main(
    argv: list[str] | None = None,
    *,
    stdin_binary: BinaryIO | None = None,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
    approval_reader: ApprovalReader | None = None,
) -> int:
    output = (
        sys.stdout
        if stdout is None
        else stdout
    )
    error_output = (
        sys.stderr
        if stderr is None
        else stderr
    )

    parser = _build_parser()

    try:
        args = parser.parse_args(
            argv
        )

        if args.command == "revise":
            return _run_revise(
                args,
                output=output,
            )

        specification_input = (
            _load_specification_input(
                args,
                stdin_binary=stdin_binary,
            )
        )

        root = (
            Path.cwd()
            if args.root is None
            else Path(
                args.root
            ).expanduser()
        )

        plan = plan_edit_text(
            root,
            specification_input.text,
        )

        if args.command == "check":
            report = validate_edit_plan(
                plan
            )

            print(
                (
                    "CHECK OK: "
                    f"{len(plan.files)} file(s), "
                    f"{_authored_edit_count(plan)} edit(s), "
                    f"{len(plan.warnings)} warning(s), "
                    f"{report.passed_count} validation PASS, "
                    f"{report.skipped_count} validation SKIPPED"
                ),
                file=output,
            )
            return 0

        if args.command == "preview":
            preview = (
                build_validated_preview(
                    plan
                )
            )
            _write_preview(
                output,
                preview.text,
            )
            return 0

        if args.command == "apply":
            preview = (
                build_validated_preview(
                    plan
                )
            )
            _write_preview(
                output,
                preview.text,
            )

            approved = _request_approval(
                approval_reader=approval_reader,
            )

            if not approved:
                print(
                    "NOT APPLIED: approval declined.",
                    file=output,
                )
                return 0

            result = publish_edit_plan(
                plan,
                specification_path=(
                    specification_input
                    .specification_path
                ),
            )

            print(
                (
                    "APPLIED: "
                    f"{len(result.targets)} target(s)."
                ),
                file=output,
            )
            return 0

        raise RuntimeError(
            f"unsupported command: {args.command}"
        )

    except EditPreflightError as exc:
        _write_edit_preflight_failure(
            error_output,
            exc,
        )
        return 1

    except DeterministicEditError as exc:
        print(
            (
                f"ERROR {exc.code}: "
                f"{exc.message}"
            ),
            file=error_output,
        )
        return 1

    except OSError:
        print(
            (
                "ERROR IO_ERROR: "
                "filesystem operation failed"
            ),
            file=error_output,
        )
        return 1


def _write_edit_preflight_failure(
    output: TextIO,
    error: EditPreflightError,
) -> None:
    print(
        (
            f"ERROR {error.code}: "
            f"{error.message}"
        ),
        file=output,
    )

    for position, diagnostic in enumerate(
        error.diagnostics,
        start=1,
    ):
        print(
            (
                f"{position}. "
                f"{diagnostic.edit_ref} "
                f"[{diagnostic.code}] "
                f"{diagnostic.target}"
            ),
            file=output,
        )

        if diagnostic.label is not None:
            print(
                (
                    "   Label: "
                    f"{diagnostic.label}"
                ),
                file=output,
            )

        print(
            (
                "   "
                f"{diagnostic.message}"
            ),
            file=output,
        )

        if (
            diagnostic.repair_metadata
            is not None
        ):
            _write_repair_metadata(
                output,
                diagnostic.repair_metadata,
            )

    payload = {
        "schema": "ep-edit-repair-v1",
        "error_count": len(
            error.diagnostics
        ),
        "errors": [
            {
                "code": diagnostic.code,
                "edit_ref": diagnostic.edit_ref,
                "label": diagnostic.label,
                "message": diagnostic.message,
                "repair": (
                    None
                    if diagnostic.repair_metadata
                    is None
                    else _repair_metadata_payload(
                        diagnostic.repair_metadata
                    )
                ),
                "target": diagnostic.target,
            }
            for diagnostic in error.diagnostics
        ],
    }

    print(
        (
            "REPAIR_JSON: "
            + json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
        ),
        file=output,
    )


def _terminal_safe_diagnostic_text(
    value: str,
) -> str:
    rendered: list[str] = []

    for character in value:
        codepoint = ord(character)

        if character == "\\":
            rendered.append(
                "\\\\"
            )
        elif character == "\t":
            rendered.append(
                "\\t"
            )
        elif (
            codepoint < 0x20
            or 0x7F <= codepoint <= 0x9F
        ):
            rendered.append(
                f"\\u{codepoint:04x}"
            )
        else:
            rendered.append(
                character
            )

    return "".join(
        rendered
    )


def _write_repair_metadata(
    output: TextIO,
    metadata: RepairMetadata,
) -> None:
    print(
        (
            "   Guidance: "
            f"{metadata.guidance}"
        ),
        file=output,
    )

    if not metadata.candidates:
        print(
            "   Candidates: none",
            file=output,
        )
        return

    if (
        metadata.candidates_truncated
        and metadata.total_candidate_count
        is not None
    ):
        print(
            (
                "   Candidates: showing "
                f"{len(metadata.candidates)} of "
                f"{metadata.total_candidate_count}"
            ),
            file=output,
        )

    for position, candidate in enumerate(
        metadata.candidates,
        start=1,
    ):
        if (
            candidate.similarity_basis_points
            is None
        ):
            detail = (
                f"lines {candidate.start_line}-"
                f"{candidate.end_line}"
            )
        else:
            similarity = (
                candidate.similarity_basis_points
                / 100
            )
            detail = (
                f"lines {candidate.start_line}-"
                f"{candidate.end_line}, "
                f"similarity={similarity:.2f}%"
            )

        print(
            (
                f"   Candidate {position}: "
                f"{detail}"
            ),
            file=output,
        )

        for line in candidate.excerpt:
            print(
                (
                    "      | "
                    + _terminal_safe_diagnostic_text(
                        line
                    )
                ),
                file=output,
            )

        if candidate.excerpt_truncated:
            print(
                "      | ...",
                file=output,
            )


def _repair_metadata_payload(
    metadata: RepairMetadata,
) -> dict[str, object]:
    return {
        "candidates": [
            {
                "end_line": candidate.end_line,
                "excerpt": list(
                    candidate.excerpt
                ),
                "excerpt_truncated": (
                    candidate.excerpt_truncated
                ),
                "similarity_basis_points": (
                    candidate.similarity_basis_points
                ),
                "start_line": candidate.start_line,
            }
            for candidate in metadata.candidates
        ],
        "candidates_truncated": (
            metadata.candidates_truncated
        ),
        "guidance": metadata.guidance,
        "kind": metadata.kind,
        "total_candidate_count": (
            metadata.total_candidate_count
        ),
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ep-edit",
        description=(
            "Deterministic exact text editing "
            "with preview-first interactive apply."
        ),
    )

    subcommands = parser.add_subparsers(
        dest="command",
        required=True,
    )

    check_parser = subcommands.add_parser(
        "check",
        help=(
            "Parse, plan, and validate without "
            "rendering a full preview or writing targets."
        ),
    )
    _add_edit_input_arguments(
        check_parser
    )

    preview_parser = subcommands.add_parser(
        "preview",
        help=(
            "Parse, plan, validate, and render "
            "the combined preview without writing."
        ),
    )
    _add_edit_input_arguments(
        preview_parser
    )

    apply_parser = subcommands.add_parser(
        "apply",
        help=(
            "Preview and require explicit y/yes "
            "before deterministic publication."
        ),
    )
    _add_edit_input_arguments(
        apply_parser
    )

    revise_parser = subcommands.add_parser(
        "revise",
        help=(
            "Revise a saved Edit Specification "
            "draft without modifying repository targets."
        ),
    )
    revise_parser.add_argument(
        "specification",
        help=(
            "Saved Edit Specification draft path."
        ),
    )
    revise_parser.add_argument(
        "revision",
        help=(
            "Revision Specification path."
        ),
    )

    return parser


def _add_edit_input_arguments(
    parser: argparse.ArgumentParser,
) -> None:
    parser.add_argument(
        "specification",
        nargs="?",
        help=(
            "Edit Specification path, or '-' for stdin."
        ),
    )
    parser.add_argument(
        "--clipboard",
        action="store_true",
        help=(
            "Read the complete Edit Specification "
            "from macOS pbpaste."
        ),
    )
    parser.add_argument(
        "--root",
        help=(
            "Explicit target root. Defaults to "
            "the current working directory."
        ),
    )


def _load_specification_input(
    args: argparse.Namespace,
    *,
    stdin_binary: BinaryIO | None,
) -> _SpecificationInput:
    if args.clipboard:
        if args.specification is not None:
            raise DeterministicEditError(
                "INPUT_PARSE_ERROR",
                (
                    "--clipboard cannot be combined "
                    "with a specification path"
                ),
            )

        raw = _read_clipboard_bytes()

        return _SpecificationInput(
            text=_decode_utf8_specification(
                raw
            ),
            specification_path=None,
            provider="clipboard",
        )

    if args.specification is None:
        raise DeterministicEditError(
            "INPUT_PARSE_ERROR",
            (
                "specification path, '-', or "
                "--clipboard is required"
            ),
        )

    if args.specification == "-":
        raw = _read_stdin_bytes(
            stdin_binary
        )

        return _SpecificationInput(
            text=_decode_utf8_specification(
                raw
            ),
            specification_path=None,
            provider="stdin",
        )

    specification_path = Path(
        args.specification
    ).expanduser()

    try:
        raw = specification_path.read_bytes()
    except OSError as exc:
        raise DeterministicEditError(
            "INPUT_PARSE_ERROR",
            (
                "Edit Specification cannot be read: "
                f"{operator_path(specification_path)}"
            ),
        ) from exc

    return _SpecificationInput(
        text=_decode_utf8_specification(
            raw
        ),
        specification_path=specification_path,
        provider="file",
    )


def _read_stdin_bytes(
    stdin_binary: BinaryIO | None,
) -> bytes:
    if stdin_binary is not None:
        return stdin_binary.read()

    stream = getattr(
        sys.stdin,
        "buffer",
        None,
    )

    if stream is not None:
        return stream.read()

    return sys.stdin.read().encode(
        "utf-8"
    )


def _read_clipboard_bytes() -> bytes:
    pbpaste = shutil.which(
        "pbpaste"
    )

    if pbpaste is None:
        raise DeterministicEditError(
            "INPUT_PARSE_ERROR",
            (
                "--clipboard requires the macOS "
                "pbpaste command"
            ),
        )

    completed = subprocess.run(
        [
            pbpaste,
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    if completed.returncode != 0:
        raise DeterministicEditError(
            "INPUT_PARSE_ERROR",
            (
                "pbpaste failed while reading "
                "the Edit Specification"
            ),
        )

    return completed.stdout


def _decode_utf8_specification(
    raw: bytes,
) -> str:
    if raw.startswith(
        codecs.BOM_UTF8
    ):
        raise DeterministicEditError(
            "UNSUPPORTED_ENCODING",
            (
                "Edit Specification UTF-8 BOM "
                "is not supported"
            ),
        )

    try:
        return raw.decode(
            "utf-8"
        )
    except UnicodeDecodeError as exc:
        raise DeterministicEditError(
            "UNSUPPORTED_ENCODING",
            (
                "Edit Specification must be "
                "valid UTF-8"
            ),
        ) from exc


def _request_approval(
    *,
    approval_reader: ApprovalReader | None,
) -> bool:
    reader = (
        _default_approval_reader
        if approval_reader is None
        else approval_reader
    )

    try:
        response = reader(
            "Apply these changes? [y/N] "
        )
    except (
        EOFError,
        KeyboardInterrupt,
    ):
        return False

    return (
        response.strip().lower()
        in {
            "y",
            "yes",
        }
    )


def _default_approval_reader(
    prompt: str,
) -> str:
    tty_path = Path(
        "/dev/tty"
    )

    try:
        with tty_path.open(
            "r+",
            encoding="utf-8",
        ) as tty:
            tty.write(
                prompt
            )
            tty.flush()

            response = tty.readline()

            if response == "":
                raise EOFError

            return response

    except OSError:
        return input(
            prompt
        )


def _run_revise(
    args: argparse.Namespace,
    *,
    output: TextIO,
) -> int:
    specification_path = Path(
        args.specification
    ).expanduser()
    revision_path = Path(
        args.revision
    ).expanduser()

    try:
        revision_raw = (
            revision_path.read_bytes()
        )
    except OSError as exc:
        raise DeterministicEditError(
            "REVISION_PARSE_ERROR",
            (
                "Revision Specification cannot "
                "be read: "
                f"{operator_path(revision_path)}"
            ),
        ) from exc

    revision_text = (
        _decode_utf8_revision(
            revision_raw
        )
    )

    result = revise_draft_file(
        specification_path,
        revision_text,
    )

    print(
        (
            "REVISED DRAFT: "
            f"{operator_path(specification_path)}"
        ),
        file=output,
    )
    print(
        (
            "Revised edits: "
            f"{_format_refs(result.revised_edit_refs)}"
        ),
        file=output,
    )
    if result.revised_edit_ref_mappings:
        print(
            (
                "Revised EditRefs: "
                + ", ".join(
                    f"{old_ref} -> {new_ref}"
                    for old_ref, new_ref
                    in result.revised_edit_ref_mappings
                )
            ),
            file=output,
        )

    print(
        (
            "Removed edits: "
            f"{_format_refs(result.removed_edit_refs)}"
        ),
        file=output,
    )
    print(
        (
            "Added edits: "
            f"{_format_refs(result.added_edit_refs)}"
        ),
        file=output,
    )
    print(
        (
            "Specification fingerprint: "
            f"{result.revised_fingerprint}"
        ),
        file=output,
    )

    return 0


def _decode_utf8_revision(
    raw: bytes,
) -> str:
    if raw.startswith(
        codecs.BOM_UTF8
    ):
        raise DeterministicEditError(
            "UNSUPPORTED_ENCODING",
            (
                "Revision Specification UTF-8 BOM "
                "is not supported"
            ),
        )

    try:
        return raw.decode(
            "utf-8"
        )
    except UnicodeDecodeError as exc:
        raise DeterministicEditError(
            "UNSUPPORTED_ENCODING",
            (
                "Revision Specification must be "
                "valid UTF-8"
            ),
        ) from exc


def _format_refs(
    values: tuple[str, ...],
) -> str:
    if not values:
        return "None"

    return ", ".join(
        values
    )


def _write_preview(
    output: TextIO,
    text: str,
) -> None:
    output.write(
        text
    )

    if not text.endswith(
        "\n"
    ):
        output.write(
            "\n"
        )


def _authored_edit_count(
    plan,
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


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
