from __future__ import annotations

import os
from pathlib import Path

import pytest

import ep_edit.publisher as publisher_module
from ep_edit.errors import DeterministicEditError
from ep_edit.planner import plan_edit_text
from ep_edit.publisher import publish_edit_plan


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


def _install_create_race(
    monkeypatch: pytest.MonkeyPatch,
    *,
    raced_target_name: str,
    concurrent_bytes: bytes,
) -> None:
    original_link = os.link
    triggered = False

    def racing_link(
        source,
        destination,
        *args,
        **kwargs,
    ):
        nonlocal triggered

        destination_path = Path(
            destination
        )

        if (
            not triggered
            and destination_path.name
            == raced_target_name
        ):
            triggered = True
            destination_path.write_bytes(
                concurrent_bytes
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


def test_create_race_before_any_publication_is_stale_not_rollback_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = plan_edit_text(
        tmp_path,
        """FILE: new.txt
EDIT: create-new
MODE: CREATE
<<<<<<< CONTENT
planned
>>>>>>> CONTENT
""",
    )

    _install_create_race(
        monkeypatch,
        raced_target_name="new.txt",
        concurrent_bytes=b"concurrent\n",
    )

    _assert_error(
        "STALE_PREVIEW",
        lambda: publish_edit_plan(
            plan
        ),
    )

    assert (
        tmp_path
        / "new.txt"
    ).read_bytes() == b"concurrent\n"

    assert list(
        tmp_path.rglob(
            ".ep-edit-*"
        )
    ) == []


def test_create_race_after_prior_publish_rolls_back_only_cli_owned_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = _write(
        tmp_path,
        "a.py",
        b"a = 1\n",
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

FILE: z.txt
EDIT: create-z
MODE: CREATE
<<<<<<< CONTENT
planned
>>>>>>> CONTENT
""",
    )

    _install_create_race(
        monkeypatch,
        raced_target_name="z.txt",
        concurrent_bytes=b"concurrent\n",
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
        tmp_path
        / "z.txt"
    ).read_bytes() == b"concurrent\n"

    assert list(
        tmp_path.rglob(
            ".ep-edit-*"
        )
    ) == []
