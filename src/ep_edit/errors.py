from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RepairCandidate:
    start_line: int
    end_line: int
    similarity_basis_points: int | None = None
    excerpt: tuple[str, ...] = ()
    excerpt_truncated: bool = False


@dataclass(frozen=True)
class RepairMetadata:
    kind: str
    guidance: str
    candidates: tuple[
        RepairCandidate,
        ...,
    ] = ()
    total_candidate_count: int | None = None
    candidates_truncated: bool = False


class DeterministicEditError(RuntimeError):
    """Fail-closed error with a stable machine-readable category."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        repair_metadata: RepairMetadata | None = None,
    ) -> None:
        super().__init__(
            f"{code}: {message}"
        )
        self.code = code
        self.message = message
        self.repair_metadata = (
            repair_metadata
        )


@dataclass(frozen=True)
class EditDiagnostic:
    code: str
    edit_id: str
    target: str
    message: str
    label: str | None = None
    repair_metadata: RepairMetadata | None = None


class EditPreflightError(
    DeterministicEditError
):
    """One or more read-only edit-local preflight failures."""

    def __init__(
        self,
        diagnostics: tuple[
            EditDiagnostic,
            ...,
        ],
    ) -> None:
        if not diagnostics:
            raise ValueError(
                "EditPreflightError requires diagnostics"
            )

        ordered = tuple(
            sorted(
                diagnostics,
                key=lambda diagnostic: (
                    diagnostic.target,
                    diagnostic.edit_id,
                    diagnostic.code,
                    diagnostic.message,
                ),
            )
        )

        if len(ordered) == 1:
            code = ordered[0].code
            message = ordered[0].message
        else:
            code = "EDIT_PREFLIGHT_FAILED"
            message = (
                f"{len(ordered)} edit preflight "
                "error(s)"
            )

        super().__init__(
            code,
            message,
        )

        self.diagnostics = ordered
