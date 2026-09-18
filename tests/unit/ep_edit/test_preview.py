from __future__ import annotations

import codecs
import hashlib
from pathlib import Path

import pytest

from ep_edit.errors import DeterministicEditError
from ep_edit.planner import plan_edit_text as _plan_edit_text
from ep_edit.preview import build_validated_preview
from ep_edit.validators import (
    ValidationResult,
    ValidationStatus,
)


pytestmark = pytest.mark.unit


def plan_edit_text(
    root: Path,
    text: str,
):
    return _plan_edit_text(
        root,
        text,
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


def test_preview_contains_required_plan_and_file_metadata(
    tmp_path: Path,
) -> None:
    before = b"value = 1\n"
    after = b"value = 2\n"
    _write(
        tmp_path,
        "example.py",
        before,
    )

    plan = plan_edit_text(
        tmp_path,
        """FILE: example.py
LABEL: update-value

<<<<<<< SEARCH
value = 1
=======
value = 2
>>>>>>> REPLACE
""",
    )

    preview = build_validated_preview(
        plan
    )
    text = preview.text

    assert "=== PLAN ===" in text
    assert "Root: ." in text
    assert str(tmp_path) not in text
    assert "Files: 1" in text
    assert "Edits: 1" in text
    assert "Target: example.py" in text
    assert "Operation: REPLACE" in text
    assert (
        hashlib.sha256(
            before
        ).hexdigest()[:12]
        in text
    )
    assert (
        hashlib.sha256(
            after
        ).hexdigest()[:12]
        in text
    )
    assert (
        "Changed lines: -1 +1"
        in text
    )
    assert (
        "Newline: before=LF after=LF"
        in text
    )
    assert (
        "Final newline: before=YES after=YES"
        in text
    )
    assert "--- a/example.py" in text
    assert "+++ b/example.py" in text
    assert "-value = 1" in text
    assert "+value = 2" in text
    assert (
        "example.py [python] PASS: "
        "Python syntax valid"
        in text
    )


def test_create_preview_uses_dev_null_before(
    tmp_path: Path,
) -> None:
    plan = plan_edit_text(
        tmp_path,
        """FILE: new.txt
LABEL: create-new
MODE: CREATE
<<<<<<< CONTENT
created
>>>>>>> CONTENT
""",
    )

    text = build_validated_preview(
        plan
    ).text

    assert "Operation: CREATE" in text
    assert (
        "Before SHA-256: ABSENT"
        in text
    )
    assert (
        "Newline: before=ABSENT after=LF"
        in text
    )
    assert "--- /dev/null" in text
    assert "+++ b/new.txt" in text
    assert "+created" in text


def test_missing_parent_create_preview_is_explicit_and_non_writing(
    tmp_path: Path,
) -> None:
    plan = plan_edit_text(
        tmp_path,
        (
            "FILE: missing/deep/new.txt\n"
            "LABEL: create-new\n"
            "MODE: CREATE\n"
            + "<" * 7
            + " CONTENT\n"
            + "created\n"
            + ">" * 7
            + " CONTENT\n"
        ),
    )

    text = build_validated_preview(
        plan
    ).text

    assert (
        "Create parent directories: missing, missing/deep"
        in text
    )
    assert not (
        tmp_path
        / "missing"
    ).exists()


def test_delete_preview_is_highlighted_and_uses_dev_null_after(
    tmp_path: Path,
) -> None:
    _write(
        tmp_path,
        "obsolete.py",
        b"value = 1\n",
    )

    plan = plan_edit_text(
        tmp_path,
        """FILE: obsolete.py
LABEL: delete-obsolete
MODE: DELETE
""",
    )

    text = build_validated_preview(
        plan
    ).text

    assert "Operation: DELETE" in text
    assert "DELETE TARGET: YES" in text
    assert "--- a/obsolete.py" in text
    assert "+++ /dev/null" in text
    assert (
        "obsolete.py [none] SKIPPED: "
        "target has no candidate after-state"
        in text
    )


def test_multifile_preview_uses_plan_target_order(
    tmp_path: Path,
) -> None:
    _write(
        tmp_path,
        "z.py",
        b"z = 1\n",
    )
    _write(
        tmp_path,
        "a.py",
        b"a = 1\n",
    )

    plan = plan_edit_text(
        tmp_path,
        """FILE: z.py
LABEL: update-z
<<<<<<< SEARCH
z = 1
=======
z = 2
>>>>>>> REPLACE

FILE: a.py
LABEL: update-a
<<<<<<< SEARCH
a = 1
=======
a = 2
>>>>>>> REPLACE
""",
    )

    text = build_validated_preview(
        plan
    ).text

    assert (
        text.index(
            "Target: a.py"
        )
        <
        text.index(
            "Target: z.py"
        )
    )
    assert "Files: 2" in text
    assert "Edits: 2" in text


def test_noop_warning_is_rendered_and_counted_as_edit(
    tmp_path: Path,
) -> None:
    _write(
        tmp_path,
        "example.py",
        b"same = 1\nold = 1\n",
    )

    plan = plan_edit_text(
        tmp_path,
        """FILE: example.py
LABEL: noop
<<<<<<< SEARCH
same = 1
=======
same = 1
>>>>>>> REPLACE

FILE: example.py
LABEL: change
<<<<<<< SEARCH
old = 1
=======
old = 2
>>>>>>> REPLACE
""",
    )

    text = build_validated_preview(
        plan
    ).text

    assert "Edits: 2" in text
    assert "=== WARNINGS ===" in text
    warning_ref = (
        plan.warnings[0].edit_ref
    )
    assert (
        "example.py [NO_CHANGE_EDIT] "
        f"EDIT {warning_ref}:"
        in text
    )


def test_crlf_target_metadata_is_preserved_while_diff_uses_lf(
    tmp_path: Path,
) -> None:
    _write(
        tmp_path,
        "example.txt",
        b"old\r\nkeep\r\n",
    )

    plan = plan_edit_text(
        tmp_path,
        """FILE: example.txt
LABEL: update
<<<<<<< SEARCH
old
=======
new
>>>>>>> REPLACE
""",
    )

    text = build_validated_preview(
        plan
    ).text

    assert (
        "Newline: before=CRLF after=CRLF"
        in text
    )
    assert "-old\n" in text
    assert "+new\n" in text
    assert "\r" not in text


def test_final_newline_change_uses_standard_no_newline_marker(
    tmp_path: Path,
) -> None:
    _write(
        tmp_path,
        "example.txt",
        b"same\n",
    )

    plan = plan_edit_text(
        tmp_path,
        """FILE: example.txt
LABEL: remove-final-newline
MODE: REPLACE_FILE
FINAL_NEWLINE: NO
<<<<<<< CONTENT
same
>>>>>>> CONTENT
""",
    )

    text = build_validated_preview(
        plan
    ).text

    assert (
        "Final newline: before=YES after=NO"
        in text
    )
    assert (
        "\\ No newline at end of file"
        in text
    )


def test_bom_is_rendered_when_preserved(
    tmp_path: Path,
) -> None:
    _write(
        tmp_path,
        "example.txt",
        codecs.BOM_UTF8
        + b"old\n",
    )

    plan = plan_edit_text(
        tmp_path,
        """FILE: example.txt
LABEL: update
<<<<<<< SEARCH
old
=======
new
>>>>>>> REPLACE
""",
    )

    text = build_validated_preview(
        plan
    ).text

    assert (
        "BOM: before=YES after=YES"
        in text
    )


def test_bom_transition_is_rendered(
    tmp_path: Path,
) -> None:
    _write(
        tmp_path,
        "example.txt",
        codecs.BOM_UTF8
        + b"old\n",
    )

    plan = plan_edit_text(
        tmp_path,
        """FILE: example.txt
LABEL: remove-bom
MODE: REPLACE_FILE
BOM: NO
<<<<<<< CONTENT
new
>>>>>>> CONTENT
""",
    )

    text = build_validated_preview(
        plan
    ).text

    assert (
        "BOM: before=YES after=NO"
        in text
    )


def test_representation_only_newline_change_is_explicit(
    tmp_path: Path,
) -> None:
    _write(
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

    text = build_validated_preview(
        plan
    ).text

    assert (
        "Changed lines: -0 +0"
        in text
    )
    assert (
        "Newline: before=CRLF after=LF"
        in text
    )
    assert (
        "byte change is representation-only"
        in text
    )


def test_unknown_extension_validation_skip_is_visible(
    tmp_path: Path,
) -> None:
    _write(
        tmp_path,
        "README.md",
        b"old\n",
    )

    plan = plan_edit_text(
        tmp_path,
        """FILE: README.md
LABEL: update-readme
<<<<<<< SEARCH
old
=======
new
>>>>>>> REPLACE
""",
    )

    text = build_validated_preview(
        plan
    ).text

    assert (
        "README.md [none] SKIPPED: "
        "no default validator for target extension"
        in text
    )


def test_invalid_candidate_fails_before_preview_is_built(
    tmp_path: Path,
) -> None:
    _write(
        tmp_path,
        "example.py",
        b"value = 1\n",
    )

    plan = plan_edit_text(
        tmp_path,
        """FILE: example.py
LABEL: break-python
<<<<<<< SEARCH
value = 1
=======
def broken(:
>>>>>>> REPLACE
""",
    )

    _assert_validation_failure(
        lambda: build_validated_preview(
            plan
        )
    )


def test_preview_generation_does_not_modify_target(
    tmp_path: Path,
) -> None:
    target = _write(
        tmp_path,
        "example.py",
        b"value = 1\n",
    )

    plan = plan_edit_text(
        tmp_path,
        """FILE: example.py
LABEL: update
<<<<<<< SEARCH
value = 1
=======
value = 2
>>>>>>> REPLACE
""",
    )

    build_validated_preview(
        plan
    )

    assert target.read_bytes() == (
        b"value = 1\n"
    )


def test_preview_sha_is_deterministic(
    tmp_path: Path,
) -> None:
    _write(
        tmp_path,
        "example.py",
        b"value = 1\n",
    )

    plan = plan_edit_text(
        tmp_path,
        """FILE: example.py
LABEL: update
<<<<<<< SEARCH
value = 1
=======
value = 2
>>>>>>> REPLACE
""",
    )

    first = build_validated_preview(
        plan
    )
    second = build_validated_preview(
        plan
    )

    assert first.text == second.text
    assert first.sha256 == second.sha256
    assert first.sha256 == (
        hashlib.sha256(
            first.text.encode(
                "utf-8"
            )
        ).hexdigest()
    )


def test_empty_create_reports_existence_only_diff(
    tmp_path: Path,
) -> None:
    plan = plan_edit_text(
        tmp_path,
        """FILE: empty.txt
LABEL: create-empty
MODE: CREATE
FINAL_NEWLINE: NO
<<<<<<< CONTENT
>>>>>>> CONTENT
""",
    )

    text = build_validated_preview(
        plan
    ).text

    assert (
        "Changed lines: -0 +0"
        in text
    )
    assert (
        "file existence changes"
        in text
    )


def test_additional_validator_result_is_rendered(
    tmp_path: Path,
) -> None:
    _write(
        tmp_path,
        "example.yaml",
        b"value: 1\n",
    )

    plan = plan_edit_text(
        tmp_path,
        """FILE: example.yaml
LABEL: update-yaml
<<<<<<< SEARCH
value: 1
=======
value: 2
>>>>>>> REPLACE
""",
    )

    def validate_yaml(
        mutation,
    ) -> ValidationResult | None:
        if not mutation.target.endswith(
            ".yaml"
        ):
            return None

        return ValidationResult(
            target=mutation.target,
            validator="external-yaml",
            status=ValidationStatus.PASS,
            message="adapter accepted candidate",
        )

    text = build_validated_preview(
        plan,
        additional_validators=(
            validate_yaml,
        ),
    ).text

    assert (
        "example.yaml [external-yaml] PASS: "
        "adapter accepted candidate"
        in text
    )


def test_changed_line_count_handles_multiline_replace(
    tmp_path: Path,
) -> None:
    _write(
        tmp_path,
        "example.txt",
        b"a\nb\nc\n",
    )

    plan = plan_edit_text(
        tmp_path,
        """FILE: example.txt
LABEL: replace-middle
<<<<<<< SEARCH
b
=======
x
y
>>>>>>> REPLACE
""",
    )

    text = build_validated_preview(
        plan
    ).text

    assert (
        "Changed lines: -1 +2"
        in text
    )


def test_input_fingerprint_short_form_is_rendered(
    tmp_path: Path,
) -> None:
    _write(
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

    plan = plan_edit_text(
        tmp_path,
        specification,
    )

    text = build_validated_preview(
        plan
    ).text

    expected = hashlib.sha256(
        specification.encode(
            "utf-8"
        )
    ).hexdigest()[:12]

    assert (
        f"Input fingerprint: {expected}"
        in text
    )
