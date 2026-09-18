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


def _read_secure_stage(
    candidate,
) -> bytes:
    assert (
        candidate.directory_descriptor
        is not None
    )
    assert candidate.name is not None

    descriptor = os.open(
        candidate.name,
        os.O_RDONLY,
        dir_fd=candidate.directory_descriptor,
    )

    try:
        chunks: list[bytes] = []

        while True:
            chunk = os.read(
                descriptor,
                65536,
            )

            if not chunk:
                break

            chunks.append(
                chunk
            )

        return b"".join(
            chunks
        )

    finally:
        os.close(
            descriptor
        )


def test_missing_parent_create_stages_in_deepest_existing_parent(
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
            "existing/missing/deep/new.txt"
        ),
    )
    mutation = plan.files[0]
    root_descriptor = (
        publisher_module
        ._open_root_directory(
            plan
        )
    )

    try:
        candidate = (
            publisher_module
            ._stage_missing_parent_create(
                root_descriptor,
                plan,
                mutation,
            )
        )

        assert candidate.path is None
        assert (
            candidate.directory_relative_path
            == "existing"
        )
        assert (
            candidate.directory_descriptor
            is not None
        )
        assert candidate.name is not None
        assert (
            _read_secure_stage(
                candidate
            )
            == mutation.after_bytes
        )
        assert not (
            existing
            / "missing"
        ).exists()

        assert (
            publisher_module
            ._cleanup_staged(
                {
                    mutation.target: (
                        candidate
                    )
                }
            )
            is None
        )

        assert (
            candidate
            .directory_descriptor
            is None
        )

    finally:
        os.close(
            root_descriptor
        )


def test_missing_parent_create_stages_at_root_when_prefix_is_empty(
    tmp_path: Path,
) -> None:
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

    try:
        candidate = (
            publisher_module
            ._stage_missing_parent_create(
                root_descriptor,
                plan,
                mutation,
            )
        )

        assert (
            candidate.directory_relative_path
            == "."
        )
        assert (
            _read_secure_stage(
                candidate
            )
            == mutation.after_bytes
        )

        assert (
            publisher_module
            ._cleanup_staged(
                {
                    mutation.target: (
                        candidate
                    )
                }
            )
            is None
        )

    finally:
        os.close(
            root_descriptor
        )


def test_existing_parent_replacement_is_rejected_before_secure_stage(
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
    mutation = plan.files[0]

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

    try:
        _assert_error(
            "STALE_PREVIEW",
            lambda: (
                publisher_module
                ._stage_missing_parent_create(
                    root_descriptor,
                    plan,
                    mutation,
                )
            ),
        )

        assert not list(
            existing.glob(
                ".ep-edit-stage-*"
            )
        )
        assert not (
            existing
            / "missing"
        ).exists()

    finally:
        os.close(
            root_descriptor
        )


def test_descriptor_relative_stage_cleanup_survives_parent_rename(
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
    mutation = plan.files[0]
    root_descriptor = (
        publisher_module
        ._open_root_directory(
            plan
        )
    )

    try:
        candidate = (
            publisher_module
            ._stage_missing_parent_create(
                root_descriptor,
                plan,
                mutation,
            )
        )
        stage_name = candidate.name

        moved = (
            tmp_path
            / "existing-moved"
        )
        existing.rename(
            moved
        )

        assert (
            publisher_module
            ._cleanup_staged(
                {
                    mutation.target: (
                        candidate
                    )
                }
            )
            is None
        )

        assert stage_name is not None
        assert not (
            moved
            / stage_name
        ).exists()
        assert (
            candidate
            .directory_descriptor
            is None
        )

    finally:
        os.close(
            root_descriptor
        )
