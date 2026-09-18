from __future__ import annotations

from pathlib import Path

import pytest

from ep_edit.errors import DeterministicEditError
from ep_edit.planner import (
    EditPlan,
    FileMutation,
    FileMutationOperation,
    plan_edit_text,
)
from ep_edit.validators import (
    ValidationResult,
    ValidationStatus,
    validate_edit_plan,
)


pytestmark = pytest.mark.unit


def _mutation(
    target: str,
    after: bytes | None,
    *,
    after_exists: bool = True,
) -> FileMutation:
    return FileMutation(
        target=target,
        operation=(
            FileMutationOperation.REPLACE
            if after_exists
            else FileMutationOperation.DELETE
        ),
        before_exists=True,
        before_sha256="before",
        before_bytes=b"before",
        after_exists=after_exists,
        after_sha256=(
            "after"
            if after_exists
            else None
        ),
        after_bytes=after,
        newline_style=None,
        final_newline=False,
        edit_ids=("edit",),
        changed_ranges=(),
    )


def _plan(
    *mutations: FileMutation,
) -> EditPlan:
    return EditPlan(
        root=Path("/tmp"),
        input_fingerprint="fingerprint",
        files=mutations,
    )


def _assert_validation_failure(
    callable_,
) -> DeterministicEditError:
    with pytest.raises(
        DeterministicEditError
    ) as raised:
        callable_()

    assert (
        raised.value.code
        == "VALIDATION_FAILED"
    )

    return raised.value


def test_python_valid_candidate_passes() -> None:
    report = validate_edit_plan(
        _plan(
            _mutation(
                "src/example.py",
                b"value = 1\n",
            )
        )
    )

    assert report.results == (
        ValidationResult(
            target="src/example.py",
            validator="python",
            status=ValidationStatus.PASS,
            message="Python syntax valid",
        ),
    )
    assert report.passed_count == 1
    assert report.skipped_count == 0


def test_python_syntax_error_rejected() -> None:
    error = _assert_validation_failure(
        lambda: validate_edit_plan(
            _plan(
                _mutation(
                    "src/example.py",
                    b"def broken(:\n",
                )
            )
        )
    )

    assert "src/example.py" in error.message
    assert "[python]" in error.message


def test_json_valid_candidate_passes() -> None:
    report = validate_edit_plan(
        _plan(
            _mutation(
                "config/example.json",
                b'{"value": 1}\n',
            )
        )
    )

    assert report.results[0].status is (
        ValidationStatus.PASS
    )
    assert (
        report.results[0].validator
        == "json"
    )


def test_json_invalid_candidate_rejected() -> None:
    error = _assert_validation_failure(
        lambda: validate_edit_plan(
            _plan(
                _mutation(
                    "config/example.json",
                    b'{"value": }\n',
                )
            )
        )
    )

    assert "[json]" in error.message
    assert "line" in error.message


def test_toml_valid_candidate_passes() -> None:
    report = validate_edit_plan(
        _plan(
            _mutation(
                "config/example.toml",
                b'value = "ok"\n',
            )
        )
    )

    assert report.results[0].status is (
        ValidationStatus.PASS
    )
    assert (
        report.results[0].validator
        == "toml"
    )


def test_toml_invalid_candidate_rejected() -> None:
    error = _assert_validation_failure(
        lambda: validate_edit_plan(
            _plan(
                _mutation(
                    "config/example.toml",
                    b"value = [\n",
                )
            )
        )
    )

    assert "[toml]" in error.message


@pytest.mark.parametrize(
    "target",
    [
        "src/example.PY",
        "config/example.JSON",
        "config/example.TOML",
    ],
)
def test_default_validator_extension_matching_is_case_insensitive(
    target: str,
) -> None:
    if target.endswith(".PY"):
        content = b"value = 1\n"
    elif target.endswith(".JSON"):
        content = b'{"value": 1}\n'
    else:
        content = b'value = "ok"\n'

    report = validate_edit_plan(
        _plan(
            _mutation(
                target,
                content,
            )
        )
    )

    assert report.results[0].status is (
        ValidationStatus.PASS
    )


def test_utf8_bom_is_accepted_by_default_validators() -> None:
    report = validate_edit_plan(
        _plan(
            _mutation(
                "src/example.py",
                b"\xef\xbb\xbfvalue = 1\n",
            )
        )
    )

    assert report.results[0].status is (
        ValidationStatus.PASS
    )


def test_unknown_extension_is_skipped() -> None:
    report = validate_edit_plan(
        _plan(
            _mutation(
                "README.md",
                b"# Example\n",
            )
        )
    )

    assert report.results == (
        ValidationResult(
            target="README.md",
            validator="none",
            status=ValidationStatus.SKIPPED,
            message=(
                "no default validator for target extension"
            ),
        ),
    )
    assert report.passed_count == 0
    assert report.skipped_count == 1


def test_delete_candidate_is_skipped() -> None:
    report = validate_edit_plan(
        _plan(
            _mutation(
                "src/obsolete.py",
                None,
                after_exists=False,
            )
        )
    )

    assert report.results[0].status is (
        ValidationStatus.SKIPPED
    )
    assert (
        report.results[0].message
        == "target has no candidate after-state"
    )


def test_multiple_candidates_are_all_validated() -> None:
    report = validate_edit_plan(
        _plan(
            _mutation(
                "src/a.py",
                b"value = 1\n",
            ),
            _mutation(
                "config/a.json",
                b'{"value": 1}\n',
            ),
            _mutation(
                "config/a.toml",
                b'value = "ok"\n',
            ),
            _mutation(
                "README.md",
                b"# Example\n",
            ),
        )
    )

    assert [
        result.status
        for result in report.results
    ] == [
        ValidationStatus.PASS,
        ValidationStatus.PASS,
        ValidationStatus.PASS,
        ValidationStatus.SKIPPED,
    ]


def test_any_invalid_candidate_rejects_entire_validation() -> None:
    error = _assert_validation_failure(
        lambda: validate_edit_plan(
            _plan(
                _mutation(
                    "src/good.py",
                    b"value = 1\n",
                ),
                _mutation(
                    "config/bad.json",
                    b'{"value": }\n',
                ),
            )
        )
    )

    assert "config/bad.json" in error.message


def test_additional_validator_can_handle_external_extension() -> None:
    def validate_yaml(
        mutation: FileMutation,
    ) -> ValidationResult | None:
        if not mutation.target.endswith(
            ".yaml"
        ):
            return None

        return ValidationResult(
            target=mutation.target,
            validator="external-yaml",
            status=ValidationStatus.PASS,
            message="external adapter accepted candidate",
        )

    report = validate_edit_plan(
        _plan(
            _mutation(
                "config/example.yaml",
                b"value: 1\n",
            )
        ),
        additional_validators=(
            validate_yaml,
        ),
    )

    assert report.results == (
        ValidationResult(
            target="config/example.yaml",
            validator="external-yaml",
            status=ValidationStatus.PASS,
            message="external adapter accepted candidate",
        ),
    )


def test_additional_validator_failure_is_fail_closed() -> None:
    def reject_yaml(
        mutation: FileMutation,
    ) -> ValidationResult | None:
        if not mutation.target.endswith(
            ".yaml"
        ):
            return None

        return ValidationResult(
            target=mutation.target,
            validator="external-yaml",
            status=ValidationStatus.FAIL,
            message="adapter rejected candidate",
        )

    error = _assert_validation_failure(
        lambda: validate_edit_plan(
            _plan(
                _mutation(
                    "config/example.yaml",
                    b"value: 1\n",
                )
            ),
            additional_validators=(
                reject_yaml,
            ),
        )
    )

    assert "[external-yaml]" in error.message


def test_validation_does_not_modify_candidate_bytes() -> None:
    mutation = _mutation(
        "config/example.json",
        b'{\n  "value": 1\n}\n',
    )
    before = mutation.after_bytes

    validate_edit_plan(
        _plan(
            mutation
        )
    )

    assert mutation.after_bytes == before


def test_planner_candidate_integrates_with_validation(
    tmp_path: Path,
) -> None:
    target = tmp_path / "example.py"
    target.write_bytes(
        b"value = 1\n"
    )

    plan = plan_edit_text(
        tmp_path,
        """
FILE: example.py

<<<<<<< SEARCH
value = 1
=======
value = 2
>>>>>>> REPLACE
""",
    )

    report = validate_edit_plan(
        plan
    )

    assert report.results[0].status is (
        ValidationStatus.PASS
    )
    assert target.read_bytes() == (
        b"value = 1\n"
    )


def test_invalid_planner_candidate_rejected_before_write(
    tmp_path: Path,
) -> None:
    target = tmp_path / "example.py"
    target.write_bytes(
        b"value = 1\n"
    )

    plan = plan_edit_text(
        tmp_path,
        """
FILE: example.py

<<<<<<< SEARCH
value = 1
=======
def broken(:
>>>>>>> REPLACE
""",
    )

    _assert_validation_failure(
        lambda: validate_edit_plan(
            plan
        )
    )

    assert target.read_bytes() == (
        b"value = 1\n"
    )
