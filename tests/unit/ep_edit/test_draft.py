from __future__ import annotations

import hashlib
import stat
from pathlib import Path

import pytest

import ep_edit.draft as draft_module
from ep_edit.draft import (
    revise_draft_file,
)
from ep_edit.errors import DeterministicEditError


pytestmark = pytest.mark.unit


BASE_SPEC = """EDIT_SPEC_VERSION: 1

FILE: src/a.py
EDIT: update-a

<<<<<<< SEARCH
old_a()
=======
new_a()
>>>>>>> REPLACE
"""


REVISION = """REVISION_SPEC_VERSION: 1

REVISE_EDIT: update-a

<<<<<<< EDIT
FILE: src/a.py
EDIT: update-a

<<<<<<< SEARCH
old_a()
=======
better_a()
>>>>>>> REPLACE
>>>>>>> EDIT
"""


def _assert_error(
    expected_code: str,
    callable_,
) -> DeterministicEditError:
    with pytest.raises(
        DeterministicEditError
    ) as raised:
        callable_()

    assert (
        raised.value.code
        == expected_code
    )

    return raised.value


def test_revise_draft_file_replaces_only_draft(
    tmp_path: Path,
) -> None:
    draft = (
        tmp_path
        / "edits.txt"
    )
    draft.write_text(
        BASE_SPEC,
        encoding="utf-8",
    )

    repository_target = (
        tmp_path
        / "src"
        / "a.py"
    )
    repository_target.parent.mkdir()
    repository_target.write_text(
        "repository target unchanged\n",
        encoding="utf-8",
    )

    result = revise_draft_file(
        draft,
        REVISION,
    )

    assert (
        "better_a()"
        in draft.read_text(
            encoding="utf-8"
        )
    )
    assert (
        repository_target.read_text(
            encoding="utf-8"
        )
        == "repository target unchanged\n"
    )
    assert (
        result.revised_edit_ids
        == ("update-a",)
    )


def test_revise_draft_file_reports_exact_fingerprint(
    tmp_path: Path,
) -> None:
    draft = (
        tmp_path
        / "edits.txt"
    )
    draft.write_text(
        BASE_SPEC,
        encoding="utf-8",
    )

    result = revise_draft_file(
        draft,
        REVISION,
    )
    raw = draft.read_bytes()

    assert (
        result.revised_fingerprint
        == hashlib.sha256(
            raw
        ).hexdigest()
    )


def test_revise_draft_file_preserves_posix_mode(
    tmp_path: Path,
) -> None:
    draft = (
        tmp_path
        / "edits.txt"
    )
    draft.write_text(
        BASE_SPEC,
        encoding="utf-8",
    )
    draft.chmod(
        0o640
    )

    revise_draft_file(
        draft,
        REVISION,
    )

    assert (
        stat.S_IMODE(
            draft.stat().st_mode
        )
        == 0o640
    )


def test_missing_draft_fails_closed(
    tmp_path: Path,
) -> None:
    _assert_error(
        "REVISION_BASE_NOT_FOUND",
        lambda: revise_draft_file(
            tmp_path / "missing.txt",
            REVISION,
        ),
    )


def test_symlink_draft_fails_closed(
    tmp_path: Path,
) -> None:
    source = (
        tmp_path
        / "source.txt"
    )
    source.write_text(
        BASE_SPEC,
        encoding="utf-8",
    )
    link = (
        tmp_path
        / "link.txt"
    )

    try:
        link.symlink_to(
            source.name
        )
    except OSError:
        pytest.skip(
            "symbolic links are unavailable"
        )

    _assert_error(
        "REVISION_BASE_NOT_FOUND",
        lambda: revise_draft_file(
            link,
            REVISION,
        ),
    )


def test_invalid_utf8_draft_fails_closed(
    tmp_path: Path,
) -> None:
    draft = (
        tmp_path
        / "edits.txt"
    )
    draft.write_bytes(
        b"\xff"
    )

    _assert_error(
        "REVISION_PARSE_ERROR",
        lambda: revise_draft_file(
            draft,
            REVISION,
        ),
    )


def test_concurrent_draft_change_is_not_overwritten(
    tmp_path: Path,
    monkeypatch,
) -> None:
    draft = (
        tmp_path
        / "edits.txt"
    )
    draft.write_text(
        BASE_SPEC,
        encoding="utf-8",
    )

    original_prepare = (
        draft_module
        ._prepare_draft_temp
    )

    def prepare_then_drift(
        path: Path,
        raw: bytes,
        mode: int,
    ) -> Path:
        temp_path = original_prepare(
            path,
            raw,
            mode,
        )
        draft.write_text(
            "concurrent change\n",
            encoding="utf-8",
        )
        return temp_path

    monkeypatch.setattr(
        draft_module,
        "_prepare_draft_temp",
        prepare_then_drift,
    )

    _assert_error(
        "STALE_SPECIFICATION",
        lambda: revise_draft_file(
            draft,
            REVISION,
        ),
    )

    assert (
        draft.read_text(
            encoding="utf-8"
        )
        == "concurrent change\n"
    )
