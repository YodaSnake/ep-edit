from __future__ import annotations

import os
from pathlib import Path

import pytest

import ep_edit.publisher as publisher_module
from ep_edit.errors import DeterministicEditError
from ep_edit.planner import plan_edit_text


pytestmark = pytest.mark.unit


def _create_spec(
    target: str,
) -> str:
    return (
        f"FILE: {target}\n"
        "EDIT: create-new\n"
        "MODE: CREATE\n"
        + "<" * 7
        + " CONTENT\n"
        + "created\n"
        + ">" * 7
        + " CONTENT\n"
    )


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


def _prepare_secure_create(
    tmp_path: Path,
):
    plan = plan_edit_text(
        tmp_path,
        _create_spec(
            "missing/deep/new.txt"
        ),
    )
    mutation = plan.files[0]
    root_descriptor = (
        publisher_module
        ._open_root_directory(
            plan
        )
    )
    staged = (
        publisher_module
        ._stage_missing_parent_create(
            root_descriptor,
            plan,
            mutation,
        )
    )
    created = []

    (
        publisher_module
        ._establish_create_parent_directories(
            root_descriptor,
            plan,
            created,
        )
    )

    parent_descriptor = (
        publisher_module
        ._open_missing_parent_create_target_parent(
            root_descriptor,
            plan,
            mutation,
            created,
        )
    )

    state = (
        publisher_module
        ._PublishedMutationState(
            mutation=mutation,
            target_path=(
                tmp_path
                / mutation.target
            ),
        )
    )

    return (
        plan,
        mutation,
        root_descriptor,
        staged,
        created,
        parent_descriptor,
        state,
    )


def _cleanup_secure_create(
    root_descriptor: int,
    plan,
    staged,
    created,
    parent_descriptor: int,
) -> None:
    os.close(
        parent_descriptor
    )

    stage_error = (
        publisher_module
        ._cleanup_staged(
            {
                staged.mutation.target: (
                    staged
                )
            }
        )
    )
    assert stage_error is None

    directory_error = (
        publisher_module
        ._cleanup_created_directories(
            root_descriptor,
            plan,
            created,
        )
    )
    assert directory_error is None

    os.close(
        root_descriptor
    )


def test_secure_create_publication_verifies_and_rolls_back_exactly(
    tmp_path: Path,
) -> None:
    (
        plan,
        mutation,
        root_descriptor,
        staged,
        created,
        parent_descriptor,
        state,
    ) = _prepare_secure_create(
        tmp_path
    )

    try:
        (
            publisher_module
            ._require_secure_create_target_absent(
                parent_descriptor,
                mutation,
            )
        )

        (
            publisher_module
            ._publish_missing_parent_create(
                parent_descriptor,
                state,
                staged,
            )
        )

        assert state.after_published

        (
            publisher_module
            ._verify_missing_parent_create(
                parent_descriptor,
                mutation,
            )
        )

        assert (
            tmp_path
            / "missing/deep/new.txt"
        ).read_bytes() == b"created\n"

        (
            publisher_module
            ._rollback_missing_parent_create(
                parent_descriptor,
                state,
            )
        )

        assert not state.after_published
        assert not (
            tmp_path
            / "missing/deep/new.txt"
        ).exists()

    finally:
        _cleanup_secure_create(
            root_descriptor,
            plan,
            staged,
            created,
            parent_descriptor,
        )


def test_secure_create_target_appearance_is_stale_and_not_overwritten(
    tmp_path: Path,
) -> None:
    (
        plan,
        mutation,
        root_descriptor,
        staged,
        created,
        parent_descriptor,
        state,
    ) = _prepare_secure_create(
        tmp_path
    )

    target = (
        tmp_path
        / "missing/deep/new.txt"
    )
    target.write_bytes(
        b"foreign\n"
    )

    try:
        _assert_error(
            "STALE_PREVIEW",
            lambda: (
                publisher_module
                ._require_secure_create_target_absent(
                    parent_descriptor,
                    mutation,
                )
            ),
        )

        assert (
            target.read_bytes()
            == b"foreign\n"
        )
        assert not state.after_published

    finally:
        target.unlink()

        _cleanup_secure_create(
            root_descriptor,
            plan,
            staged,
            created,
            parent_descriptor,
        )


def test_secure_create_link_race_preserves_foreign_target(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (
        plan,
        mutation,
        root_descriptor,
        staged,
        created,
        parent_descriptor,
        state,
    ) = _prepare_secure_create(
        tmp_path
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

        if not triggered:
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

    try:
        _assert_error(
            "STALE_PREVIEW",
            lambda: (
                publisher_module
                ._publish_missing_parent_create(
                    parent_descriptor,
                    state,
                    staged,
                )
            ),
        )

        assert not state.after_published
        assert (
            tmp_path
            / "missing/deep/new.txt"
        ).read_bytes() == b"foreign\n"

    finally:
        (
            tmp_path
            / "missing/deep/new.txt"
        ).unlink()

        _cleanup_secure_create(
            root_descriptor,
            plan,
            staged,
            created,
            parent_descriptor,
        )


def test_secure_create_rollback_refuses_foreign_file_replacement(
    tmp_path: Path,
) -> None:
    (
        plan,
        mutation,
        root_descriptor,
        staged,
        created,
        parent_descriptor,
        state,
    ) = _prepare_secure_create(
        tmp_path
    )

    try:
        (
            publisher_module
            ._publish_missing_parent_create(
                parent_descriptor,
                state,
                staged,
            )
        )

        target = (
            tmp_path
            / "missing/deep/new.txt"
        )
        target.unlink()
        target.write_bytes(
            b"foreign\n"
        )

        with pytest.raises(
            RuntimeError
        ):
            (
                publisher_module
                ._rollback_missing_parent_create(
                    parent_descriptor,
                    state,
                )
            )

        assert (
            target.read_bytes()
            == b"foreign\n"
        )

        target.unlink()
        state.after_published = False

    finally:
        _cleanup_secure_create(
            root_descriptor,
            plan,
            staged,
            created,
            parent_descriptor,
        )
