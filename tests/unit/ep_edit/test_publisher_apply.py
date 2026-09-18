from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

import ep_edit.publisher as publisher_module
from ep_edit.errors import DeterministicEditError
from ep_edit.planner import plan_edit_text as _plan_edit_text
from ep_edit.publisher import publish_edit_plan


pytestmark = pytest.mark.unit


def _current_spec(
    text: str,
) -> str:
    return text


def plan_edit_text(
    root: Path,
    text: str,
):
    return _plan_edit_text(
        root,
        _current_spec(text),
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


def test_replace_publishes_exact_bytes_and_preserves_mode(
    tmp_path: Path,
) -> None:
    target = _write(
        tmp_path,
        "script.py",
        b"value = 1\n",
    )
    target.chmod(
        0o755
    )

    plan = plan_edit_text(
        tmp_path,
        """FILE: script.py
LABEL: update-value
<<<<<<< SEARCH
value = 1
=======
value = 2
>>>>>>> REPLACE
""",
    )

    result = publish_edit_plan(
        plan
    )

    assert (
        target.read_bytes()
        == b"value = 2\n"
    )
    assert (
        stat.S_IMODE(
            target.stat().st_mode
        )
        == 0o755
    )
    assert (
        result.targets[0].final_sha256
        == plan.files[0].after_sha256
    )


def test_create_publishes_exact_candidate(
    tmp_path: Path,
) -> None:
    (tmp_path / "src").mkdir()

    plan = plan_edit_text(
        tmp_path,
        """FILE: src/new.py
LABEL: create-new
MODE: CREATE
FINAL_NEWLINE: NO
<<<<<<< CONTENT
value = 1
>>>>>>> CONTENT
""",
    )

    result = publish_edit_plan(
        plan
    )
    target = (
        tmp_path
        / "src/new.py"
    )

    assert (
        target.read_bytes()
        == b"value = 1"
    )
    assert (
        result.targets[0].final_exists
        is True
    )


def test_url_uri_partial_replace_publishes_exact_bytes(
    tmp_path: Path,
) -> None:
    target = _write(
        tmp_path,
        "links.txt",
        (
            b'url = "http://example.invalid/a:b'
            b'?x=1&y=2#old"\n'
        ),
    )

    search_open = "<" * 7 + " SEARCH"
    replace_separator = "=" * 7
    replace_close = ">" * 7 + " REPLACE"

    plan = plan_edit_text(
        tmp_path,
        (
            "FILE: links.txt\n"
            "LABEL: replace URL literal\n\n"
            f"{search_open}\n"
            'url = "http://example.invalid/a:b'
            '?x=1&y=2#old"\n'
            f"{replace_separator}\n"
            'url = "https://example.invalid/a:b'
            '?x=1&y=2#new"\n'
            f"{replace_close}\n"
        ),
    )

    result = publish_edit_plan(
        plan
    )

    assert (
        target.read_bytes()
        == (
            b'url = "https://example.invalid/a:b'
            b'?x=1&y=2#new"\n'
        )
    )
    assert (
        result.targets[0].final_sha256
        == plan.files[0].after_sha256
    )


def test_url_uri_whole_file_content_publishes_exact_bytes(
    tmp_path: Path,
) -> None:
    (tmp_path / "generated").mkdir()

    content_open = "<" * 7 + " CONTENT"
    content_close = ">" * 7 + " CONTENT"

    expected = (
        b"http://example.invalid/path\n"
        b"https://example.invalid/a:b/c?x=1&y=2#fragment\n"
        b"urn:test:a6-url-compat\n"
        b"mailto:test@example.invalid\n"
    )

    plan = plan_edit_text(
        tmp_path,
        (
            "FILE: generated/links.txt\n"
            "LABEL: create URL URI literal file\n"
            "MODE: CREATE\n\n"
            f"{content_open}\n"
            "http://example.invalid/path\n"
            "https://example.invalid/a:b/c?x=1&y=2#fragment\n"
            "urn:test:a6-url-compat\n"
            "mailto:test@example.invalid\n"
            f"{content_close}\n"
        ),
    )

    result = publish_edit_plan(
        plan
    )
    target = (
        tmp_path
        / "generated"
        / "links.txt"
    )

    assert target.read_bytes() == expected
    assert (
        result.targets[0].final_sha256
        == plan.files[0].after_sha256
    )


def test_create_final_target_is_regular_single_link(
    tmp_path: Path,
) -> None:
    (tmp_path / "src").mkdir()

    plan = plan_edit_text(
        tmp_path,
        """FILE: src/new.txt
LABEL: create-new
MODE: CREATE
<<<<<<< CONTENT
created
>>>>>>> CONTENT
""",
    )

    publish_edit_plan(
        plan
    )

    item_stat = (
        tmp_path
        / "src/new.txt"
    ).lstat()

    assert stat.S_ISREG(
        item_stat.st_mode
    )
    assert item_stat.st_nlink == 1


def test_delete_removes_exact_target(
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
LABEL: remove-obsolete
MODE: DELETE
""",
    )

    result = publish_edit_plan(
        plan
    )

    assert not target.exists()
    assert (
        result.targets[0].final_exists
        is False
    )
    assert (
        result.targets[0].final_sha256
        is None
    )


def test_mixed_multifile_publication_reaches_exact_after_state(
    tmp_path: Path,
) -> None:
    (tmp_path / "src").mkdir()
    _write(
        tmp_path,
        "src/a.py",
        b"a = 1\n",
    )
    _write(
        tmp_path,
        "src/obsolete.txt",
        b"obsolete\n",
    )

    plan = plan_edit_text(
        tmp_path,
        """FILE: src/a.py
LABEL: update-a
<<<<<<< SEARCH
a = 1
=======
a = 2
>>>>>>> REPLACE

FILE: src/new.py
LABEL: create-new
MODE: CREATE
<<<<<<< CONTENT
created = True
>>>>>>> CONTENT

FILE: src/obsolete.txt
LABEL: remove-old
MODE: DELETE
""",
    )

    result = publish_edit_plan(
        plan
    )

    assert (
        tmp_path
        / "src/a.py"
    ).read_bytes() == b"a = 2\n"

    assert (
        tmp_path
        / "src/new.py"
    ).read_bytes() == b"created = True\n"

    assert not (
        tmp_path
        / "src/obsolete.txt"
    ).exists()

    assert [
        item.target
        for item in result.targets
    ] == [
        mutation.target
        for mutation in plan.files
    ]


def test_representation_only_change_is_published_exactly(
    tmp_path: Path,
) -> None:
    target = _write(
        tmp_path,
        "example.txt",
        b"same\r\n",
    )

    plan = plan_edit_text(
        tmp_path,
        """FILE: example.txt
LABEL: normalize-newline
MODE: REPLACE_FILE
NEWLINE: LF
<<<<<<< CONTENT
same
>>>>>>> CONTENT
""",
    )

    publish_edit_plan(
        plan
    )

    assert (
        target.read_bytes()
        == b"same\n"
    )


def test_bom_and_final_newline_candidate_is_published_byte_exact(
    tmp_path: Path,
) -> None:
    target = _write(
        tmp_path,
        "example.txt",
        b"old\n",
    )

    plan = plan_edit_text(
        tmp_path,
        """FILE: example.txt
LABEL: replace-file
MODE: REPLACE_FILE
BOM: YES
FINAL_NEWLINE: NO
NEWLINE: LF
<<<<<<< CONTENT
new
>>>>>>> CONTENT
""",
    )

    publish_edit_plan(
        plan
    )

    assert (
        target.read_bytes()
        == plan.files[0].after_bytes
    )


def test_stale_file_backed_specification_prevents_publication(
    tmp_path: Path,
) -> None:
    target = _write(
        tmp_path,
        "example.py",
        b"value = 1\n",
    )
    specification = """FILE: example.py
LABEL: update
<<<<<<< SEARCH
value = 1
=======
value = 2
>>>>>>> REPLACE
"""
    spec_path = (
        tmp_path
        / "edits.txt"
    )
    spec_path.write_bytes(
        _current_spec(
            specification
        ).encode(
            "utf-8"
        )
    )

    plan = plan_edit_text(
        tmp_path,
        specification,
    )

    spec_path.write_bytes(
        _current_spec(
            specification.replace(
                "value = 2",
                "value = 3",
            )
        ).encode(
            "utf-8"
        )
    )

    _assert_error(
        "STALE_SPECIFICATION",
        lambda: publish_edit_plan(
            plan,
            specification_path=spec_path,
        ),
    )

    assert (
        target.read_bytes()
        == b"value = 1\n"
    )


def test_each_target_is_revalidated_globally_and_before_publish(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write(
        tmp_path,
        "a.py",
        b"a = 1\n",
    )
    _write(
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

    original = (
        publisher_module
        .revalidate_target_mutation
    )
    calls: list[str] = []

    def recording_revalidation(
        root: Path,
        mutation,
    ):
        calls.append(
            mutation.target
        )
        return original(
            root,
            mutation,
        )

    monkeypatch.setattr(
        publisher_module,
        "revalidate_target_mutation",
        recording_revalidation,
    )

    publish_edit_plan(
        plan
    )

    assert calls == [
        "a.py",
        "b.py",
        "a.py",
        "b.py",
    ]


def test_all_candidates_stage_before_first_publish(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write(
        tmp_path,
        "a.py",
        b"a = 1\n",
    )
    _write(
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
    original_publish = (
        publisher_module
        ._publish_one
    )
    events: list[str] = []

    def recording_stage(
        root: Path,
        mutation,
    ):
        events.append(
            f"stage:{mutation.target}"
        )
        return original_stage(
            root,
            mutation,
        )

    def recording_publish(
        state,
        staged,
    ):
        events.append(
            f"publish:{state.mutation.target}"
        )
        return original_publish(
            state,
            staged,
        )

    monkeypatch.setattr(
        publisher_module,
        "_stage_candidate",
        recording_stage,
    )
    monkeypatch.setattr(
        publisher_module,
        "_publish_one",
        recording_publish,
    )

    publish_edit_plan(
        plan
    )

    assert events == [
        "stage:a.py",
        "stage:b.py",
        "publish:a.py",
        "publish:b.py",
    ]


def test_success_leaves_no_cli_owned_ephemeral_files(
    tmp_path: Path,
) -> None:
    _write(
        tmp_path,
        "a.py",
        b"a = 1\n",
    )
    _write(
        tmp_path,
        "obsolete.txt",
        b"old\n",
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

FILE: new.txt
LABEL: create-new
MODE: CREATE
<<<<<<< CONTENT
new
>>>>>>> CONTENT

FILE: obsolete.txt
LABEL: remove-old
MODE: DELETE
""",
    )

    publish_edit_plan(
        plan
    )

    leftovers = [
        item
        for item in tmp_path.rglob(
            ".ep-edit-*"
        )
    ]

    assert leftovers == []


def test_publication_does_not_require_git_repository(
    tmp_path: Path,
) -> None:
    target = _write(
        tmp_path,
        "plain.txt",
        b"old\n",
    )

    assert not (
        tmp_path
        / ".git"
    ).exists()

    plan = plan_edit_text(
        tmp_path,
        """FILE: plain.txt
LABEL: update
<<<<<<< SEARCH
old
=======
new
>>>>>>> REPLACE
""",
    )

    publish_edit_plan(
        plan
    )

    assert (
        target.read_bytes()
        == b"new\n"
    )
