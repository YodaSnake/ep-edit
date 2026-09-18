from __future__ import annotations


SEARCH_PAYLOAD_MARKERS = (
    "=======",
    ">>>>>>> REPLACE",
)
REPLACE_PAYLOAD_MARKERS = (
    ">>>>>>> REPLACE",
)
CONTENT_PAYLOAD_MARKERS = (
    ">>>>>>> CONTENT",
)
REVISION_EDIT_PAYLOAD_MARKERS = (
    ">>>>>>> EDIT",
)


def encode_structural_payload_line(
    line: str,
    *,
    markers: tuple[str, ...],
) -> str:
    if _is_marker_form(
        line,
        markers=markers,
    ):
        return "\\" + line

    return line


def decode_structural_payload_line(
    line: str,
    *,
    markers: tuple[str, ...],
) -> str:
    if not line.startswith(
        "\\"
    ):
        return line

    candidate = line[1:]

    if _is_marker_form(
        candidate,
        markers=markers,
    ):
        return candidate

    return line


def _is_marker_form(
    line: str,
    *,
    markers: tuple[str, ...],
) -> bool:
    without_escape_prefix = (
        line.lstrip(
            "\\"
        )
    )

    return (
        without_escape_prefix
        in markers
    )
