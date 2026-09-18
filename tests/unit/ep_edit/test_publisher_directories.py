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


def test_establishment_tracks_only_apply_created_chain(
    tmp_path: Path,
) -> None:
    preexisting = (
        tmp_path
        / "existing"
    )
    preexisting.mkdir()

    plan = plan_edit_text(
        tmp_path,
        _create_spec(
            "existing/missing/deep/new.txt"
        ),
    )
    root_descriptor = (
        publisher_module
        ._open_root_directory(
            plan
        )
    )
    created = []

    try:
        (
            publisher_module
            ._establish_create_parent_directories(
                root_descriptor,
                plan,
                created,
            )
        )

        assert [
            directory.relative_path
            for directory in created
        ] == [
            "existing/missing",
            "existing/missing/deep",
        ]
        assert (
            preexisting
            / "missing/deep"
        ).is_dir()

        assert (
            publisher_module
            ._cleanup_created_directories(
                root_descriptor,
                plan,
                created,
            )
            is None
        )

        assert preexisting.is_dir()
        assert not (
            preexisting
            / "missing"
        ).exists()

    finally:
        os.close(
            root_descriptor
        )


def test_existing_parent_directory_replacement_fails_before_mkdir(
    tmp_path: Path,
) -> None:
    existing = (
        tmp_path
        / "existing"
    )
    existing.mkdir()

    plan = plan_edit_text(
        tmp_path,
        _create_spec(
            "existing/missing/new.txt"
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

    root_descriptor = (
        publisher_module
        ._open_root_directory(
            plan
        )
    )
    created = []

    try:
        _assert_error(
            "STALE_PREVIEW",
            lambda: (
                publisher_module
                ._establish_create_parent_directories(
                    root_descriptor,
                    plan,
                    created,
                )
            ),
        )

        assert created == []
        assert not (
            existing
            / "missing"
        ).exists()

    finally:
        os.close(
            root_descriptor
        )


def test_existing_parent_symlink_swap_never_redirects_mkdir(
    tmp_path: Path,
) -> None:
    existing = (
        tmp_path
        / "existing"
    )
    existing.mkdir()

    plan = plan_edit_text(
        tmp_path,
        _create_spec(
            "existing/missing/new.txt"
        ),
    )

    original = (
        tmp_path
        / "existing-original"
    )
    existing.rename(
        original
    )
    outside = (
        tmp_path
        / "outside"
    )
    outside.mkdir()

    try:
        existing.symlink_to(
            outside,
            target_is_directory=True,
        )
    except OSError:
        pytest.skip(
            "symbolic links are unavailable"
        )

    root_descriptor = (
        publisher_module
        ._open_root_directory(
            plan
        )
    )
    created = []

    try:
        _assert_error(
            "STALE_PREVIEW",
            lambda: (
                publisher_module
                ._establish_create_parent_directories(
                    root_descriptor,
                    plan,
                    created,
                )
            ),
        )

        assert created == []
        assert not (
            outside
            / "missing"
        ).exists()

    finally:
        os.close(
            root_descriptor
        )


def test_mkdir_race_is_stale_and_foreign_directory_is_not_owned(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = plan_edit_text(
        tmp_path,
        _create_spec(
            "missing/new.txt"
        ),
    )
    root_descriptor = (
        publisher_module
        ._open_root_directory(
            plan
        )
    )
    created = []
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

    try:
        _assert_error(
            "STALE_PREVIEW",
            lambda: (
                publisher_module
                ._establish_create_parent_directories(
                    root_descriptor,
                    plan,
                    created,
                )
            ),
        )

        assert created == []
        assert (
            tmp_path
            / "missing"
        ).is_dir()

    finally:
        os.close(
            root_descriptor
        )


def test_foreign_content_prevents_created_directory_cleanup(
    tmp_path: Path,
) -> None:
    plan = plan_edit_text(
        tmp_path,
        _create_spec(
            "missing/deep/new.txt"
        ),
    )
    root_descriptor = (
        publisher_module
        ._open_root_directory(
            plan
        )
    )
    created = []

    try:
        (
            publisher_module
            ._establish_create_parent_directories(
                root_descriptor,
                plan,
                created,
            )
        )

        (
            tmp_path
            / "missing/deep/foreign.txt"
        ).write_bytes(
            b"foreign\n"
        )

        error = (
            publisher_module
            ._cleanup_created_directories(
                root_descriptor,
                plan,
                created,
            )
        )

        assert error is not None
        assert (
            tmp_path
            / "missing/deep/foreign.txt"
        ).read_bytes() == b"foreign\n"
        assert (
            tmp_path
            / "missing/deep"
        ).is_dir()

    finally:
        os.close(
            root_descriptor
        )


def test_identity_replacement_is_never_removed_as_apply_owned(
    tmp_path: Path,
) -> None:
    plan = plan_edit_text(
        tmp_path,
        _create_spec(
            "missing/deep/new.txt"
        ),
    )
    root_descriptor = (
        publisher_module
        ._open_root_directory(
            plan
        )
    )
    created = []

    try:
        (
            publisher_module
            ._establish_create_parent_directories(
                root_descriptor,
                plan,
                created,
            )
        )

        owned_deep = (
            tmp_path
            / "missing/deep"
        )
        displaced = (
            tmp_path
            / "missing/displaced"
        )
        owned_deep.rename(
            displaced
        )
        owned_deep.mkdir()

        error = (
            publisher_module
            ._cleanup_created_directories(
                root_descriptor,
                plan,
                created,
            )
        )

        assert error is not None
        assert owned_deep.is_dir()
        assert displaced.is_dir()

    finally:
        os.close(
            root_descriptor
        )


def test_root_replacement_is_rejected_when_opening_publication_anchor(
    tmp_path: Path,
) -> None:
    plan = plan_edit_text(
        tmp_path,
        _create_spec(
            "missing/new.txt"
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
        lambda: (
            publisher_module
            ._open_root_directory(
                plan
            )
        ),
    )

    assert not (
        tmp_path
        / "missing"
    ).exists()


@pytest.mark.parametrize(
    "missing_flag",
    [
        "O_DIRECTORY",
        "O_NOFOLLOW",
    ],
)
def test_missing_parent_publication_fails_closed_without_required_directory_flags(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    missing_flag: str,
) -> None:
    plan = plan_edit_text(
        tmp_path,
        _create_spec(
            "missing/deep/new.txt"
        ),
    )
    monkeypatch.delattr(
        publisher_module.os,
        missing_flag,
    )

    error = _assert_error(
        "APPLY_FAILED_ROLLED_BACK",
        lambda: (
            publisher_module
            .publish_edit_plan(
                plan
            )
        ),
    )

    assert (
        "platform does not provide required "
        "no-follow directory publication support"
        in error.message
    )
    assert not (
        tmp_path
        / "missing"
    ).exists()
    assert list(
        tmp_path.rglob(
            ".ep-edit-*"
        )
    ) == []
