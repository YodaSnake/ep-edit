from __future__ import annotations

import hashlib
import os
import secrets
import stat
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from ep_edit.display import operator_path
from ep_edit.errors import DeterministicEditError
from ep_edit.planner import (
    EditPlan,
    FileMutation,
    FileMutationOperation,
)
from ep_edit.snapshot import load_text_snapshot


@dataclass(frozen=True)
class TargetRevalidationResult:
    target: str
    operation: FileMutationOperation
    current_exists: bool
    current_sha256: str | None
    state: str = "CURRENT"


@dataclass(frozen=True)
class PublicationPreflightReport:
    specification_checked: bool
    specification_sha256: str | None
    targets: tuple[TargetRevalidationResult, ...]


def revalidate_publication_preconditions(
    plan: EditPlan,
    *,
    specification_path: Path | None = None,
) -> PublicationPreflightReport:
    _revalidate_root_identity(
        plan
    )

    specification_sha256 = (
        _revalidate_specification(
            plan,
            specification_path,
        )
        if specification_path is not None
        else None
    )

    targets = tuple(
        revalidate_target_mutation(
            plan.root,
            mutation,
        )
        for mutation in plan.files
    )

    return PublicationPreflightReport(
        specification_checked=(
            specification_path is not None
        ),
        specification_sha256=specification_sha256,
        targets=targets,
    )


def revalidate_target_mutation(
    root: Path,
    mutation: FileMutation,
) -> TargetRevalidationResult:
    if (
        mutation.operation
        is FileMutationOperation.CREATE
    ):
        _require_create_still_absent(
            root,
            mutation,
        )

        return TargetRevalidationResult(
            target=mutation.target,
            operation=mutation.operation,
            current_exists=False,
            current_sha256=None,
        )

    if (
        mutation.operation
        not in {
            FileMutationOperation.REPLACE,
            FileMutationOperation.DELETE,
        }
    ):
        raise DeterministicEditError(
            "STALE_PREVIEW",
            (
                f"unsupported planned operation for "
                f"{mutation.target!r}: "
                f"{mutation.operation}"
            ),
        )

    if (
        not mutation.before_exists
        or mutation.before_sha256 is None
        or mutation.before_bytes is None
    ):
        raise DeterministicEditError(
            "STALE_PREVIEW",
            (
                f"planned before-state is incomplete "
                f"for {mutation.target!r}"
            ),
        )

    try:
        snapshot = load_text_snapshot(
            root,
            mutation.target,
        )
    except DeterministicEditError as exc:
        raise DeterministicEditError(
            "STALE_PREVIEW",
            (
                f"target state changed after preview: "
                f"{mutation.target!r}; "
                f"current state cannot satisfy planned "
                f"before-state ({exc.code})"
            ),
        ) from exc

    if (
        snapshot.sha256
        != mutation.before_sha256
        or snapshot.raw_bytes
        != mutation.before_bytes
    ):
        raise DeterministicEditError(
            "STALE_PREVIEW",
            (
                f"target bytes changed after preview: "
                f"{mutation.target!r}"
            ),
        )

    return TargetRevalidationResult(
        target=mutation.target,
        operation=mutation.operation,
        current_exists=True,
        current_sha256=snapshot.sha256,
    )


def _revalidate_root_identity(
    plan: EditPlan,
) -> None:
    if (
        plan.root_device is None
        or plan.root_inode is None
    ):
        raise DeterministicEditError(
            "STALE_PREVIEW",
            "planned root identity is unavailable",
        )

    try:
        root_stat = plan.root.lstat()
    except OSError as exc:
        raise DeterministicEditError(
            "STALE_PREVIEW",
            "root state changed after preview",
        ) from exc

    if (
        not stat.S_ISDIR(
            root_stat.st_mode
        )
        or root_stat.st_dev
        != plan.root_device
        or root_stat.st_ino
        != plan.root_inode
    ):
        raise DeterministicEditError(
            "STALE_PREVIEW",
            "root identity changed after preview",
        )


def _revalidate_specification(
    plan: EditPlan,
    specification_path: Path,
) -> str:
    try:
        raw = specification_path.read_bytes()
    except OSError as exc:
        raise DeterministicEditError(
            "STALE_SPECIFICATION",
            (
                "file-backed Edit Specification "
                "cannot be re-read: "
                f"{operator_path(specification_path)}"
            ),
        ) from exc

    current_sha256 = hashlib.sha256(
        raw
    ).hexdigest()

    if (
        current_sha256
        != plan.input_fingerprint
    ):
        raise DeterministicEditError(
            "STALE_SPECIFICATION",
            (
                "file-backed Edit Specification changed "
                "after planning"
            ),
        )

    return current_sha256


def _require_create_still_absent(
    root: Path,
    mutation: FileMutation,
) -> None:
    target = mutation.target
    relative = PurePosixPath(
        target
    )
    planned_missing = set(
        mutation.create_parent_directories
    )
    planned_existing = {
        identity.relative_path: identity
        for identity in (
            mutation.create_existing_parent_identities
        )
    }
    current = root

    for depth, part in enumerate(
        relative.parts[:-1],
        start=1,
    ):
        current = (
            current
            / part
        )
        current_relative = PurePosixPath(
            *relative.parts[:depth]
        ).as_posix()

        if current_relative in planned_missing:
            try:
                current.lstat()
            except FileNotFoundError:
                continue
            except OSError as exc:
                raise DeterministicEditError(
                    "STALE_PREVIEW",
                    (
                        "planned CREATE parent state cannot be "
                        f"revalidated: {target!r}"
                    ),
                ) from exc

            raise DeterministicEditError(
                "STALE_PREVIEW",
                (
                    "planned missing CREATE parent appeared "
                    f"after preview: {target!r}"
                ),
            )

        try:
            item_stat = current.lstat()
        except FileNotFoundError as exc:
            raise DeterministicEditError(
                "STALE_PREVIEW",
                (
                    "CREATE parent state changed "
                    f"after preview: {target!r}"
                ),
            ) from exc
        except OSError as exc:
            raise DeterministicEditError(
                "STALE_PREVIEW",
                (
                    "CREATE parent state cannot be "
                    f"revalidated: {target!r}"
                ),
            ) from exc

        if stat.S_ISLNK(
            item_stat.st_mode
        ):
            raise DeterministicEditError(
                "STALE_PREVIEW",
                (
                    "CREATE target path gained a "
                    f"symbolic-link component: {target!r}"
                ),
            )

        if not stat.S_ISDIR(
            item_stat.st_mode
        ):
            raise DeterministicEditError(
                "STALE_PREVIEW",
                (
                    "CREATE parent is no longer a "
                    f"directory: {target!r}"
                ),
            )

        expected_identity = planned_existing.get(
            current_relative
        )

        if (
            expected_identity is None
            or item_stat.st_dev
            != expected_identity.device
            or item_stat.st_ino
            != expected_identity.inode
        ):
            raise DeterministicEditError(
                "STALE_PREVIEW",
                (
                    "CREATE parent identity changed "
                    f"after preview: {target!r}"
                ),
            )

    target_path = (
        root
        / target
    )

    try:
        target_path.lstat()
    except FileNotFoundError:
        return
    except OSError as exc:
        raise DeterministicEditError(
            "STALE_PREVIEW",
            (
                "CREATE target existence cannot be "
                f"revalidated: {target!r}"
            ),
        ) from exc

    raise DeterministicEditError(
        "STALE_PREVIEW",
        (
            "CREATE target appeared after preview: "
            f"{target!r}"
        ),
    )


@dataclass(frozen=True)
class PublishedTargetResult:
    target: str
    operation: FileMutationOperation
    final_exists: bool
    final_sha256: str | None


@dataclass(frozen=True)
class PublicationResult:
    targets: tuple[PublishedTargetResult, ...]


@dataclass
class _StagedCandidate:
    mutation: FileMutation
    path: Path | None = None
    directory_descriptor: int | None = None
    directory_relative_path: str | None = None
    name: str | None = None
    consumed: bool = False


@dataclass
class _PublishedMutationState:
    mutation: FileMutation
    target_path: Path
    backup_path: Path | None = None
    original_moved: bool = False
    after_published: bool = False


@dataclass
class _CreatedDirectory:
    relative_path: str
    device: int | None = None
    inode: int | None = None


def _directory_open_flags() -> int:
    if (
        not hasattr(
            os,
            "O_DIRECTORY",
        )
        or not hasattr(
            os,
            "O_NOFOLLOW",
        )
    ):
        raise DeterministicEditError(
            "APPLY_FAILED_ROLLED_BACK",
            (
                "platform does not provide required "
                "no-follow directory publication support"
            ),
        )

    flags = (
        os.O_RDONLY
        | os.O_DIRECTORY
        | os.O_NOFOLLOW
    )

    if hasattr(
        os,
        "O_CLOEXEC",
    ):
        flags |= os.O_CLOEXEC

    return flags


def _open_root_directory(
    plan: EditPlan,
) -> int:
    if (
        plan.root_device is None
        or plan.root_inode is None
    ):
        raise DeterministicEditError(
            "STALE_PREVIEW",
            "planned root identity is unavailable",
        )

    try:
        descriptor = os.open(
            plan.root,
            _directory_open_flags(),
        )
    except OSError as exc:
        raise DeterministicEditError(
            "STALE_PREVIEW",
            "Repository root cannot be opened safely during apply",
        ) from exc

    try:
        item_stat = os.fstat(
            descriptor
        )

        if (
            not stat.S_ISDIR(
                item_stat.st_mode
            )
            or item_stat.st_dev
            != plan.root_device
            or item_stat.st_ino
            != plan.root_inode
        ):
            raise DeterministicEditError(
                "STALE_PREVIEW",
                "Repository root identity changed during apply",
            )

        return descriptor

    except BaseException:
        os.close(
            descriptor
        )
        raise


def _planned_existing_parent_identities(
    plan: EditPlan,
) -> dict[str, tuple[int, int]]:
    identities: dict[
        str,
        tuple[int, int],
    ] = {}

    for mutation in plan.files:
        for identity in (
            mutation.create_existing_parent_identities
        ):
            current = (
                identity.device,
                identity.inode,
            )
            previous = identities.get(
                identity.relative_path
            )

            if (
                previous is not None
                and previous != current
            ):
                raise DeterministicEditError(
                    "STALE_PREVIEW",
                    (
                        "planned CREATE parent identity is "
                        f"inconsistent: {identity.relative_path!r}"
                    ),
                )

            identities[
                identity.relative_path
            ] = current

    return identities


def _open_directory_from_root(
    root_descriptor: int,
    relative_path: str,
    plan: EditPlan,
    created: list[_CreatedDirectory],
) -> int:
    if relative_path in {
        "",
        ".",
    }:
        return os.dup(
            root_descriptor
        )

    planned_existing = (
        _planned_existing_parent_identities(
            plan
        )
    )
    created_by_relative = {
        directory.relative_path: directory
        for directory in created
    }
    current_descriptor = os.dup(
        root_descriptor
    )
    traversed: list[str] = []

    try:
        for part in PurePosixPath(
            relative_path
        ).parts:
            traversed.append(
                part
            )
            current_relative = PurePosixPath(
                *traversed
            ).as_posix()

            try:
                next_descriptor = os.open(
                    part,
                    _directory_open_flags(),
                    dir_fd=current_descriptor,
                )
            except OSError as exc:
                raise DeterministicEditError(
                    "STALE_PREVIEW",
                    (
                        "CREATE directory path cannot be "
                        f"traversed safely: {relative_path!r}"
                    ),
                ) from exc

            try:
                item_stat = os.fstat(
                    next_descriptor
                )

                if not stat.S_ISDIR(
                    item_stat.st_mode
                ):
                    raise DeterministicEditError(
                        "STALE_PREVIEW",
                        (
                            "CREATE directory path gained a "
                            f"non-directory component: {relative_path!r}"
                        ),
                    )

                created_identity = (
                    created_by_relative.get(
                        current_relative
                    )
                )

                if created_identity is not None:
                    if (
                        created_identity.device is None
                        or created_identity.inode is None
                        or item_stat.st_dev
                        != created_identity.device
                        or item_stat.st_ino
                        != created_identity.inode
                    ):
                        raise DeterministicEditError(
                            "STALE_PREVIEW",
                            (
                                "Apply-created directory identity "
                                "changed during apply: "
                                f"{current_relative!r}"
                            ),
                        )

                else:
                    expected = planned_existing.get(
                        current_relative
                    )

                    if (
                        expected is None
                        or (
                            item_stat.st_dev,
                            item_stat.st_ino,
                        )
                        != expected
                    ):
                        raise DeterministicEditError(
                            "STALE_PREVIEW",
                            (
                                "existing CREATE parent identity "
                                "changed during apply: "
                                f"{current_relative!r}"
                            ),
                        )

            except BaseException:
                os.close(
                    next_descriptor
                )
                raise

            os.close(
                current_descriptor
            )
            current_descriptor = (
                next_descriptor
            )

        return current_descriptor

    except BaseException:
        os.close(
            current_descriptor
        )
        raise


def _planned_create_parent_directories(
    plan: EditPlan,
) -> tuple[str, ...]:
    return tuple(
        sorted(
            {
                directory
                for mutation in plan.files
                if (
                    mutation.operation
                    is FileMutationOperation.CREATE
                )
                for directory in (
                    mutation.create_parent_directories
                )
            },
            key=lambda directory: (
                len(
                    PurePosixPath(
                        directory
                    ).parts
                ),
                directory,
            ),
        )
    )


def _establish_create_parent_directories(
    root_descriptor: int,
    plan: EditPlan,
    created: list[_CreatedDirectory],
) -> None:
    for relative_path in (
        _planned_create_parent_directories(
            plan
        )
    ):
        relative = PurePosixPath(
            relative_path
        )
        parent_descriptor = (
            _open_directory_from_root(
                root_descriptor,
                relative.parent.as_posix(),
                plan,
                created,
            )
        )

        try:
            try:
                os.mkdir(
                    relative.name,
                    dir_fd=parent_descriptor,
                )
            except FileExistsError as exc:
                raise DeterministicEditError(
                    "STALE_PREVIEW",
                    (
                        "planned missing CREATE parent appeared "
                        f"during apply: {relative_path!r}"
                    ),
                ) from exc
            except OSError as exc:
                raise DeterministicEditError(
                    "APPLY_FAILED_ROLLED_BACK",
                    (
                        "CREATE parent directory could not be "
                        f"established: {relative_path!r}"
                    ),
                ) from exc

            owned = _CreatedDirectory(
                relative_path=relative_path,
            )
            created.append(
                owned
            )

            try:
                child_descriptor = os.open(
                    relative.name,
                    _directory_open_flags(),
                    dir_fd=parent_descriptor,
                )
            except OSError as exc:
                raise DeterministicEditError(
                    "STALE_PREVIEW",
                    (
                        "newly created CREATE parent cannot be "
                        f"opened safely: {relative_path!r}"
                    ),
                ) from exc

            try:
                item_stat = os.fstat(
                    child_descriptor
                )

                if not stat.S_ISDIR(
                    item_stat.st_mode
                ):
                    raise DeterministicEditError(
                        "STALE_PREVIEW",
                        (
                            "newly created CREATE parent is no "
                            f"longer a directory: {relative_path!r}"
                        ),
                    )

                owned.device = (
                    item_stat.st_dev
                )
                owned.inode = (
                    item_stat.st_ino
                )

            finally:
                os.close(
                    child_descriptor
                )

        finally:
            os.close(
                parent_descriptor
            )


def _cleanup_created_directories(
    root_descriptor: int,
    plan: EditPlan,
    created: list[_CreatedDirectory],
) -> str | None:
    for directory in reversed(
        created
    ):
        if (
            directory.device is None
            or directory.inode is None
        ):
            return (
                "Apply-created directory identity was "
                "not available for safe cleanup"
            )

        relative = PurePosixPath(
            directory.relative_path
        )
        parent_descriptor: int | None = None

        try:
            parent_descriptor = (
                _open_directory_from_root(
                    root_descriptor,
                    relative.parent.as_posix(),
                    plan,
                    created,
                )
            )

            try:
                item_stat = os.stat(
                    relative.name,
                    dir_fd=parent_descriptor,
                    follow_symlinks=False,
                )
            except FileNotFoundError:
                continue
            except OSError:
                return (
                    "Apply-created directory state could not "
                    "be checked during rollback cleanup"
                )

            if (
                stat.S_ISLNK(
                    item_stat.st_mode
                )
                or not stat.S_ISDIR(
                    item_stat.st_mode
                )
                or item_stat.st_dev
                != directory.device
                or item_stat.st_ino
                != directory.inode
            ):
                return (
                    "Apply-created directory identity changed "
                    "before rollback cleanup"
                )

            try:
                os.rmdir(
                    relative.name,
                    dir_fd=parent_descriptor,
                )
            except OSError:
                return (
                    "Apply-created directory is not safely "
                    "removable during rollback cleanup"
                )

        except DeterministicEditError:
            return (
                "Apply-created directory path cannot be "
                "safely traversed during rollback cleanup"
            )

        finally:
            if parent_descriptor is not None:
                os.close(
                    parent_descriptor
                )

    return None


def publish_edit_plan(
    plan: EditPlan,
    *,
    specification_path: Path | None = None,
) -> PublicationResult:
    revalidate_publication_preconditions(
        plan,
        specification_path=specification_path,
    )

    if any(
        _is_missing_parent_create(
            mutation
        )
        for mutation in plan.files
    ):
        return (
            _publish_edit_plan_with_missing_parent_creates(
                plan
            )
        )

    staged: dict[str, _StagedCandidate] = {}
    published: list[_PublishedMutationState] = []

    try:
        for mutation in plan.files:
            if mutation.after_exists:
                staged[
                    mutation.target
                ] = _stage_candidate(
                    plan.root,
                    mutation,
                )

        for mutation in plan.files:
            revalidate_target_mutation(
                plan.root,
                mutation,
            )

            state = _PublishedMutationState(
                mutation=mutation,
                target_path=(
                    plan.root
                    / mutation.target
                ),
            )
            published.append(
                state
            )

            _publish_one(
                state,
                staged.get(
                    mutation.target
                ),
            )
            _verify_applied_mutation(
                plan.root,
                mutation,
            )

        result = PublicationResult(
            targets=tuple(
                PublishedTargetResult(
                    target=mutation.target,
                    operation=mutation.operation,
                    final_exists=mutation.after_exists,
                    final_sha256=mutation.after_sha256,
                )
                for mutation in plan.files
            )
        )

    except DeterministicEditError as exc:
        mutated = _has_published_state(
            published
        )
        rollback_error = _rollback_published(
            plan.root,
            published,
        )
        cleanup_error = _cleanup_staged(
            staged,
        )

        if (
            rollback_error is not None
            or cleanup_error is not None
        ):
            detail = (
                rollback_error
                or cleanup_error
                or "unknown rollback failure"
            )
            raise DeterministicEditError(
                "ROLLBACK_FAILED",
                detail,
            ) from exc

        if (
            exc.code
            in {
                "STALE_SPECIFICATION",
                "STALE_PREVIEW",
            }
            and not mutated
        ):
            raise

        raise DeterministicEditError(
            "APPLY_FAILED_ROLLED_BACK",
            (
                "publication failed and all handled "
                f"target mutations were rolled back: {exc.code}"
            ),
        ) from exc

    except Exception as exc:
        rollback_error = _rollback_published(
            plan.root,
            published,
        )
        cleanup_error = _cleanup_staged(
            staged,
        )

        if (
            rollback_error is not None
            or cleanup_error is not None
        ):
            detail = (
                rollback_error
                or cleanup_error
                or "unknown rollback failure"
            )
            raise DeterministicEditError(
                "ROLLBACK_FAILED",
                detail,
            ) from exc

        raise DeterministicEditError(
            "APPLY_FAILED_ROLLED_BACK",
            (
                "publication failed and all handled "
                "target mutations were rolled back"
            ),
        ) from exc

    cleanup_error = _cleanup_success_state(
        staged,
        published,
    )

    if cleanup_error is not None:
        raise DeterministicEditError(
            "APPLY_CLEANUP_FAILED",
            cleanup_error,
        )

    return result


def _publish_edit_plan_with_missing_parent_creates(
    plan: EditPlan,
) -> PublicationResult:
    root_descriptor = (
        _open_root_directory(
            plan
        )
    )
    staged: dict[
        str,
        _StagedCandidate,
    ] = {}
    published: list[
        _PublishedMutationState
    ] = []
    created: list[
        _CreatedDirectory
    ] = []

    try:
        try:
            for mutation in plan.files:
                if not mutation.after_exists:
                    continue

                if _is_missing_parent_create(
                    mutation
                ):
                    staged[
                        mutation.target
                    ] = (
                        _stage_missing_parent_create(
                            root_descriptor,
                            plan,
                            mutation,
                        )
                    )
                else:
                    staged[
                        mutation.target
                    ] = _stage_candidate(
                        plan.root,
                        mutation,
                    )

            (
                _establish_create_parent_directories(
                    root_descriptor,
                    plan,
                    created,
                )
            )

            for mutation in plan.files:
                state = (
                    _PublishedMutationState(
                        mutation=mutation,
                        target_path=(
                            plan.root
                            / mutation.target
                        ),
                    )
                )
                published.append(
                    state
                )

                if _is_missing_parent_create(
                    mutation
                ):
                    parent_descriptor = (
                        _open_missing_parent_create_target_parent(
                            root_descriptor,
                            plan,
                            mutation,
                            created,
                        )
                    )

                    try:
                        (
                            _require_secure_create_target_absent(
                                parent_descriptor,
                                mutation,
                            )
                        )
                        (
                            _publish_missing_parent_create(
                                parent_descriptor,
                                state,
                                staged.get(
                                    mutation.target
                                ),
                            )
                        )
                        (
                            _verify_missing_parent_create(
                                parent_descriptor,
                                mutation,
                            )
                        )

                    finally:
                        os.close(
                            parent_descriptor
                        )

                    continue

                revalidate_target_mutation(
                    plan.root,
                    mutation,
                )
                _publish_one(
                    state,
                    staged.get(
                        mutation.target
                    ),
                )
                _verify_applied_mutation(
                    plan.root,
                    mutation,
                )

            result = PublicationResult(
                targets=tuple(
                    PublishedTargetResult(
                        target=mutation.target,
                        operation=mutation.operation,
                        final_exists=(
                            mutation.after_exists
                        ),
                        final_sha256=(
                            mutation.after_sha256
                        ),
                    )
                    for mutation in plan.files
                )
            )

        except DeterministicEditError as exc:
            mutated = (
                _has_published_state(
                    published
                )
                or bool(
                    created
                )
            )

            rollback_error = (
                _rollback_published_with_secure_creates(
                    plan,
                    root_descriptor,
                    created,
                    published,
                )
            )
            directory_error = (
                _cleanup_created_directories(
                    root_descriptor,
                    plan,
                    created,
                )
            )
            cleanup_error = (
                _cleanup_staged(
                    staged
                )
            )

            if (
                rollback_error is not None
                or directory_error is not None
                or cleanup_error is not None
            ):
                detail = (
                    rollback_error
                    or directory_error
                    or cleanup_error
                    or "unknown rollback failure"
                )
                raise DeterministicEditError(
                    "ROLLBACK_FAILED",
                    detail,
                ) from exc

            if (
                exc.code
                in {
                    "STALE_SPECIFICATION",
                    "STALE_PREVIEW",
                }
                and not mutated
            ):
                raise

            raise DeterministicEditError(
                "APPLY_FAILED_ROLLED_BACK",
                (
                    "publication failed and all handled "
                    "target mutations were rolled back: "
                    f"{exc.code}"
                ),
            ) from exc

        except Exception as exc:
            rollback_error = (
                _rollback_published_with_secure_creates(
                    plan,
                    root_descriptor,
                    created,
                    published,
                )
            )
            directory_error = (
                _cleanup_created_directories(
                    root_descriptor,
                    plan,
                    created,
                )
            )
            cleanup_error = (
                _cleanup_staged(
                    staged
                )
            )

            if (
                rollback_error is not None
                or directory_error is not None
                or cleanup_error is not None
            ):
                detail = (
                    rollback_error
                    or directory_error
                    or cleanup_error
                    or "unknown rollback failure"
                )
                raise DeterministicEditError(
                    "ROLLBACK_FAILED",
                    detail,
                ) from exc

            raise DeterministicEditError(
                "APPLY_FAILED_ROLLED_BACK",
                (
                    "publication failed and all handled "
                    "target mutations were rolled back"
                ),
            ) from exc

        cleanup_error = (
            _cleanup_success_state(
                staged,
                published,
            )
        )

        if cleanup_error is not None:
            raise DeterministicEditError(
                "APPLY_CLEANUP_FAILED",
                cleanup_error,
            )

        return result

    finally:
        try:
            os.close(
                root_descriptor
            )
        except OSError:
            pass


def _missing_parent_stage_directory(
    mutation: FileMutation,
) -> str:
    if (
        mutation.operation
        is not FileMutationOperation.CREATE
        or not mutation.create_parent_directories
    ):
        raise DeterministicEditError(
            "APPLY_FAILED_ROLLED_BACK",
            (
                "secure missing-parent staging requested "
                f"for ineligible target: {mutation.target!r}"
            ),
        )

    if not mutation.create_existing_parent_identities:
        return "."

    return (
        mutation
        .create_existing_parent_identities[-1]
        .relative_path
    )


def _create_ephemeral_file_at(
    parent_descriptor: int,
    *,
    prefix: str,
    mode: int,
) -> tuple[int, str]:
    flags = (
        os.O_RDWR
        | os.O_CREAT
        | os.O_EXCL
    )

    if hasattr(
        os,
        "O_CLOEXEC",
    ):
        flags |= os.O_CLOEXEC

    if hasattr(
        os,
        "O_NOFOLLOW",
    ):
        flags |= os.O_NOFOLLOW

    for _ in range(
        100
    ):
        name = (
            f"{prefix}"
            f"{os.getpid()}-"
            f"{secrets.token_hex(8)}"
        )

        try:
            descriptor = os.open(
                name,
                flags,
                mode,
                dir_fd=parent_descriptor,
            )
        except FileExistsError:
            continue

        return (
            descriptor,
            name,
        )

    raise OSError(
        "could not allocate CLI-owned descriptor-relative ephemeral file"
    )


def _stage_missing_parent_create(
    root_descriptor: int,
    plan: EditPlan,
    mutation: FileMutation,
) -> _StagedCandidate:
    if (
        not mutation.after_exists
        or mutation.after_bytes is None
        or mutation.after_sha256 is None
    ):
        raise DeterministicEditError(
            "APPLY_FAILED_ROLLED_BACK",
            (
                "candidate after-state is incomplete "
                f"for {mutation.target!r}"
            ),
        )

    stage_directory = (
        _missing_parent_stage_directory(
            mutation
        )
    )
    parent_descriptor = (
        _open_directory_from_root(
            root_descriptor,
            stage_directory,
            plan,
            [],
        )
    )
    file_descriptor: int | None = None
    stage_name: str | None = None

    try:
        (
            file_descriptor,
            stage_name,
        ) = _create_ephemeral_file_at(
            parent_descriptor,
            prefix=".ep-edit-stage-",
            mode=0o666,
        )

        with os.fdopen(
            file_descriptor,
            "w+b",
            closefd=True,
        ) as handle:
            file_descriptor = None

            handle.write(
                mutation.after_bytes
            )
            handle.flush()
            os.fsync(
                handle.fileno()
            )

            handle.seek(
                0
            )
            staged_bytes = (
                handle.read()
            )

        staged_sha256 = hashlib.sha256(
            staged_bytes
        ).hexdigest()

        if (
            staged_bytes
            != mutation.after_bytes
            or staged_sha256
            != mutation.after_sha256
        ):
            raise DeterministicEditError(
                "APPLY_FAILED_ROLLED_BACK",
                (
                    "staged candidate does not match "
                    f"planned after-state: {mutation.target!r}"
                ),
            )

        return _StagedCandidate(
            mutation=mutation,
            directory_descriptor=parent_descriptor,
            directory_relative_path=stage_directory,
            name=stage_name,
        )

    except BaseException:
        if file_descriptor is not None:
            try:
                os.close(
                    file_descriptor
                )
            except OSError:
                pass

        if stage_name is not None:
            try:
                os.unlink(
                    stage_name,
                    dir_fd=parent_descriptor,
                )
            except FileNotFoundError:
                pass
            except OSError:
                pass

        try:
            os.close(
                parent_descriptor
            )
        except OSError:
            pass

        raise


def _stage_candidate(
    root: Path,
    mutation: FileMutation,
) -> _StagedCandidate:
    if (
        not mutation.after_exists
        or mutation.after_bytes is None
        or mutation.after_sha256 is None
    ):
        raise DeterministicEditError(
            "APPLY_FAILED_ROLLED_BACK",
            (
                "candidate after-state is incomplete "
                f"for {mutation.target!r}"
            ),
        )

    if mutation.operation not in {
        FileMutationOperation.CREATE,
        FileMutationOperation.REPLACE,
    }:
        raise DeterministicEditError(
            "APPLY_FAILED_ROLLED_BACK",
            (
                "staging requested for non-candidate "
                f"operation {mutation.operation}"
            ),
        )

    target_path = (
        root
        / mutation.target
    )
    parent = target_path.parent

    if (
        mutation.operation
        is FileMutationOperation.CREATE
    ):
        requested_mode = 0o666
        replacement_mode = None
    else:
        try:
            target_stat = target_path.lstat()
        except OSError as exc:
            raise DeterministicEditError(
                "STALE_PREVIEW",
                (
                    "REPLACE target cannot be staged "
                    f"because current mode is unavailable: "
                    f"{mutation.target!r}"
                ),
            ) from exc

        requested_mode = 0o600
        replacement_mode = stat.S_IMODE(
            target_stat.st_mode
        )

    file_descriptor, stage_path = (
        _create_ephemeral_file(
            parent,
            prefix=".ep-edit-stage-",
            mode=requested_mode,
        )
    )

    try:
        with os.fdopen(
            file_descriptor,
            "wb",
            closefd=True,
        ) as handle:
            if replacement_mode is not None:
                os.fchmod(
                    handle.fileno(),
                    replacement_mode,
                )

            handle.write(
                mutation.after_bytes
            )
            handle.flush()
            os.fsync(
                handle.fileno()
            )

        staged_bytes = stage_path.read_bytes()
        staged_sha256 = hashlib.sha256(
            staged_bytes
        ).hexdigest()

        if (
            staged_bytes
            != mutation.after_bytes
            or staged_sha256
            != mutation.after_sha256
        ):
            raise DeterministicEditError(
                "APPLY_FAILED_ROLLED_BACK",
                (
                    "staged candidate does not match "
                    f"planned after-state: {mutation.target!r}"
                ),
            )

        return _StagedCandidate(
            mutation=mutation,
            path=stage_path,
        )

    except BaseException:
        try:
            os.close(
                file_descriptor
            )
        except OSError:
            pass

        try:
            stage_path.unlink()
        except FileNotFoundError:
            pass
        except OSError:
            pass

        raise


def _create_ephemeral_file(
    parent: Path,
    *,
    prefix: str,
    mode: int,
) -> tuple[int, Path]:
    for _ in range(
        100
    ):
        candidate = (
            parent
            / (
                f"{prefix}"
                f"{os.getpid()}-"
                f"{secrets.token_hex(8)}"
            )
        )

        try:
            descriptor = os.open(
                candidate,
                (
                    os.O_WRONLY
                    | os.O_CREAT
                    | os.O_EXCL
                ),
                mode,
            )
        except FileExistsError:
            continue

        return (
            descriptor,
            candidate,
        )

    raise OSError(
        "could not allocate CLI-owned ephemeral file"
    )


def _is_missing_parent_create(
    mutation: FileMutation,
) -> bool:
    return (
        mutation.operation
        is FileMutationOperation.CREATE
        and bool(
            mutation.create_parent_directories
        )
    )


def _open_missing_parent_create_target_parent(
    root_descriptor: int,
    plan: EditPlan,
    mutation: FileMutation,
    created: list[_CreatedDirectory],
) -> int:
    if not _is_missing_parent_create(
        mutation
    ):
        raise DeterministicEditError(
            "APPLY_FAILED_ROLLED_BACK",
            (
                "secure CREATE target-parent open requested "
                f"for ineligible target: {mutation.target!r}"
            ),
        )

    parent_relative = (
        PurePosixPath(
            mutation.target
        )
        .parent
        .as_posix()
    )

    return _open_directory_from_root(
        root_descriptor,
        parent_relative,
        plan,
        created,
    )


def _secure_create_target_name(
    mutation: FileMutation,
) -> str:
    return PurePosixPath(
        mutation.target
    ).name


def _require_secure_create_target_absent(
    parent_descriptor: int,
    mutation: FileMutation,
) -> None:
    target_name = (
        _secure_create_target_name(
            mutation
        )
    )

    try:
        os.stat(
            target_name,
            dir_fd=parent_descriptor,
            follow_symlinks=False,
        )
    except FileNotFoundError:
        return
    except OSError as exc:
        raise DeterministicEditError(
            "STALE_PREVIEW",
            (
                "CREATE target state cannot be "
                f"revalidated securely: {mutation.target!r}"
            ),
        ) from exc

    raise DeterministicEditError(
        "STALE_PREVIEW",
        (
            "CREATE target appeared during "
            f"secure publication: {mutation.target!r}"
        ),
    )


def _publish_missing_parent_create(
    parent_descriptor: int,
    state: _PublishedMutationState,
    staged: _StagedCandidate | None,
) -> None:
    mutation = state.mutation

    if not _is_missing_parent_create(
        mutation
    ):
        raise RuntimeError(
            "secure CREATE publication requested for ineligible mutation"
        )

    if (
        staged is None
        or staged.directory_descriptor
        is None
        or staged.name is None
    ):
        raise RuntimeError(
            "secure CREATE candidate was not staged"
        )

    target_name = (
        _secure_create_target_name(
            mutation
        )
    )

    try:
        os.link(
            staged.name,
            target_name,
            src_dir_fd=(
                staged.directory_descriptor
            ),
            dst_dir_fd=parent_descriptor,
            follow_symlinks=False,
        )
    except FileExistsError as exc:
        raise DeterministicEditError(
            "STALE_PREVIEW",
            (
                "CREATE target appeared during "
                f"secure publication: {mutation.target!r}"
            ),
        ) from exc

    state.after_published = True

    os.unlink(
        staged.name,
        dir_fd=(
            staged.directory_descriptor
        ),
    )
    staged.consumed = True


def _read_regular_file_at(
    parent_descriptor: int,
    name: str,
    *,
    target: str,
) -> bytes:
    flags = os.O_RDONLY

    if hasattr(
        os,
        "O_CLOEXEC",
    ):
        flags |= os.O_CLOEXEC

    if hasattr(
        os,
        "O_NOFOLLOW",
    ):
        flags |= os.O_NOFOLLOW

    try:
        descriptor = os.open(
            name,
            flags,
            dir_fd=parent_descriptor,
        )
    except OSError as exc:
        raise RuntimeError(
            (
                "published target cannot be opened "
                f"safely: {target}"
            )
        ) from exc

    try:
        item_stat = os.fstat(
            descriptor
        )

        if not stat.S_ISREG(
            item_stat.st_mode
        ):
            raise RuntimeError(
                (
                    "published target is no longer "
                    f"a regular file: {target}"
                )
            )

        chunks: list[bytes] = []

        while True:
            chunk = os.read(
                descriptor,
                65536,
            )

            if not chunk:
                break

            chunks.append(
                chunk
            )

        return b"".join(
            chunks
        )

    finally:
        os.close(
            descriptor
        )


def _verify_missing_parent_create(
    parent_descriptor: int,
    mutation: FileMutation,
) -> None:
    if (
        mutation.after_bytes is None
        or mutation.after_sha256 is None
    ):
        raise DeterministicEditError(
            "POST_APPLY_VERIFY_FAILED",
            (
                "planned after-state is incomplete "
                f"for {mutation.target!r}"
            ),
        )

    try:
        raw = _read_regular_file_at(
            parent_descriptor,
            _secure_create_target_name(
                mutation
            ),
            target=mutation.target,
        )
    except RuntimeError as exc:
        raise DeterministicEditError(
            "POST_APPLY_VERIFY_FAILED",
            (
                "published CREATE target cannot be "
                f"verified securely: {mutation.target!r}"
            ),
        ) from exc

    if (
        raw != mutation.after_bytes
        or hashlib.sha256(
            raw
        ).hexdigest()
        != mutation.after_sha256
    ):
        raise DeterministicEditError(
            "POST_APPLY_VERIFY_FAILED",
            (
                "published CREATE target does not match "
                f"planned after-state: {mutation.target!r}"
            ),
        )


def _rollback_missing_parent_create(
    parent_descriptor: int,
    state: _PublishedMutationState,
) -> None:
    mutation = state.mutation

    if not state.after_published:
        return

    if (
        mutation.after_bytes is None
        or mutation.after_sha256 is None
    ):
        raise RuntimeError(
            "planned after-state is unavailable"
        )

    raw = _read_regular_file_at(
        parent_descriptor,
        _secure_create_target_name(
            mutation
        ),
        target=mutation.target,
    )

    if (
        raw != mutation.after_bytes
        or hashlib.sha256(
            raw
        ).hexdigest()
        != mutation.after_sha256
    ):
        raise RuntimeError(
            (
                "published target changed before rollback: "
                f"{mutation.target}"
            )
        )

    os.unlink(
        _secure_create_target_name(
            mutation
        ),
        dir_fd=parent_descriptor,
    )
    state.after_published = False


def _publish_one(
    state: _PublishedMutationState,
    staged: _StagedCandidate | None,
) -> None:
    mutation = state.mutation
    target_path = state.target_path

    if (
        mutation.operation
        is FileMutationOperation.CREATE
    ):
        if staged is None:
            raise RuntimeError(
                "CREATE candidate was not staged"
            )

        try:
            os.link(
                staged.path,
                target_path,
            )
        except FileExistsError as exc:
            raise DeterministicEditError(
                "STALE_PREVIEW",
                (
                    "CREATE target appeared during "
                    f"publication: {mutation.target!r}"
                ),
            ) from exc

        state.after_published = True

        staged.path.unlink()
        staged.consumed = True
        return

    backup_path = _allocate_backup_path(
        target_path.parent
    )
    state.backup_path = backup_path

    os.rename(
        target_path,
        backup_path,
    )
    state.original_moved = True

    if (
        mutation.operation
        is FileMutationOperation.DELETE
    ):
        return

    if (
        mutation.operation
        is not FileMutationOperation.REPLACE
    ):
        raise RuntimeError(
            (
                "unsupported publication operation: "
                f"{mutation.operation}"
            )
        )

    if staged is None:
        raise RuntimeError(
            "REPLACE candidate was not staged"
        )

    os.replace(
        staged.path,
        target_path,
    )
    staged.consumed = True
    state.after_published = True


def _allocate_backup_path(
    parent: Path,
) -> Path:
    for _ in range(
        100
    ):
        candidate = (
            parent
            / (
                ".ep-edit-backup-"
                f"{os.getpid()}-"
                f"{secrets.token_hex(8)}"
            )
        )

        try:
            candidate.lstat()
        except FileNotFoundError:
            return candidate

    raise OSError(
        "could not allocate CLI-owned backup path"
    )


def _verify_applied_mutation(
    root: Path,
    mutation: FileMutation,
) -> None:
    target_path = (
        root
        / mutation.target
    )

    if (
        mutation.operation
        is FileMutationOperation.DELETE
    ):
        try:
            target_path.lstat()
        except FileNotFoundError:
            return
        except OSError as exc:
            raise DeterministicEditError(
                "POST_APPLY_VERIFY_FAILED",
                (
                    "DELETE target state cannot be "
                    f"verified: {mutation.target!r}"
                ),
            ) from exc

        raise DeterministicEditError(
            "POST_APPLY_VERIFY_FAILED",
            (
                "DELETE target still exists after "
                f"publication: {mutation.target!r}"
            ),
        )

    if (
        mutation.after_bytes is None
        or mutation.after_sha256 is None
    ):
        raise DeterministicEditError(
            "POST_APPLY_VERIFY_FAILED",
            (
                "planned after-state is incomplete "
                f"for {mutation.target!r}"
            ),
        )

    try:
        snapshot = load_text_snapshot(
            root,
            mutation.target,
        )
    except DeterministicEditError as exc:
        raise DeterministicEditError(
            "POST_APPLY_VERIFY_FAILED",
            (
                "published target cannot be loaded "
                f"for verification: {mutation.target!r}"
            ),
        ) from exc

    if (
        snapshot.raw_bytes
        != mutation.after_bytes
        or snapshot.sha256
        != mutation.after_sha256
    ):
        raise DeterministicEditError(
            "POST_APPLY_VERIFY_FAILED",
            (
                "published target does not match "
                f"planned after-state: {mutation.target!r}"
            ),
        )


def _rollback_published_with_secure_creates(
    plan: EditPlan,
    root_descriptor: int,
    created: list[_CreatedDirectory],
    published: list[_PublishedMutationState],
) -> str | None:
    restored: list[
        _PublishedMutationState
    ] = []

    try:
        for state in reversed(
            published
        ):
            mutation = state.mutation
            target_path = state.target_path
            was_mutated = (
                state.original_moved
                or state.after_published
            )

            if _is_missing_parent_create(
                mutation
            ):
                if state.after_published:
                    parent_descriptor = (
                        _open_missing_parent_create_target_parent(
                            root_descriptor,
                            plan,
                            mutation,
                            created,
                        )
                    )

                    try:
                        (
                            _rollback_missing_parent_create(
                                parent_descriptor,
                                state,
                            )
                        )
                    finally:
                        os.close(
                            parent_descriptor
                        )

                continue

            if (
                mutation.operation
                is FileMutationOperation.CREATE
            ):
                if state.after_published:
                    _require_current_after_state(
                        target_path,
                        mutation,
                    )
                    target_path.unlink()
                    state.after_published = False

                if was_mutated:
                    restored.append(
                        state
                    )

                continue

            backup_path = state.backup_path

            if state.after_published:
                _require_current_after_state(
                    target_path,
                    mutation,
                )
                target_path.unlink()
                state.after_published = False

            if (
                state.original_moved
                and backup_path is not None
            ):
                if _lstat_exists(
                    target_path
                ):
                    raise RuntimeError(
                        (
                            "rollback target unexpectedly "
                            f"exists: {mutation.target}"
                        )
                    )

                os.rename(
                    backup_path,
                    target_path,
                )
                state.original_moved = False

            if was_mutated:
                restored.append(
                    state
                )

        for state in restored:
            revalidate_target_mutation(
                plan.root,
                state.mutation,
            )

    except Exception:
        return (
            "best-effort rollback could not restore "
            "the planned original state"
        )

    return None


def _rollback_published(
    root: Path,
    published: list[_PublishedMutationState],
) -> str | None:
    restored: list[
        _PublishedMutationState
    ] = []

    try:
        for state in reversed(
            published
        ):
            mutation = state.mutation
            target_path = state.target_path
            was_mutated = (
                state.original_moved
                or state.after_published
            )

            if (
                mutation.operation
                is FileMutationOperation.CREATE
            ):
                if state.after_published:
                    _require_current_after_state(
                        target_path,
                        mutation,
                    )
                    target_path.unlink()
                    state.after_published = False

                if was_mutated:
                    restored.append(
                        state
                    )

                continue

            backup_path = state.backup_path

            if state.after_published:
                _require_current_after_state(
                    target_path,
                    mutation,
                )
                target_path.unlink()
                state.after_published = False

            if (
                state.original_moved
                and backup_path is not None
            ):
                if _lstat_exists(
                    target_path
                ):
                    raise RuntimeError(
                        (
                            "rollback target unexpectedly "
                            f"exists: {mutation.target}"
                        )
                    )

                os.rename(
                    backup_path,
                    target_path,
                )
                state.original_moved = False

            if was_mutated:
                restored.append(
                    state
                )

        for state in restored:
            revalidate_target_mutation(
                root,
                state.mutation,
            )

    except Exception:
        return (
            "best-effort rollback could not restore "
            "the planned original state"
        )

    return None


def _require_current_after_state(
    target_path: Path,
    mutation: FileMutation,
) -> None:
    if (
        mutation.after_bytes is None
        or mutation.after_sha256 is None
    ):
        raise RuntimeError(
            "planned after-state is unavailable"
        )

    try:
        item_stat = target_path.lstat()
    except OSError as exc:
        raise RuntimeError(
            (
                "published target cannot be read "
                f"during rollback: {mutation.target}"
            )
        ) from exc

    if not stat.S_ISREG(
        item_stat.st_mode
    ):
        raise RuntimeError(
            (
                "published target is no longer "
                f"a regular file: {mutation.target}"
            )
        )

    raw = target_path.read_bytes()

    if (
        raw != mutation.after_bytes
        or hashlib.sha256(
            raw
        ).hexdigest()
        != mutation.after_sha256
    ):
        raise RuntimeError(
            (
                "published target changed before rollback: "
                f"{mutation.target}"
            )
        )


def _cleanup_staged(
    staged: dict[str, _StagedCandidate],
) -> str | None:
    cleanup_failed = False

    for candidate in staged.values():
        try:
            if not candidate.consumed:
                if (
                    candidate.directory_descriptor
                    is not None
                    and candidate.name is not None
                ):
                    try:
                        os.unlink(
                            candidate.name,
                            dir_fd=(
                                candidate
                                .directory_descriptor
                            ),
                        )
                    except FileNotFoundError:
                        pass

                elif candidate.path is not None:
                    try:
                        candidate.path.unlink()
                    except FileNotFoundError:
                        pass

                else:
                    cleanup_failed = True

                candidate.consumed = True

        except OSError:
            cleanup_failed = True

        finally:
            if (
                candidate.directory_descriptor
                is not None
            ):
                try:
                    os.close(
                        candidate
                        .directory_descriptor
                    )
                except OSError:
                    cleanup_failed = True

                candidate.directory_descriptor = (
                    None
                )

    if cleanup_failed:
        return (
            "CLI-owned staged candidate cleanup failed"
        )

    return None


def _cleanup_success_state(
    staged: dict[str, _StagedCandidate],
    published: list[_PublishedMutationState],
) -> str | None:
    staged_error = _cleanup_staged(
        staged
    )

    if staged_error is not None:
        return staged_error

    try:
        for state in published:
            if (
                state.backup_path is None
                or not state.original_moved
            ):
                continue

            try:
                state.backup_path.unlink()
            except FileNotFoundError:
                pass

            state.original_moved = False

    except OSError:
        return (
            "CLI-owned backup cleanup failed after "
            "successful publication"
        )

    return None


def _has_published_state(
    published: list[_PublishedMutationState],
) -> bool:
    return any(
        (
            state.original_moved
            or state.after_published
        )
        for state in published
    )


def _lstat_exists(
    target_path: Path,
) -> bool:
    try:
        target_path.lstat()
    except FileNotFoundError:
        return False

    return True
