from __future__ import annotations

from pathlib import Path

import pytest

from ep_edit.planner import (
    FileMutationOperation,
    plan_edit_text,
)


pytestmark = pytest.mark.unit

_SEARCH_OPEN = "<" * 7 + " SEARCH"
_REPLACE_SEPARATOR = "=" * 7
_REPLACE_CLOSE = ">" * 7 + " REPLACE"


def test_generated_edit_ref_flows_into_plan(
    tmp_path: Path,
) -> None:
    target = (
        tmp_path
        / "src"
        / "a.py"
    )
    target.parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    target.write_text(
        "old_a()\n",
        encoding="utf-8",
    )

    plan = plan_edit_text(
        tmp_path,
        f"""

FILE: src/a.py
LABEL: update a

{_SEARCH_OPEN}
old_a()
{_REPLACE_SEPARATOR}
new_a()
{_REPLACE_CLOSE}
""",
    )

    assert len(
        plan.files
    ) == 1

    mutation = plan.files[0]

    assert (
        mutation.operation
        is FileMutationOperation.REPLACE
    )
    assert len(
        mutation.edit_refs
    ) == 1
    assert (
        mutation.edit_refs[0]
        .startswith(
            "e_"
        )
    )
    assert (
        target.read_text(
            encoding="utf-8"
        )
        == "old_a()\n"
    )
