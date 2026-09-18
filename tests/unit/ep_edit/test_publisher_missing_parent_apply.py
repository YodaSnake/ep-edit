from __future__ import annotations

import os
from pathlib import Path

import pytest

import ep_edit.publisher as publisher_module
from ep_edit.errors import DeterministicEditError
from ep_edit.planner import plan_edit_text
from ep_edit.publisher import publish_edit_plan


pytestmark = pytest.mark.unit


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


def _assert_no_ep_edit_artifacts(
    root: Path,
) -> None:
    assert list(
        root.rglob(
            ".ep-edit-*"
        )
    ) == []


def test_missing_parent_create_publishes_through_secure_flow(
    tmp_path: Path,
) -> None:
    plan = plan_edit_text(
        tmp_path,
        (
            "FILE: missing/deep/new.txt\n"
            "EDIT: create-new\n"
            "MODE: CREATE\n"
            + "<" * 7
            + " CONTENT\n"
            + "created\n"
            + ">" * 7
            + " CONTENT\n"
        ),
    )

    result = publish_edit_plan(
        plan
    )

    assert (
        tmp_path
        / "missing/deep/new.txt"
    ).read_bytes() == b"created\n"

    assert [
        target.target
        for target in result.targets
    ] == [
        "missing/deep/new.txt",
    ]

    _assert_no_ep_edit_artifacts(
        tmp_path
    )


def test_first_missing_parent_mkdir_race_is_stale_without_owned_residue(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = plan_edit_text(
        tmp_path,
        (
            "FILE: missing/new.txt\n"
            "EDIT: create-new\n"
            "MODE: CREATE\n"
            + "<" * 7
            + " CONTENT\n"
            + "created\n"
            + ">" * 7
            + " CONTENT\n"
        ),
    )

    original_mkdir = os.mkdir
    triggered = False

    def racing_mkdir(
        path,
        mode=0o777,
        *,
        dir_fd=None,
    ):
        nonlocal triggered

        if (
            not triggered
            and path == "missing"
        ):
            triggered = True
            original_mkdir(
                path,
                mode,
                dir_fd=dir_fd,
            )

        return original_mkdir(
            path,
            mode,
            dir_fd=dir_fd,
        )

    monkeypatch.setattr(
        publisher_module.os,
        "mkdir",
        racing_mkdir,
    )

    _assert_error(
        "STALE_PREVIEW",
        lambda: publish_edit_plan(
            plan
        ),
    )

    assert (
        tmp_path
        / "missing"
    ).is_dir()

    _assert_no_ep_edit_artifacts(
        tmp_path
    )


def test_secure_create_rolls_back_file_and_created_directories_on_later_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    existing = (
        tmp_path
        / "z.py"
    )
    existing.write_bytes(
        b"z = 1\n"
    )

    plan = plan_edit_text(
        tmp_path,
        (
            "FILE: a-missing/deep/new.txt\n"
            "EDIT: create-new\n"
            "MODE: CREATE\n"
            + "<" * 7
            + " CONTENT\n"
            + "created\n"
            + ">" * 7
            + " CONTENT\n"
            + "FILE: z.py\n"
            + "EDIT: update-z\n"
            + "<" * 7
            + " SEARCH\n"
            + "z = 1\n"
            + "=" * 7
            + "\n"
            + "z = 2\n"
            + ">" * 7
            + " REPLACE\n"
        ),
    )

    original_publish = (
        publisher_module
        ._publish_one
    )

    def failing_publish(
        state,
        staged,
    ):
        if (
            state.mutation.target
            == "z.py"
        ):
            raise OSError(
                "injected later publish failure"
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

    _assert_error(
        "APPLY_FAILED_ROLLED_BACK",
        lambda: publish_edit_plan(
            plan
        ),
    )

    assert not (
        tmp_path
        / "a-missing"
    ).exists()

    assert (
        existing.read_bytes()
        == b"z = 1\n"
    )

    _assert_no_ep_edit_artifacts(
        tmp_path
    )


def test_secure_create_post_verify_failure_rolls_back_created_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = plan_edit_text(
        tmp_path,
        (
            "FILE: missing/deep/new.txt\n"
            "EDIT: create-new\n"
            "MODE: CREATE\n"
            + "<" * 7
            + " CONTENT\n"
            + "created\n"
            + ">" * 7
            + " CONTENT\n"
        ),
    )

    def failing_verify(
        parent_descriptor,
        mutation,
    ) -> None:
        raise DeterministicEditError(
            "POST_APPLY_VERIFY_FAILED",
            "injected secure verification failure",
        )

    monkeypatch.setattr(
        publisher_module,
        "_verify_missing_parent_create",
        failing_verify,
    )

    _assert_error(
        "APPLY_FAILED_ROLLED_BACK",
        lambda: publish_edit_plan(
            plan
        ),
    )

    assert not (
        tmp_path
        / "missing"
    ).exists()

    _assert_no_ep_edit_artifacts(
        tmp_path
    )


def test_secure_final_target_race_preserves_foreign_state_and_reports_rollback_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = plan_edit_text(
        tmp_path,
        (
            "FILE: missing/deep/new.txt\n"
            "EDIT: create-new\n"
            "MODE: CREATE\n"
            + "<" * 7
            + " CONTENT\n"
            + "created\n"
            + ">" * 7
            + " CONTENT\n"
        ),
    )

    original_link = os.link
    triggered = False

    def racing_link(
        source,
        destination,
        *args,
        **kwargs,
    ):
        nonlocal triggered

        if (
            not triggered
            and destination == "new.txt"
        ):
            triggered = True

            descriptor = os.open(
                destination,
                (
                    os.O_WRONLY
                    | os.O_CREAT
                    | os.O_EXCL
                ),
                0o666,
                dir_fd=kwargs[
                    "dst_dir_fd"
                ],
            )

            try:
                os.write(
                    descriptor,
                    b"foreign\n",
                )
            finally:
                os.close(
                    descriptor
                )

        return original_link(
            source,
            destination,
            *args,
            **kwargs,
        )

    monkeypatch.setattr(
        publisher_module.os,
        "link",
        racing_link,
    )

    _assert_error(
        "ROLLBACK_FAILED",
        lambda: publish_edit_plan(
            plan
        ),
    )

    assert (
        tmp_path
        / "missing/deep/new.txt"
    ).read_bytes() == b"foreign\n"

    _assert_no_ep_edit_artifacts(
        tmp_path
    )
