from __future__ import annotations

import ast
import json
import tomllib
from dataclasses import dataclass
from enum import Enum
from pathlib import PurePosixPath
from typing import Callable

from ep_edit.errors import DeterministicEditError
from ep_edit.planner import EditPlan, FileMutation


class ValidationStatus(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    SKIPPED = "SKIPPED"


@dataclass(frozen=True)
class ValidationResult:
    target: str
    validator: str
    status: ValidationStatus
    message: str


@dataclass(frozen=True)
class ValidationReport:
    results: tuple[ValidationResult, ...]

    @property
    def passed_count(self) -> int:
        return sum(
            result.status is ValidationStatus.PASS
            for result in self.results
        )

    @property
    def skipped_count(self) -> int:
        return sum(
            result.status is ValidationStatus.SKIPPED
            for result in self.results
        )


CandidateValidator = Callable[
    [FileMutation],
    ValidationResult | None,
]


def validate_edit_plan(
    plan: EditPlan,
    *,
    additional_validators: tuple[
        CandidateValidator,
        ...,
    ] = (),
) -> ValidationReport:
    validators: tuple[
        CandidateValidator,
        ...,
    ] = (
        _validate_python_candidate,
        _validate_json_candidate,
        _validate_toml_candidate,
        *additional_validators,
    )

    results: list[ValidationResult] = []

    for mutation in plan.files:
        if not mutation.after_exists:
            results.append(
                ValidationResult(
                    target=mutation.target,
                    validator="none",
                    status=ValidationStatus.SKIPPED,
                    message=(
                        "target has no candidate after-state"
                    ),
                )
            )
            continue

        handled = False

        for validator in validators:
            result = validator(
                mutation
            )

            if result is None:
                continue

            handled = True
            results.append(
                result
            )

        if not handled:
            results.append(
                ValidationResult(
                    target=mutation.target,
                    validator="none",
                    status=ValidationStatus.SKIPPED,
                    message=(
                        "no default validator for target extension"
                    ),
                )
            )

    failures = [
        result
        for result in results
        if result.status is ValidationStatus.FAIL
    ]

    if failures:
        details = "; ".join(
            (
                f"{result.target} "
                f"[{result.validator}]: "
                f"{result.message}"
            )
            for result in failures
        )

        raise DeterministicEditError(
            "VALIDATION_FAILED",
            (
                f"{len(failures)} candidate validation "
                f"failure(s): {details}"
            ),
        )

    return ValidationReport(
        results=tuple(results),
    )


def _validate_python_candidate(
    mutation: FileMutation,
) -> ValidationResult | None:
    if _suffix(mutation.target) != ".py":
        return None

    text, decode_error = _decode_candidate(
        mutation
    )

    if decode_error is not None:
        return ValidationResult(
            target=mutation.target,
            validator="python",
            status=ValidationStatus.FAIL,
            message=decode_error,
        )

    assert text is not None

    try:
        ast.parse(
            text,
            filename=mutation.target,
            mode="exec",
        )
    except SyntaxError as exc:
        location = _syntax_location(
            exc
        )

        return ValidationResult(
            target=mutation.target,
            validator="python",
            status=ValidationStatus.FAIL,
            message=(
                f"{exc.msg}{location}"
            ),
        )

    return ValidationResult(
        target=mutation.target,
        validator="python",
        status=ValidationStatus.PASS,
        message="Python syntax valid",
    )


def _validate_json_candidate(
    mutation: FileMutation,
) -> ValidationResult | None:
    if _suffix(mutation.target) != ".json":
        return None

    text, decode_error = _decode_candidate(
        mutation
    )

    if decode_error is not None:
        return ValidationResult(
            target=mutation.target,
            validator="json",
            status=ValidationStatus.FAIL,
            message=decode_error,
        )

    assert text is not None

    try:
        json.loads(
            text
        )
    except json.JSONDecodeError as exc:
        return ValidationResult(
            target=mutation.target,
            validator="json",
            status=ValidationStatus.FAIL,
            message=(
                f"{exc.msg} at line {exc.lineno}, "
                f"column {exc.colno}"
            ),
        )

    return ValidationResult(
        target=mutation.target,
        validator="json",
        status=ValidationStatus.PASS,
        message="JSON syntax valid",
    )


def _validate_toml_candidate(
    mutation: FileMutation,
) -> ValidationResult | None:
    if _suffix(mutation.target) != ".toml":
        return None

    text, decode_error = _decode_candidate(
        mutation
    )

    if decode_error is not None:
        return ValidationResult(
            target=mutation.target,
            validator="toml",
            status=ValidationStatus.FAIL,
            message=decode_error,
        )

    assert text is not None

    try:
        tomllib.loads(
            text
        )
    except tomllib.TOMLDecodeError as exc:
        return ValidationResult(
            target=mutation.target,
            validator="toml",
            status=ValidationStatus.FAIL,
            message=str(exc),
        )

    return ValidationResult(
        target=mutation.target,
        validator="toml",
        status=ValidationStatus.PASS,
        message="TOML syntax valid",
    )


def _decode_candidate(
    mutation: FileMutation,
) -> tuple[str | None, str | None]:
    raw = mutation.after_bytes

    if raw is None:
        return (
            None,
            "candidate after-bytes are unavailable",
        )

    try:
        return (
            raw.decode(
                "utf-8-sig"
            ),
            None,
        )
    except UnicodeDecodeError:
        return (
            None,
            "candidate is not valid UTF-8",
        )


def _suffix(
    target: str,
) -> str:
    return (
        PurePosixPath(target)
        .suffix
        .lower()
    )


def _syntax_location(
    error: SyntaxError,
) -> str:
    if error.lineno is None:
        return ""

    location = (
        f" at line {error.lineno}"
    )

    if error.offset is not None:
        location += (
            f", column {error.offset}"
        )

    return location
