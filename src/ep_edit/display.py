from __future__ import annotations

from pathlib import Path


def operator_path(
    path: Path,
) -> str:
    """Render a path without exposing host-specific absolute directories."""
    candidate = path.expanduser()
    try:
        root = Path.cwd().resolve(
            strict=True
        )
    except (OSError, RuntimeError):
        root = None

    if root is not None:
        try:
            resolved = candidate
            if not resolved.is_absolute():
                resolved = root / resolved
            relative = (
                resolved.resolve(
                    strict=False
                )
                .relative_to(
                    root
                )
            )
        except (
            OSError,
            RuntimeError,
            ValueError,
        ):
            pass
        else:
            rendered = relative.as_posix()
            return (
                rendered
                if rendered
                else "."
            )

    return (
        candidate.name
        if candidate.name
        else "<path>"
    )
