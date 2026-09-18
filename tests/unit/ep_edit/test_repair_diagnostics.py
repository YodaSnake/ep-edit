from __future__ import annotations

import json
from io import StringIO
from pathlib import Path

import pytest

from ep_edit.cli import main
from ep_edit.errors import (
    EditPreflightError,
)
from ep_edit.planner import (
    plan_edit_text,
)


pytestmark = pytest.mark.unit


_SEARCH_OPEN = "<" * 7 + " SEARCH"
_REPLACE_SEPARATOR = "=" * 7
_REPLACE_CLOSE = ">" * 7 + " REPLACE"


def _spec(
    *,
    target: str,
    label: str,
    search: str,
    replace: str,
) -> str:
    return (
        f"FILE: {target}\n"
        f"LABEL: {label}\n\n"
        f"{_SEARCH_OPEN}\n"
        f"{search}"
        f"{_REPLACE_SEPARATOR}\n"
        f"{replace}"
        f"{_REPLACE_CLOSE}\n"
    )


def test_zero_match_reports_ranked_bounded_candidates(
    tmp_path: Path,
) -> None:
    target = tmp_path / "example.py"
    target.write_text(
        (
            "alpha()\n"
            "beta()\n"
            "gamma()\n"
            "omega()\n"
            "beta_extra()\n"
        ),
        encoding="utf-8",
    )

    with pytest.raises(
        EditPreflightError
    ) as raised:
        plan_edit_text(
            tmp_path,
            _spec(
                target="example.py",
                label="repair zero",
                search=(
                    "beta()\n"
                    "gamma_changed()\n"
                ),
                replace="replacement()\n",
            ),
        )

    diagnostic = (
        raised.value.diagnostics[0]
    )
    metadata = (
        diagnostic.repair_metadata
    )

    assert metadata is not None
    assert (
        metadata.kind
        == "ZERO_MATCH_SIMILARITY"
    )
    assert (
        metadata.guidance
        == (
            "Use the smallest exact SEARCH block "
            "that is unique in the declared target."
        )
    )
    assert len(
        metadata.candidates
    ) == 3

    best = metadata.candidates[0]

    assert (
        best.start_line,
        best.end_line,
    ) == (2, 3)
    assert (
        best.similarity_basis_points
        is not None
    )
    assert (
        best.similarity_basis_points
        > 5000
    )
    assert best.excerpt == (
        "beta()",
        "gamma()",
    )
    assert metadata.total_candidate_count == 4
    assert metadata.candidates_truncated is True


def test_multiple_match_reports_all_exact_ranges(
    tmp_path: Path,
) -> None:
    target = tmp_path / "example.py"
    target.write_text(
        (
            "same()\n"
            "other()\n"
            "same()\n"
        ),
        encoding="utf-8",
    )

    with pytest.raises(
        EditPreflightError
    ) as raised:
        plan_edit_text(
            tmp_path,
            _spec(
                target="example.py",
                label="repair multiple",
                search="same()\n",
                replace="new()\n",
            ),
        )

    metadata = (
        raised.value
        .diagnostics[0]
        .repair_metadata
    )

    assert metadata is not None
    assert (
        metadata.kind
        == "MULTIPLE_MATCH_EXACT_RANGES"
    )
    assert [
        (
            candidate.start_line,
            candidate.end_line,
        )
        for candidate
        in metadata.candidates
    ] == [
        (1, 1),
        (3, 3),
    ]
    assert all(
        candidate.similarity_basis_points
        is None
        for candidate
        in metadata.candidates
    )
    assert metadata.total_candidate_count == 2
    assert metadata.candidates_truncated is False


def test_multiple_match_ranges_are_bounded(
    tmp_path: Path,
) -> None:
    target = tmp_path / "example.py"
    target.write_text(
        "same()\n" * 25,
        encoding="utf-8",
    )

    with pytest.raises(
        EditPreflightError
    ) as raised:
        plan_edit_text(
            tmp_path,
            _spec(
                target="example.py",
                label="many matches",
                search="same()\n",
                replace="new()\n",
            ),
        )

    metadata = (
        raised.value
        .diagnostics[0]
        .repair_metadata
    )

    assert metadata is not None
    assert metadata.total_candidate_count == 25
    assert metadata.candidates_truncated is True
    assert len(metadata.candidates) == 20
    assert (
        metadata.candidates[0].start_line,
        metadata.candidates[-1].start_line,
    ) == (1, 20)


def test_cli_emits_deterministic_repair_json(
    tmp_path: Path,
) -> None:
    target = tmp_path / "example.py"
    target.write_text(
        (
            "alpha()\n"
            "same()\n"
            "same()\n"
        ),
        encoding="utf-8",
    )

    specification_path = (
        tmp_path / "edits.txt"
    )

    specification_path.write_text(
        (

            "FILE: example.py\n"
            "LABEL: zero problem\n\n"
            f"{_SEARCH_OPEN}\n"
            "missing()\n"
            f"{_REPLACE_SEPARATOR}\n"
            "replacement_zero()\n"
            f"{_REPLACE_CLOSE}\n\n"
            "FILE: example.py\n"
            "LABEL: multiple problem\n\n"
            f"{_SEARCH_OPEN}\n"
            "same()\n"
            f"{_REPLACE_SEPARATOR}\n"
            "replacement_multiple()\n"
            f"{_REPLACE_CLOSE}\n"
        ),
        encoding="utf-8",
    )

    stdout = StringIO()
    stderr = StringIO()

    result = main(
        [
            "check",
            "--root",
            str(tmp_path),
            str(specification_path),
        ],
        stdout=stdout,
        stderr=stderr,
    )

    assert result == 1
    assert stdout.getvalue() == ""

    rendered = stderr.getvalue()

    assert (
        "Guidance: Use the smallest exact "
        "SEARCH block that is unique "
        "in the declared target."
        in rendered
    )
    assert "Candidate 1: lines " in rendered

    repair_lines = [
        line
        for line in rendered.splitlines()
        if line.startswith(
            "REPAIR_JSON: "
        )
    ]

    assert len(repair_lines) == 1

    payload = json.loads(
        repair_lines[0].partition(
            ": "
        )[2]
    )

    assert payload[
        "schema"
    ] == "ep-edit-repair-v1"
    assert payload[
        "error_count"
    ] == 2

    errors_by_code = {
        item["code"]: item
        for item in payload["errors"]
    }

    zero = errors_by_code[
        "SEARCH_ZERO_MATCH"
    ]
    multiple = errors_by_code[
        "SEARCH_MULTIPLE_MATCH"
    ]

    assert zero[
        "repair"
    ][
        "kind"
    ] == "ZERO_MATCH_SIMILARITY"
    assert zero[
        "repair"
    ][
        "total_candidate_count"
    ] == 3
    assert zero[
        "repair"
    ][
        "candidates_truncated"
    ] is False
    assert len(
        zero[
            "repair"
        ][
            "candidates"
        ]
    ) == 3

    assert multiple[
        "repair"
    ][
        "kind"
    ] == "MULTIPLE_MATCH_EXACT_RANGES"
    assert multiple[
        "repair"
    ][
        "total_candidate_count"
    ] == 2
    assert multiple[
        "repair"
    ][
        "candidates_truncated"
    ] is False
    assert [
        (
            candidate[
                "start_line"
            ],
            candidate[
                "end_line"
            ],
        )
        for candidate
        in multiple[
            "repair"
        ][
            "candidates"
        ]
    ] == [
        (2, 2),
        (3, 3),
    ]


def test_cli_candidate_excerpt_escapes_terminal_controls(
    tmp_path: Path,
) -> None:
    target = tmp_path / "example.py"
    target.write_text(
        "value = \"\x1b[31mred\"\n",
        encoding="utf-8",
    )

    specification_path = (
        tmp_path / "edits.txt"
    )
    specification_path.write_text(
        _spec(
            target="example.py",
            label="terminal safe",
            search=(
                "value = \"\x1b[32mred\"\n"
            ),
            replace="replacement()\n",
        ),
        encoding="utf-8",
    )

    stdout = StringIO()
    stderr = StringIO()

    result = main(
        [
            "check",
            "--root",
            str(tmp_path),
            str(specification_path),
        ],
        stdout=stdout,
        stderr=stderr,
    )

    assert result == 1
    assert stdout.getvalue() == ""

    rendered = stderr.getvalue()

    assert "\x1b" not in rendered
    assert "\\u001b[31mred" in rendered


def test_similarity_candidate_never_authorizes_apply(
    tmp_path: Path,
) -> None:
    target = tmp_path / "example.py"
    target.write_text(
        "value = 10\n",
        encoding="utf-8",
    )

    specification_path = (
        tmp_path / "edits.txt"
    )
    specification_path.write_text(
        _spec(
            target="example.py",
            label="near but not exact",
            search="value = 11\n",
            replace="value = 12\n",
        ),
        encoding="utf-8",
    )

    def fail_if_called(
        _prompt: str,
    ) -> str:
        raise AssertionError(
            "similarity candidate must not "
            "authorize approval"
        )

    stdout = StringIO()
    stderr = StringIO()

    result = main(
        [
            "apply",
            "--root",
            str(tmp_path),
            str(specification_path),
        ],
        stdout=stdout,
        stderr=stderr,
        approval_reader=fail_if_called,
    )

    assert result == 1
    assert (
        "SEARCH_ZERO_MATCH"
        in stderr.getvalue()
    )
    assert (
        "similarity="
        in stderr.getvalue()
    )
    assert target.read_text(
        encoding="utf-8"
    ) == "value = 10\n"


def test_candidate_excerpt_is_bounded(
    tmp_path: Path,
) -> None:
    long_line = (
        "x" * 400
    )
    target = tmp_path / "example.py"
    target.write_text(
        "\n".join(
            [
                long_line,
                "two",
                "three",
                "four",
                "five",
                "six",
                "seven",
                "eight",
                "nine",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(
        EditPreflightError
    ) as raised:
        plan_edit_text(
            tmp_path,
            _spec(
                target="example.py",
                label="bounded",
                search=(
                    "y" * 400
                    + "\n"
                    + "two\n"
                    + "three\n"
                    + "four\n"
                    + "five\n"
                    + "six\n"
                    + "seven\n"
                    + "eight\n"
                    + "changed-nine\n"
                ),
                replace="replacement()\n",
            ),
        )

    best = (
        raised.value
        .diagnostics[0]
        .repair_metadata
        .candidates[0]
    )

    assert len(
        best.excerpt
    ) == 8
    assert best.excerpt_truncated is True
    assert len(
        best.excerpt[0]
    ) == 240
    assert best.excerpt[0].endswith(
        "..."
    )
