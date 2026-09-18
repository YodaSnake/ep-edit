from __future__ import annotations

import codecs
import hashlib
import stat
from dataclasses import dataclass
from enum import Enum
from pathlib import Path, PurePosixPath

from ep_edit.errors import DeterministicEditError
from ep_edit.specification import normalize_target_path


class NewlineStyle(str, Enum):
    LF = "LF"
    CRLF = "CRLF"


@dataclass(frozen=True)
class TextSnapshot:
    root: Path
    target: str
    path: Path
    raw_bytes: bytes
    text: str
    sha256: str
    has_utf8_bom: bool
    newline_style: NewlineStyle | None
    has_final_newline: bool
    posix_mode: int


def load_text_snapshot(
    root: Path,
    target: str,
) -> TextSnapshot:
    canonical_target = (
        normalize_target_path(
            target
        )
    )

    try:
        resolved_root = (
            root.expanduser()
            .resolve(
                strict=True
            )
        )
    except OSError as exc:
        raise DeterministicEditError(
            "TARGET_INVALID_PATH",
            "root does not exist",
        ) from exc

    if not resolved_root.is_dir():
        raise DeterministicEditError(
            "TARGET_INVALID_PATH",
            (
                "root is not a directory"
            ),
        )

    relative = PurePosixPath(
        canonical_target
    )
    current = resolved_root

    for part in relative.parts:
        current = current / part

        try:
            item_stat = (
                current.lstat()
            )
        except FileNotFoundError as exc:
            raise DeterministicEditError(
                "TARGET_NOT_FOUND",
                (
                    "target does not exist: "
                    f"{canonical_target}"
                ),
            ) from exc

        if stat.S_ISLNK(
            item_stat.st_mode
        ):
            raise DeterministicEditError(
                "TARGET_SYMLINK",
                (
                    "symbolic links are not "
                    "allowed in target path: "
                    f"{canonical_target}"
                ),
            )

    try:
        resolved_target = (
            current.resolve(
                strict=True
            )
        )
        resolved_target.relative_to(
            resolved_root
        )
    except ValueError as exc:
        raise DeterministicEditError(
            "TARGET_OUTSIDE_ROOT",
            (
                "target escapes root: "
                f"{canonical_target}"
            ),
        ) from exc

    target_stat = (
        resolved_target.stat()
    )

    if not stat.S_ISREG(
        target_stat.st_mode
    ):
        raise DeterministicEditError(
            "TARGET_NOT_REGULAR_FILE",
            (
                "target is not a "
                "regular file: "
                f"{canonical_target}"
            ),
        )

    if target_stat.st_nlink > 1:
        raise DeterministicEditError(
            "TARGET_HARDLINK",
            (
                "hard-linked target is "
                "not allowed: "
                f"{canonical_target}"
            ),
        )

    raw = resolved_target.read_bytes()

    if b"\x00" in raw:
        raise DeterministicEditError(
            "UNSUPPORTED_ENCODING",
            (
                "NUL byte found in target: "
                f"{canonical_target}"
            ),
        )

    has_bom = raw.startswith(
        codecs.BOM_UTF8
    )

    body = (
        raw[len(codecs.BOM_UTF8) :]
        if has_bom
        else raw
    )

    try:
        text = body.decode(
            "utf-8"
        )
    except UnicodeDecodeError as exc:
        raise DeterministicEditError(
            "UNSUPPORTED_ENCODING",
            (
                "target is not valid UTF-8: "
                f"{canonical_target}"
            ),
        ) from exc

    newline_style = (
        _detect_newline_style(
            body,
            target=canonical_target,
        )
    )

    has_final_newline = (
        _has_final_newline(
            body,
            newline_style,
        )
    )

    return TextSnapshot(
        root=resolved_root,
        target=canonical_target,
        path=resolved_target,
        raw_bytes=raw,
        text=text,
        sha256=hashlib.sha256(
            raw
        ).hexdigest(),
        has_utf8_bom=has_bom,
        newline_style=newline_style,
        has_final_newline=(
            has_final_newline
        ),
        posix_mode=stat.S_IMODE(
            target_stat.st_mode
        ),
    )


def _detect_newline_style(
    raw: bytes,
    *,
    target: str,
) -> NewlineStyle | None:
    without_crlf = raw.replace(
        b"\r\n",
        b"",
    )

    if b"\r" in without_crlf:
        raise DeterministicEditError(
            "UNSUPPORTED_NEWLINE",
            (
                "target contains lone CR: "
                f"{target}"
            ),
        )

    has_crlf = b"\r\n" in raw
    has_lf = b"\n" in without_crlf

    if (
        has_crlf
        and has_lf
    ):
        raise DeterministicEditError(
            "MIXED_NEWLINE",
            (
                "target mixes LF and "
                f"CRLF: {target}"
            ),
        )

    if has_crlf:
        return NewlineStyle.CRLF

    if has_lf:
        return NewlineStyle.LF

    return None


def _has_final_newline(
    raw: bytes,
    newline_style: NewlineStyle | None,
) -> bool:
    if (
        newline_style
        is NewlineStyle.CRLF
    ):
        return raw.endswith(
            b"\r\n"
        )

    if (
        newline_style
        is NewlineStyle.LF
    ):
        return raw.endswith(
            b"\n"
        )

    return False
