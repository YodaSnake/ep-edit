from __future__ import annotations

import codecs
import hashlib
import os
import stat
from pathlib import Path

import pytest

from ep_edit.errors import DeterministicEditError
from ep_edit.snapshot import (
    NewlineStyle,
    load_text_snapshot,
)


pytestmark = pytest.mark.unit


def _assert_error(
    expected_code: str,
    callable_,
) -> DeterministicEditError:
    with pytest.raises(
        DeterministicEditError
    ) as raised:
        callable_()

    assert (
        raised.value.code
        == expected_code
    )

    return raised.value


def test_snapshot_preserves_lf_and_final_newline(
    tmp_path: Path,
) -> None:
    target = (
        tmp_path
        / "example.txt"
    )
    target.write_bytes(
        b"alpha\nbeta\n"
    )

    snapshot = load_text_snapshot(
        tmp_path,
        "example.txt",
    )

    assert (
        snapshot.raw_bytes
        == b"alpha\nbeta\n"
    )
    assert (
        snapshot.text
        == "alpha\nbeta\n"
    )
    assert (
        snapshot.newline_style
        is NewlineStyle.LF
    )
    assert (
        snapshot.has_final_newline
        is True
    )
    assert (
        snapshot.has_utf8_bom
        is False
    )
    assert (
        snapshot.sha256
        == hashlib.sha256(
            b"alpha\nbeta\n"
        ).hexdigest()
    )


def test_snapshot_preserves_crlf_and_final_newline(
    tmp_path: Path,
) -> None:
    target = (
        tmp_path
        / "example.txt"
    )
    target.write_bytes(
        b"alpha\r\nbeta\r\n"
    )

    snapshot = load_text_snapshot(
        tmp_path,
        "example.txt",
    )

    assert (
        snapshot.text
        == "alpha\r\nbeta\r\n"
    )
    assert (
        snapshot.newline_style
        is NewlineStyle.CRLF
    )
    assert (
        snapshot.has_final_newline
        is True
    )


def test_snapshot_preserves_missing_final_newline(
    tmp_path: Path,
) -> None:
    target = (
        tmp_path
        / "example.txt"
    )
    target.write_bytes(
        b"alpha\nbeta"
    )

    snapshot = load_text_snapshot(
        tmp_path,
        "example.txt",
    )

    assert (
        snapshot.newline_style
        is NewlineStyle.LF
    )
    assert (
        snapshot.has_final_newline
        is False
    )


def test_single_line_without_newline_has_no_style(
    tmp_path: Path,
) -> None:
    target = (
        tmp_path
        / "example.txt"
    )
    target.write_bytes(
        b"alpha"
    )

    snapshot = load_text_snapshot(
        tmp_path,
        "example.txt",
    )

    assert (
        snapshot.newline_style
        is None
    )
    assert (
        snapshot.has_final_newline
        is False
    )


def test_empty_file_has_no_newline_style(
    tmp_path: Path,
) -> None:
    target = (
        tmp_path
        / "example.txt"
    )
    target.write_bytes(
        b""
    )

    snapshot = load_text_snapshot(
        tmp_path,
        "example.txt",
    )

    assert snapshot.text == ""
    assert (
        snapshot.newline_style
        is None
    )
    assert (
        snapshot.has_final_newline
        is False
    )


def test_utf8_bom_is_detected_and_preserved(
    tmp_path: Path,
) -> None:
    raw = (
        codecs.BOM_UTF8
        + b"alpha\n"
    )
    target = (
        tmp_path
        / "example.txt"
    )
    target.write_bytes(
        raw
    )

    snapshot = load_text_snapshot(
        tmp_path,
        "example.txt",
    )

    assert (
        snapshot.has_utf8_bom
        is True
    )
    assert (
        snapshot.raw_bytes
        == raw
    )
    assert (
        snapshot.text
        == "alpha\n"
    )
    assert (
        snapshot.sha256
        == hashlib.sha256(
            raw
        ).hexdigest()
    )


def test_mixed_newlines_fail_closed(
    tmp_path: Path,
) -> None:
    target = (
        tmp_path
        / "example.txt"
    )
    target.write_bytes(
        b"alpha\r\nbeta\n"
    )

    _assert_error(
        "MIXED_NEWLINE",
        lambda: load_text_snapshot(
            tmp_path,
            "example.txt",
        ),
    )


def test_lone_cr_fails_closed(
    tmp_path: Path,
) -> None:
    target = (
        tmp_path
        / "example.txt"
    )
    target.write_bytes(
        b"alpha\rbeta"
    )

    _assert_error(
        "UNSUPPORTED_NEWLINE",
        lambda: load_text_snapshot(
            tmp_path,
            "example.txt",
        ),
    )


def test_invalid_utf8_fails_closed(
    tmp_path: Path,
) -> None:
    target = (
        tmp_path
        / "example.txt"
    )
    target.write_bytes(
        b"\xff"
    )

    _assert_error(
        "UNSUPPORTED_ENCODING",
        lambda: load_text_snapshot(
            tmp_path,
            "example.txt",
        ),
    )


def test_nul_byte_fails_closed(
    tmp_path: Path,
) -> None:
    target = (
        tmp_path
        / "example.txt"
    )
    target.write_bytes(
        b"alpha\x00beta"
    )

    _assert_error(
        "UNSUPPORTED_ENCODING",
        lambda: load_text_snapshot(
            tmp_path,
            "example.txt",
        ),
    )


def test_missing_target_fails_closed(
    tmp_path: Path,
) -> None:
    _assert_error(
        "TARGET_NOT_FOUND",
        lambda: load_text_snapshot(
            tmp_path,
            "missing.txt",
        ),
    )


def test_directory_target_fails_closed(
    tmp_path: Path,
) -> None:
    directory = (
        tmp_path
        / "directory"
    )
    directory.mkdir()

    _assert_error(
        "TARGET_NOT_REGULAR_FILE",
        lambda: load_text_snapshot(
            tmp_path,
            "directory",
        ),
    )


def test_symlink_target_fails_closed(
    tmp_path: Path,
) -> None:
    source = (
        tmp_path
        / "source.txt"
    )
    source.write_text(
        "alpha\n",
        encoding="utf-8",
    )
    link = (
        tmp_path
        / "link.txt"
    )

    try:
        link.symlink_to(
            source.name
        )
    except OSError:
        pytest.skip(
            "symbolic links are unavailable"
        )

    _assert_error(
        "TARGET_SYMLINK",
        lambda: load_text_snapshot(
            tmp_path,
            "link.txt",
        ),
    )


def test_symlink_component_fails_closed(
    tmp_path: Path,
) -> None:
    real = (
        tmp_path
        / "real"
    )
    real.mkdir()

    target = (
        real
        / "example.txt"
    )
    target.write_text(
        "alpha\n",
        encoding="utf-8",
    )

    link = (
        tmp_path
        / "linked"
    )

    try:
        link.symlink_to(
            real.name,
            target_is_directory=True,
        )
    except OSError:
        pytest.skip(
            "symbolic links are unavailable"
        )

    _assert_error(
        "TARGET_SYMLINK",
        lambda: load_text_snapshot(
            tmp_path,
            "linked/example.txt",
        ),
    )


def test_hard_link_target_fails_closed(
    tmp_path: Path,
) -> None:
    source = (
        tmp_path
        / "source.txt"
    )
    source.write_text(
        "alpha\n",
        encoding="utf-8",
    )

    hardlink = (
        tmp_path
        / "hardlink.txt"
    )

    try:
        os.link(
            source,
            hardlink,
        )
    except OSError:
        pytest.skip(
            "hard links are unavailable"
        )

    _assert_error(
        "TARGET_HARDLINK",
        lambda: load_text_snapshot(
            tmp_path,
            "hardlink.txt",
        ),
    )


def test_snapshot_records_posix_mode(
    tmp_path: Path,
) -> None:
    target = (
        tmp_path
        / "example.txt"
    )
    target.write_text(
        "alpha\n",
        encoding="utf-8",
    )
    target.chmod(
        0o640
    )

    snapshot = load_text_snapshot(
        tmp_path,
        "example.txt",
    )

    assert (
        snapshot.posix_mode
        == stat.S_IMODE(
            target.stat().st_mode
        )
    )
