from __future__ import annotations

from pathlib import Path

import pytest

from ep_edit.errors import DeterministicEditError
from ep_edit.planner import plan_edit_text
from ep_edit.publisher import (
    revalidate_publication_preconditions,
    revalidate_target_mutation,
)


pytestmark = pytest.mark.unit


def _write(
    root: Path,
    target: str,
    raw: bytes,
) -> Path:
    file_path = (
        root
        / target
    )
    file_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    file_path.write_bytes(
        raw
    )
    return file_path


def _assert_error(
    code: str,
    callable_,
) -> DeterministicEditError:
    with pytest.raises(
        DeterministicEditError
    ) as raised:
        callable_()

    assert raised.value.code == code
    return raised.value


def _replace_spec() -> str:
    return """FILE: example.py
EDIT: update-value
<<<<<<< SEARCH
value = 1
=======
value = 2
>>>>>>> REPLACE
"""


def test_immutable_input_skips_specification_revalidation(
    tmp_path: Path,
) -> None:
    _write(
        tmp_path,
        "example.py",
        b"value = 1\n",
    )
    plan = plan_edit_text(
        tmp_path,
        _replace_spec(),
    )

    report = revalidate_publication_preconditions(
        plan
    )

    assert report.specification_checked is False
    assert report.specification_sha256 is None
    assert len(report.targets) == 1
    assert report.targets[0].state == "CURRENT"


def test_file_backed_specification_exact_fingerprint_passes(
    tmp_path: Path,
) -> None:
    _write(
        tmp_path,
        "example.py",
        b"value = 1\n",
    )
    specification = _replace_spec()
    spec_path = (
        tmp_path
        / "edit-spec.txt"
    )
    spec_path.write_bytes(
        specification.encode(
            "utf-8"
        )
    )

    plan = plan_edit_text(
        tmp_path,
        specification,
    )

    report = revalidate_publication_preconditions(
        plan,
        specification_path=spec_path,
    )

    assert report.specification_checked is True
    assert (
        report.specification_sha256
        == plan.input_fingerprint
    )


def test_file_backed_specification_change_is_stale(
    tmp_path: Path,
) -> None:
    target = _write(
        tmp_path,
        "example.py",
        b"value = 1\n",
    )
    specification = _replace_spec()
    spec_path = (
        tmp_path
        / "edit-spec.txt"
    )
    spec_path.write_bytes(
        specification.encode(
            "utf-8"
        )
    )

    plan = plan_edit_text(
        tmp_path,
        specification,
    )

    spec_path.write_bytes(
        specification.replace(
            "value = 2",
            "value = 3",
        ).encode(
            "utf-8"
        )
    )

    _assert_error(
        "STALE_SPECIFICATION",
        lambda: revalidate_publication_preconditions(
            plan,
            specification_path=spec_path,
        ),
    )

    assert (
        target.read_bytes()
        == b"value = 1\n"
    )


def test_missing_file_backed_specification_is_stale(
    tmp_path: Path,
) -> None:
    _write(
        tmp_path,
        "example.py",
        b"value = 1\n",
    )
    specification = _replace_spec()
    spec_path = (
        tmp_path
        / "edit-spec.txt"
    )
    spec_path.write_bytes(
        specification.encode(
            "utf-8"
        )
    )

    plan = plan_edit_text(
        tmp_path,
        specification,
    )

    spec_path.unlink()

    _assert_error(
        "STALE_SPECIFICATION",
        lambda: revalidate_publication_preconditions(
            plan,
            specification_path=spec_path,
        ),
    )


def test_crlf_file_backed_specification_uses_exact_bytes(
    tmp_path: Path,
) -> None:
    _write(
        tmp_path,
        "example.py",
        b"value = 1\n",
    )
    specification = _replace_spec().replace(
        "\n",
        "\r\n",
    )
    spec_path = (
        tmp_path
        / "edit-spec.txt"
    )
    spec_path.write_bytes(
        specification.encode(
            "utf-8"
        )
    )

    plan = plan_edit_text(
        tmp_path,
        specification,
    )

    report = revalidate_publication_preconditions(
        plan,
        specification_path=spec_path,
    )

    assert (
        report.specification_sha256
        == plan.input_fingerprint
    )


def test_replace_target_exact_bytes_remain_current(
    tmp_path: Path,
) -> None:
    _write(
        tmp_path,
        "example.py",
        b"value = 1\n",
    )
    plan = plan_edit_text(
        tmp_path,
        _replace_spec(),
    )

    result = revalidate_target_mutation(
        plan.root,
        plan.files[0],
    )

    assert result.current_exists is True
    assert (
        result.current_sha256
        == plan.files[0].before_sha256
    )


def test_replace_target_byte_drift_is_stale_preview(
    tmp_path: Path,
) -> None:
    target = _write(
        tmp_path,
        "example.py",
        b"value = 1\n",
    )
    plan = plan_edit_text(
        tmp_path,
        _replace_spec(),
    )

    target.write_bytes(
        b"value = 9\n"
    )

    _assert_error(
        "STALE_PREVIEW",
        lambda: revalidate_publication_preconditions(
            plan
        ),
    )

    assert (
        target.read_bytes()
        == b"value = 9\n"
    )


def test_same_size_byte_drift_is_detected(
    tmp_path: Path,
) -> None:
    target = _write(
        tmp_path,
        "example.py",
        b"value = 1\n",
    )
    plan = plan_edit_text(
        tmp_path,
        _replace_spec(),
    )

    target.write_bytes(
        b"value = 9\n"
    )

    assert (
        len(plan.files[0].before_bytes)
        == target.stat().st_size
    )

    _assert_error(
        "STALE_PREVIEW",
        lambda: revalidate_target_mutation(
            plan.root,
            plan.files[0],
        ),
    )


def test_same_bytes_new_inode_remains_current(
    tmp_path: Path,
) -> None:
    target = _write(
        tmp_path,
        "example.py",
        b"value = 1\n",
    )
    plan = plan_edit_text(
        tmp_path,
        _replace_spec(),
    )

    replacement = (
        tmp_path
        / "replacement.tmp"
    )
    replacement.write_bytes(
        b"value = 1\n"
    )
    replacement.replace(
        target
    )

    result = revalidate_target_mutation(
        plan.root,
        plan.files[0],
    )

    assert result.state == "CURRENT"


def test_create_target_still_absent_passes(
    tmp_path: Path,
) -> None:
    (tmp_path / "src").mkdir()

    plan = plan_edit_text(
        tmp_path,
        """FILE: src/new.py
EDIT: create-new
MODE: CREATE
<<<<<<< CONTENT
value = 1
>>>>>>> CONTENT
""",
    )

    result = revalidate_target_mutation(
        plan.root,
        plan.files[0],
    )

    assert result.current_exists is False
    assert (
        tmp_path
        / "src/new.py"
    ).exists() is False


def test_root_directory_replacement_is_stale(
    tmp_path: Path,
) -> None:
    plan = plan_edit_text(
        tmp_path,
        (
            "FILE: missing/new.py\n"
            "EDIT: create-new\n"
            "MODE: CREATE\n"
            + "<" * 7
            + " CONTENT\n"
            + "value = 1\n"
            + ">" * 7
            + " CONTENT\n"
        ),
    )

    displaced = (
        tmp_path.parent
        / f"{tmp_path.name}-displaced"
    )
    tmp_path.rename(
        displaced
    )
    tmp_path.mkdir()

    _assert_error(
        "STALE_PREVIEW",
        lambda: revalidate_publication_preconditions(
            plan
        ),
    )

    assert tmp_path.is_dir()
    assert displaced.is_dir()
    assert not (
        tmp_path
        / "missing"
    ).exists()


def test_create_missing_parent_chain_remains_absent_during_preflight(
    tmp_path: Path,
) -> None:
    plan = plan_edit_text(
        tmp_path,
        (
            "FILE: missing/deep/new.py\n"
            "EDIT: create-new\n"
            "MODE: CREATE\n"
            + "<" * 7
            + " CONTENT\n"
            + "value = 1\n"
            + ">" * 7
            + " CONTENT\n"
        ),
    )

    result = revalidate_publication_preconditions(
        plan
    )

    assert result.targets[0].current_exists is False
    assert not (
        tmp_path
        / "missing"
    ).exists()


def test_existing_create_parent_directory_replacement_is_stale(
    tmp_path: Path,
) -> None:
    existing = (
        tmp_path
        / "existing"
    )
    existing.mkdir()

    plan = plan_edit_text(
        tmp_path,
        (
            "FILE: existing/missing/new.py\n"
            "EDIT: create-new\n"
            "MODE: CREATE\n"
            + "<" * 7
            + " CONTENT\n"
            + "value = 1\n"
            + ">" * 7
            + " CONTENT\n"
        ),
    )

    displaced = (
        tmp_path
        / "existing-displaced"
    )
    existing.rename(
        displaced
    )
    existing.mkdir()

    _assert_error(
        "STALE_PREVIEW",
        lambda: revalidate_publication_preconditions(
            plan
        ),
    )

    assert existing.is_dir()
    assert displaced.is_dir()
    assert not (
        existing
        / "missing"
    ).exists()


def test_planned_missing_create_parent_appearing_is_stale(
    tmp_path: Path,
) -> None:
    plan = plan_edit_text(
        tmp_path,
        (
            "FILE: missing/deep/new.py\n"
            "EDIT: create-new\n"
            "MODE: CREATE\n"
            + "<" * 7
            + " CONTENT\n"
            + "value = 1\n"
            + ">" * 7
            + " CONTENT\n"
        ),
    )

    concurrent_parent = (
        tmp_path
        / "missing"
    )
    concurrent_parent.mkdir()

    _assert_error(
        "STALE_PREVIEW",
        lambda: revalidate_publication_preconditions(
            plan
        ),
    )

    assert concurrent_parent.is_dir()


def test_create_target_reappears_after_preview_is_stale(
    tmp_path: Path,
) -> None:
    (tmp_path / "src").mkdir()

    plan = plan_edit_text(
        tmp_path,
        """FILE: src/new.py
EDIT: create-new
MODE: CREATE
<<<<<<< CONTENT
value = 1
>>>>>>> CONTENT
""",
    )

    target = _write(
        tmp_path,
        "src/new.py",
        b"concurrent\n",
    )

    _assert_error(
        "STALE_PREVIEW",
        lambda: revalidate_publication_preconditions(
            plan
        ),
    )

    assert (
        target.read_bytes()
        == b"concurrent\n"
    )


def test_create_parent_removed_after_preview_is_stale(
    tmp_path: Path,
) -> None:
    parent = (
        tmp_path
        / "src"
    )
    parent.mkdir()

    plan = plan_edit_text(
        tmp_path,
        """FILE: src/new.py
EDIT: create-new
MODE: CREATE
<<<<<<< CONTENT
value = 1
>>>>>>> CONTENT
""",
    )

    parent.rmdir()

    _assert_error(
        "STALE_PREVIEW",
        lambda: revalidate_publication_preconditions(
            plan
        ),
    )


def test_delete_target_exact_bytes_remain_current(
    tmp_path: Path,
) -> None:
    _write(
        tmp_path,
        "obsolete.txt",
        b"obsolete\n",
    )

    plan = plan_edit_text(
        tmp_path,
        """FILE: obsolete.txt
EDIT: delete-obsolete
MODE: DELETE
""",
    )

    result = revalidate_target_mutation(
        plan.root,
        plan.files[0],
    )

    assert result.current_exists is True


def test_delete_target_missing_after_preview_is_stale(
    tmp_path: Path,
) -> None:
    target = _write(
        tmp_path,
        "obsolete.txt",
        b"obsolete\n",
    )

    plan = plan_edit_text(
        tmp_path,
        """FILE: obsolete.txt
EDIT: delete-obsolete
MODE: DELETE
""",
    )

    target.unlink()

    _assert_error(
        "STALE_PREVIEW",
        lambda: revalidate_publication_preconditions(
            plan
        ),
    )


def test_delete_target_byte_drift_is_stale(
    tmp_path: Path,
) -> None:
    target = _write(
        tmp_path,
        "obsolete.txt",
        b"obsolete\n",
    )

    plan = plan_edit_text(
        tmp_path,
        """FILE: obsolete.txt
EDIT: delete-obsolete
MODE: DELETE
""",
    )

    target.write_bytes(
        b"changed\n"
    )

    _assert_error(
        "STALE_PREVIEW",
        lambda: revalidate_publication_preconditions(
            plan
        ),
    )

    assert (
        target.read_bytes()
        == b"changed\n"
    )


def test_target_changed_to_symlink_is_stale(
    tmp_path: Path,
) -> None:
    target = _write(
        tmp_path,
        "example.py",
        b"value = 1\n",
    )
    alternate = _write(
        tmp_path,
        "alternate.py",
        b"value = 1\n",
    )

    plan = plan_edit_text(
        tmp_path,
        _replace_spec(),
    )

    target.unlink()

    try:
        target.symlink_to(
            alternate
        )
    except OSError:
        pytest.skip(
            "symbolic links are unavailable"
        )

    _assert_error(
        "STALE_PREVIEW",
        lambda: revalidate_publication_preconditions(
            plan
        ),
    )


def test_multi_file_global_revalidation_fails_before_any_write(
    tmp_path: Path,
) -> None:
    a = _write(
        tmp_path,
        "a.py",
        b"a = 1\n",
    )
    b = _write(
        tmp_path,
        "b.py",
        b"b = 1\n",
    )

    plan = plan_edit_text(
        tmp_path,
        """FILE: a.py
EDIT: update-a
<<<<<<< SEARCH
a = 1
=======
a = 2
>>>>>>> REPLACE

FILE: b.py
EDIT: update-b
<<<<<<< SEARCH
b = 1
=======
b = 2
>>>>>>> REPLACE
""",
    )

    b.write_bytes(
        b"b = 9\n"
    )

    _assert_error(
        "STALE_PREVIEW",
        lambda: revalidate_publication_preconditions(
            plan
        ),
    )

    assert a.read_bytes() == b"a = 1\n"
    assert b.read_bytes() == b"b = 9\n"


def test_preflight_is_read_only(
    tmp_path: Path,
) -> None:
    target = _write(
        tmp_path,
        "example.py",
        b"value = 1\n",
    )

    plan = plan_edit_text(
        tmp_path,
        _replace_spec(),
    )
    before = target.read_bytes()

    revalidate_publication_preconditions(
        plan
    )

    assert target.read_bytes() == before
