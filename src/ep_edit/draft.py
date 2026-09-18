from __future__ import annotations

import hashlib
import os
import stat
import tempfile
from pathlib import Path

from ep_edit.display import operator_path
from ep_edit.errors import DeterministicEditError
from ep_edit.revision import (
    RevisionResult,
    revise_edit_specification,
)


def specification_fingerprint(
    raw: bytes,
) -> str:
    return hashlib.sha256(
        raw
    ).hexdigest()


def revise_draft_file(
    base_path: Path,
    revision_text: str,
) -> RevisionResult:
    path = base_path.expanduser()

    try:
        base_stat = path.lstat()
    except FileNotFoundError as exc:
        raise DeterministicEditError(
            "REVISION_BASE_NOT_FOUND",
            (
                "base Edit Specification "
                "does not exist: "
                f"{operator_path(path)}"
            ),
        ) from exc

    _require_safe_draft_file(
        path,
        base_stat,
    )

    base_raw = path.read_bytes()

    try:
        base_text = base_raw.decode(
            "utf-8"
        )
    except UnicodeDecodeError as exc:
        raise DeterministicEditError(
            "REVISION_PARSE_ERROR",
            (
                "base Edit Specification "
                "is not valid UTF-8"
            ),
        ) from exc

    result = revise_edit_specification(
        base_text,
        revision_text,
    )
    revised_raw = (
        result.revised_text.encode(
            "utf-8"
        )
    )

    if (
        result.base_fingerprint
        != specification_fingerprint(
            base_raw
        )
    ):
        raise DeterministicEditError(
            "STALE_SPECIFICATION",
            (
                "base specification fingerprint "
                "changed during revision"
            ),
        )

    if (
        result.revised_fingerprint
        != specification_fingerprint(
            revised_raw
        )
    ):
        raise RuntimeError(
            (
                "internal revised specification "
                "fingerprint mismatch"
            )
        )

    temp_path = _prepare_draft_temp(
        path,
        revised_raw,
        stat.S_IMODE(
            base_stat.st_mode
        ),
    )

    try:
        _require_current_draft(
            path,
            base_raw,
        )

        os.replace(
            temp_path,
            path,
        )
    finally:
        try:
            temp_path.unlink()
        except FileNotFoundError:
            pass

    return result


def _require_safe_draft_file(
    path: Path,
    file_stat: os.stat_result,
) -> None:
    if stat.S_ISLNK(
        file_stat.st_mode
    ):
        raise DeterministicEditError(
            "REVISION_BASE_NOT_FOUND",
            (
                "base Edit Specification "
                "must not be a symlink: "
                f"{operator_path(path)}"
            ),
        )

    if not stat.S_ISREG(
        file_stat.st_mode
    ):
        raise DeterministicEditError(
            "REVISION_BASE_NOT_FOUND",
            (
                "base Edit Specification "
                "is not a regular file: "
                f"{operator_path(path)}"
            ),
        )

    if file_stat.st_nlink > 1:
        raise DeterministicEditError(
            "REVISION_BASE_NOT_FOUND",
            (
                "base Edit Specification "
                "must not be hard-linked: "
                f"{operator_path(path)}"
            ),
        )


def _require_current_draft(
    path: Path,
    expected_raw: bytes,
) -> None:
    try:
        current_stat = path.lstat()
    except FileNotFoundError as exc:
        raise DeterministicEditError(
            "STALE_SPECIFICATION",
            (
                "base Edit Specification "
                "disappeared during revision"
            ),
        ) from exc

    try:
        _require_safe_draft_file(
            path,
            current_stat,
        )
    except DeterministicEditError as exc:
        raise DeterministicEditError(
            "STALE_SPECIFICATION",
            (
                "base Edit Specification "
                "identity changed during revision"
            ),
        ) from exc

    current_raw = path.read_bytes()

    if current_raw != expected_raw:
        raise DeterministicEditError(
            "STALE_SPECIFICATION",
            (
                "base Edit Specification "
                "changed during revision"
            ),
        )


def _prepare_draft_temp(
    path: Path,
    raw: bytes,
    mode: int,
) -> Path:
    parent = path.parent
    file_descriptor, temp_name = (
        tempfile.mkstemp(
            prefix=(
                f".{path.name}."
                "ep-edit-"
            ),
            dir=str(
                parent
            ),
        )
    )
    temp_path = Path(
        temp_name
    )

    try:
        if hasattr(
            os,
            "fchmod",
        ):
            os.fchmod(
                file_descriptor,
                mode,
            )

        with os.fdopen(
            file_descriptor,
            "wb",
        ) as handle:
            handle.write(
                raw
            )
            handle.flush()
            os.fsync(
                handle.fileno()
            )
    except BaseException:
        try:
            os.close(
                file_descriptor
            )
        except OSError:
            pass

        try:
            temp_path.unlink()
        except FileNotFoundError:
            pass

        raise

    return temp_path
