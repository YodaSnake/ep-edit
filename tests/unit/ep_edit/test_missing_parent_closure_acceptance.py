from __future__ import annotations

import os
from io import StringIO
from pathlib import Path

import pytest

import ep_edit.publisher as publisher_module
from ep_edit.cli import main
from ep_edit.planner import plan_edit_text
from ep_edit.publisher import publish_edit_plan


pytestmark = pytest.mark.unit


def _create_block(
    target: str,
    content: str,
) -> str:
    return (
        f"FILE: {target}\n"
        "MODE: CREATE\n"
        + "<" * 7
        + " CONTENT\n"
        + content
        + ">" * 7
        + " CONTENT\n"
    )


def _replace_block(
    target: str,
    before: str,
    after: str,
) -> str:
    return (
        f"FILE: {target}\n"
        + "<" * 7
        + " SEARCH\n"
        + before
        + "=" * 7
        + "\n"
        + after
        + ">" * 7
        + " REPLACE\n"
    )


def _assert_no_ep_edit_artifacts(
    root: Path,
) -> None:
    assert list(
        root.rglob(
            ".ep-edit-*"
        )
    ) == []


def test_shared_missing_parent_chain_is_established_once_and_serves_both_creates(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = plan_edit_text(
        tmp_path,
        (
            _create_block(
                "missing/shared/a.txt",
                "a\n",
            )
            + _create_block(
                "missing/shared/b.txt",
                "b\n",
            )
        ),
    )

    original_mkdir = os.mkdir
    mkdir_calls: list[str] = []

    def recording_mkdir(
        path,
        mode=0o777,
        *,
        dir_fd=None,
    ):
        mkdir_calls.append(
            path
        )
        return original_mkdir(
            path,
            mode,
            dir_fd=dir_fd,
        )

    monkeypatch.setattr(
        publisher_module.os,
        "mkdir",
        recording_mkdir,
    )

    result = publish_edit_plan(
        plan
    )

    assert mkdir_calls == [
        "missing",
        "shared",
    ]

    assert (
        tmp_path
        / "missing/shared/a.txt"
    ).read_bytes() == b"a\n"

    assert (
        tmp_path
        / "missing/shared/b.txt"
    ).read_bytes() == b"b\n"

    assert [
        target.target
        for target in result.targets
    ] == [
        "missing/shared/a.txt",
        "missing/shared/b.txt",
    ]

    _assert_no_ep_edit_artifacts(
        tmp_path
    )


def test_missing_parent_create_and_replace_reach_exact_mixed_final_state(
    tmp_path: Path,
) -> None:
    existing = (
        tmp_path
        / "existing.txt"
    )
    existing.write_bytes(
        b"before\n"
    )

    plan = plan_edit_text(
        tmp_path,
        (
            _create_block(
                "missing/deep/new.txt",
                "created\n",
            )
            + _replace_block(
                "existing.txt",
                "before\n",
                "after\n",
            )
        ),
    )

    result = publish_edit_plan(
        plan
    )

    assert (
        tmp_path
        / "missing/deep/new.txt"
    ).read_bytes() == b"created\n"

    assert (
        existing.read_bytes()
        == b"after\n"
    )

    assert [
        target.target
        for target in result.targets
    ] == [
        "existing.txt",
        "missing/deep/new.txt",
    ]

    _assert_no_ep_edit_artifacts(
        tmp_path
    )


def test_cli_apply_missing_parent_create_reaches_publication(
    tmp_path: Path,
) -> None:
    specification = (
        tmp_path
        / "edit-spec.txt"
    )
    specification.write_bytes(
        (
            _create_block(
                "missing/from-cli/new.txt",
                "cli-created\n",
            )
        ).encode(
            "utf-8"
        )
    )

    stdout = StringIO()
    stderr = StringIO()

    result = main(
        [
            "apply",
            "--root",
            str(
                tmp_path
            ),
            str(
                specification
            ),
        ],
        stdout=stdout,
        stderr=stderr,
        approval_reader=(
            lambda _prompt: "y"
        ),
    )

    assert result == 0

    assert (
        tmp_path
        / "missing/from-cli/new.txt"
    ).read_bytes() == b"cli-created\n"

    assert (
        "APPLIED: 1 target(s)."
        in stdout.getvalue()
    )
    assert stderr.getvalue() == ""

    _assert_no_ep_edit_artifacts(
        tmp_path
    )
