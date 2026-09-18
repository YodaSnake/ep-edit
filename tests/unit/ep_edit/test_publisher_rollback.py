from __future__ import annotations

import stat
from pathlib import Path

import pytest

import ep_edit.publisher as publisher_module
from ep_edit.errors import DeterministicEditError
from ep_edit.planner import plan_edit_text as _plan_edit_text
from ep_edit.publisher import publish_edit_plan


pytestmark = pytest.mark.unit


def plan_edit_text(
    root: Path,
    text: str,
):
    return _plan_edit_text(
        root,
        text,
    )


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


def _assert_no_stage_or_backup(
    root: Path,
) -> None:
    assert list(
        root.rglob(
            ".ep-edit-stage-*"
        )
    ) == []

    assert list(
        root.rglob(
            ".ep-edit-backup-*"
        )
    ) == []


def _install_second_publish_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_publish = (
        publisher_module
        ._publish_one
    )
    call_count = 0

    def failing_publish(
        state,
        staged,
    ):
        nonlocal call_count
        call_count += 1

        if call_count == 2:
            raise OSError(
                "injected second publish failure"
            )

        return original_publish(
            state,
            staged,
        )

    monkeypatch.setattr(
        publisher_module,
        "_publish_one",
        failing_publish,
    )


def test_staging_failure_before_publish_leaves_all_targets_original(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = _write(
        tmp_path,
        "a.py",
        b"a = 1\n",
    )
    second = _write(
        tmp_path,
        "b.py",
        b"b = 1\n",
    )

    plan = plan_edit_text(
        tmp_path,
        """FILE: a.py
LABEL: update-a
<<<<<<< SEARCH
a = 1
=======
a = 2
>>>>>>> REPLACE

FILE: b.py
LABEL: update-b
<<<<<<< SEARCH
b = 1
=======
b = 2
>>>>>>> REPLACE
""",
    )

    original_stage = (
        publisher_module
        ._stage_candidate
    )
    call_count = 0

    def failing_stage(
        root: Path,
        mutation,
    ):
        nonlocal call_count
        call_count += 1

        if call_count == 2:
            raise OSError(
                "injected staging failure"
            )

        return original_stage(
            root,
            mutation,
        )

    monkeypatch.setattr(
        publisher_module,
        "_stage_candidate",
        failing_stage,
    )

    _assert_error(
        "APPLY_FAILED_ROLLED_BACK",
        lambda: publish_edit_plan(
            plan
        ),
    )

    assert (
        first.read_bytes()
        == b"a = 1\n"
    )
    assert (
        second.read_bytes()
        == b"b = 1\n"
    )
    _assert_no_stage_or_backup(
        tmp_path
    )


def test_second_publish_failure_rolls_back_first_replace_and_mode(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = _write(
        tmp_path,
        "a.py",
        b"a = 1\n",
    )
    second = _write(
        tmp_path,
        "b.py",
        b"b = 1\n",
    )
    first.chmod(
        0o755
    )

    plan = plan_edit_text(
        tmp_path,
        """FILE: a.py
LABEL: update-a
<<<<<<< SEARCH
a = 1
=======
a = 2
>>>>>>> REPLACE

FILE: b.py
LABEL: update-b
<<<<<<< SEARCH
b = 1
=======
b = 2
>>>>>>> REPLACE
""",
    )

    _install_second_publish_failure(
        monkeypatch
    )

    _assert_error(
        "APPLY_FAILED_ROLLED_BACK",
        lambda: publish_edit_plan(
            plan
        ),
    )

    assert (
        first.read_bytes()
        == b"a = 1\n"
    )
    assert (
        second.read_bytes()
        == b"b = 1\n"
    )
    assert (
        stat.S_IMODE(
            first.stat().st_mode
        )
        == 0o755
    )
    _assert_no_stage_or_backup(
        tmp_path
    )


def test_second_publish_failure_rolls_back_prior_create(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    existing = _write(
        tmp_path,
        "z.py",
        b"z = 1\n",
    )

    plan = plan_edit_text(
        tmp_path,
        """FILE: a-created.txt
LABEL: create-a
MODE: CREATE
<<<<<<< CONTENT
created
>>>>>>> CONTENT

FILE: z.py
LABEL: update-z
<<<<<<< SEARCH
z = 1
=======
z = 2
>>>>>>> REPLACE
""",
    )

    _install_second_publish_failure(
        monkeypatch
    )

    _assert_error(
        "APPLY_FAILED_ROLLED_BACK",
        lambda: publish_edit_plan(
            plan
        ),
    )

    assert not (
        tmp_path
        / "a-created.txt"
    ).exists()

    assert (
        existing.read_bytes()
        == b"z = 1\n"
    )
    _assert_no_stage_or_backup(
        tmp_path
    )


def test_second_publish_failure_rolls_back_prior_delete(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    deleted = _write(
        tmp_path,
        "a-obsolete.txt",
        b"obsolete\n",
    )
    existing = _write(
        tmp_path,
        "z.py",
        b"z = 1\n",
    )

    plan = plan_edit_text(
        tmp_path,
        """FILE: a-obsolete.txt
LABEL: delete-a
MODE: DELETE

FILE: z.py
LABEL: update-z
<<<<<<< SEARCH
z = 1
=======
z = 2
>>>>>>> REPLACE
""",
    )

    _install_second_publish_failure(
        monkeypatch
    )

    _assert_error(
        "APPLY_FAILED_ROLLED_BACK",
        lambda: publish_edit_plan(
            plan
        ),
    )

    assert (
        deleted.read_bytes()
        == b"obsolete\n"
    )
    assert (
        existing.read_bytes()
        == b"z = 1\n"
    )
    _assert_no_stage_or_backup(
        tmp_path
    )


def test_replace_failure_after_backup_rename_restores_original(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = _write(
        tmp_path,
        "example.py",
        b"value = 1\n",
    )

    plan = plan_edit_text(
        tmp_path,
        """FILE: example.py
LABEL: update-value
<<<<<<< SEARCH
value = 1
=======
value = 2
>>>>>>> REPLACE
""",
    )

    original_replace = (
        publisher_module.os.replace
    )

    def failing_replace(
        source,
        destination,
        *args,
        **kwargs,
    ):
        source_path = Path(
            source
        )
        destination_path = Path(
            destination
        )

        if (
            source_path.name.startswith(
                ".ep-edit-stage-"
            )
            and destination_path.name
            == "example.py"
        ):
            raise OSError(
                "injected candidate publish failure"
            )

        return original_replace(
            source,
            destination,
            *args,
            **kwargs,
        )

    monkeypatch.setattr(
        publisher_module.os,
        "replace",
        failing_replace,
    )

    _assert_error(
        "APPLY_FAILED_ROLLED_BACK",
        lambda: publish_edit_plan(
            plan
        ),
    )

    assert (
        target.read_bytes()
        == b"value = 1\n"
    )
    _assert_no_stage_or_backup(
        tmp_path
    )


def test_second_post_apply_verify_failure_rolls_back_both_published_targets(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = _write(
        tmp_path,
        "a.py",
        b"a = 1\n",
    )
    second = _write(
        tmp_path,
        "b.py",
        b"b = 1\n",
    )

    plan = plan_edit_text(
        tmp_path,
        """FILE: a.py
LABEL: update-a
<<<<<<< SEARCH
a = 1
=======
a = 2
>>>>>>> REPLACE

FILE: b.py
LABEL: update-b
<<<<<<< SEARCH
b = 1
=======
b = 2
>>>>>>> REPLACE
""",
    )

    original_verify = (
        publisher_module
        ._verify_applied_mutation
    )
    call_count = 0

    def failing_second_verify(
        root: Path,
        mutation,
    ) -> None:
        nonlocal call_count
        call_count += 1

        if call_count == 2:
            raise DeterministicEditError(
                "POST_APPLY_VERIFY_FAILED",
                "injected second verification failure",
            )

        original_verify(
            root,
            mutation,
        )

    monkeypatch.setattr(
        publisher_module,
        "_verify_applied_mutation",
        failing_second_verify,
    )

    _assert_error(
        "APPLY_FAILED_ROLLED_BACK",
        lambda: publish_edit_plan(
            plan
        ),
    )

    assert (
        first.read_bytes()
        == b"a = 1\n"
    )
    assert (
        second.read_bytes()
        == b"b = 1\n"
    )
    _assert_no_stage_or_backup(
        tmp_path
    )


def test_rollback_restore_failure_is_reported_explicitly(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = _write(
        tmp_path,
        "a.py",
        b"a = 1\n",
    )
    second = _write(
        tmp_path,
        "z.py",
        b"z = 1\n",
    )

    plan = plan_edit_text(
        tmp_path,
        """FILE: a.py
LABEL: update-a
<<<<<<< SEARCH
a = 1
=======
a = 2
>>>>>>> REPLACE

FILE: z.py
LABEL: update-z
<<<<<<< SEARCH
z = 1
=======
z = 2
>>>>>>> REPLACE
""",
    )

    _install_second_publish_failure(
        monkeypatch
    )

    original_rename = (
        publisher_module.os.rename
    )

    def failing_restore_rename(
        source,
        destination,
        *args,
        **kwargs,
    ):
        source_path = Path(
            source
        )
        destination_path = Path(
            destination
        )

        if (
            source_path.name.startswith(
                ".ep-edit-backup-"
            )
            and destination_path.name
            == "a.py"
        ):
            raise OSError(
                "injected rollback restore failure"
            )

        return original_rename(
            source,
            destination,
            *args,
            **kwargs,
        )

    monkeypatch.setattr(
        publisher_module.os,
        "rename",
        failing_restore_rename,
    )

    _assert_error(
        "ROLLBACK_FAILED",
        lambda: publish_edit_plan(
            plan
        ),
    )

    assert not first.exists()
    assert (
        second.read_bytes()
        == b"z = 1\n"
    )

    backups = list(
        tmp_path.glob(
            ".ep-edit-backup-*"
        )
    )

    assert len(backups) == 1
    assert (
        backups[0].read_bytes()
        == b"a = 1\n"
    )

    assert list(
        tmp_path.rglob(
            ".ep-edit-stage-*"
        )
    ) == []


def test_successful_publication_with_backup_cleanup_failure_is_explicit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = _write(
        tmp_path,
        "example.py",
        b"value = 1\n",
    )

    plan = plan_edit_text(
        tmp_path,
        """FILE: example.py
LABEL: update-value
<<<<<<< SEARCH
value = 1
=======
value = 2
>>>>>>> REPLACE
""",
    )

    original_unlink = Path.unlink

    def failing_backup_unlink(
        self: Path,
        *args,
        **kwargs,
    ):
        if self.name.startswith(
            ".ep-edit-backup-"
        ):
            raise OSError(
                "injected backup cleanup failure"
            )

        return original_unlink(
            self,
            *args,
            **kwargs,
        )

    monkeypatch.setattr(
        Path,
        "unlink",
        failing_backup_unlink,
    )

    _assert_error(
        "APPLY_CLEANUP_FAILED",
        lambda: publish_edit_plan(
            plan
        ),
    )

    assert (
        target.read_bytes()
        == b"value = 2\n"
    )

    backups = list(
        tmp_path.glob(
            ".ep-edit-backup-*"
        )
    )

    assert len(backups) == 1
    assert (
        backups[0].read_bytes()
        == b"value = 1\n"
    )

    assert list(
        tmp_path.rglob(
            ".ep-edit-stage-*"
        )
    ) == []
