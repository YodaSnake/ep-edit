# Development Guide

This document describes the contributor and standalone package boundary for
`ep-edit`.

It complements:

- `README.md` for product and usage orientation;
- `AGENTS.md` for agent-facing authoring rules;
- `docs/CLI_REFERENCE.md` for the public CLI contract;
- `docs/EDIT_SPECIFICATION.md` for Edit and Revision grammar;
- `docs/CHATGPT_COPY_PASTE_WORKFLOW.md` for browser-assisted authoring.

## Repository state

This repository is the standalone home of `ep-edit`.

The package implementation lives at:

    src/ep_edit/

Standalone documentation lives at:

    README.md
    AGENTS.md
    DEVELOPMENT.md
    docs/

The package code is intentionally generic.

The runtime import boundary uses:

- Python standard-library modules; and
- modules inside `ep_edit`.

The runtime package must not depend on `ep_system`.

## Standalone packaging

The repository-level `pyproject.toml` defines the standalone distribution:

    ep-edit

It defines the public console entry point:

    ep-edit = ep_edit.cli:main

Host-only EP System entry points and dependencies are not part of this
package.

## Required standalone CLI entry point

The current public CLI entry point is:

    ep-edit = ep_edit.cli:main

A standalone package must preserve the `ep-edit` command contract unless an
explicit compatibility decision changes it.

Host-only entry points such as `repo-edit` are not part of the standalone
`ep-edit` package.

## Runtime dependency boundary

The current `src/ep_edit` runtime implementation uses only Python
standard-library modules and `ep_edit` internals.

The standalone `pyproject.toml` currently declares no runtime dependencies.

Do not introduce a dependency solely because that dependency happens to be
available in a consuming project.

In particular, `ep_edit -> ep_system` remains prohibited.

If a future third-party runtime dependency is intentionally introduced, treat
that as an explicit standalone product decision and test it independently.

## Public Python API

The package top level currently exports:

- `DeterministicEditError`;
- `EditSpecification`;
- `NewlineStyle`;
- `SearchReplaceEdit`;
- `TextSnapshot`;
- `load_text_snapshot`;
- `normalize_target_path`;
- `parse_edit_specification`.

These exports are the intentionally small top-level Python surface at the
current productization checkpoint.

Internal modules such as planner, preview, publisher, revision, and
structural-escape implementation modules are not automatically promoted to a
stable public API merely because tests import them directly.

Changes to the public Python surface should be intentional.

## CLI-first product boundary

`ep-edit` is primarily a CLI product.

The CLI is the preferred integration boundary for ordinary users and
automation.

The public Python API is intentionally narrower than the complete internal
module graph.

Do not expose internals simply to make integration or packaging mechanically
easier.

## Python module execution

There is currently no:

    src/ep_edit/__main__.py

Therefore:

    python -m ep_edit

is not currently a documented public invocation path.

The supported command is the installed console entry point:

    ep-edit

If module execution is added later, it should be an intentional feature with
its own tests and documentation rather than an accidental packaging side
effect.

## Test boundary

The dedicated package unit suite lives under:

    tests/unit/ep_edit/

That suite is the primary behavioral test corpus for `ep-edit`.

It covers areas including:

- CLI behavior;
- Edit Specification grammar;
- Revision Specification grammar;
- planning;
- Preview;
- validation;
- deterministic repair diagnostics;
- publication;
- rollback;
- stale-state handling;
- whole-file operations;
- missing-parent CREATE;
- secure directory and staging behavior;
- structural escaping.

From the standalone repository root, with the supported Python version, the
package, and pytest installed in the active environment, run:

    python -m pytest -q

This intentionally exercises the installed package rather than overriding
imports with `PYTHONPATH=src`.

## Standalone console-delivery test

Standalone package and console-delivery metadata coverage lives at:

    tests/unit/test_ep_edit_console_delivery.py

That test verifies this repository's package metadata and the
`ep-edit` console entry-point target.

It must not introduce assumptions about EP System host packaging.

## Repository test inventory rule

Do not use only `git ls-files` as the authority for the complete test
inventory while relevant work remains uncommitted.

A pre-commit or release inventory must include the actual working-tree test
set, including newly created tests that may not yet be tracked.

Before publication or release, compare:

- package source inventory;
- package-focused tests;
- public documentation;
- package metadata requirements;
- CLI entry-point expectations.

## Standalone repository responsibilities

This repository should preserve and verify:

1. standalone `pyproject.toml` metadata;
2. Python version support;
3. the `ep-edit = ep_edit.cli:main` console entry point;
4. runtime dependency boundaries;
5. package discovery and layout;
6. package-focused test layout;
7. standalone console-delivery coverage;
8. README and contributor documentation placement;
9. license and repository metadata as applicable;
10. CI or local test commands for the standalone repository.

Host-only EP System packages, scripts, commands, and dependencies must not
become standalone dependencies by accident.

## Documentation layout

The standalone documentation layout is:

    README.md
    AGENTS.md
    DEVELOPMENT.md
    docs/CHATGPT_COPY_PASTE_WORKFLOW.md
    docs/CLI_REFERENCE.md
    docs/EDIT_SPECIFICATION.md

Keep links relative to this repository layout and do not introduce
machine-local or unrelated host-repository paths.

## Safe development workflow

Changes to `ep-edit` should continue to dogfood the deterministic authoring
workflow where practical:

    inspect current state
        ->
    author exact Specification
        ->
    check
        ->
    preview
        ->
    Human review
        ->
    apply
        ->
    focused tests
        ->
    broader relevant regression

If CHECK fails or Preview is rejected, preserve the failed authoring
workspace and use a fresh attempt workspace for the corrected attempt.

See `docs/CHATGPT_COPY_PASTE_WORKFLOW.md` for the detailed workspace
lifecycle.

## Validation expectations

A source change should receive focused tests for the changed behavior.

Changes affecting shared planner, publication, representation, or CLI
contracts should also receive continuity tests covering neighboring behavior.

Before a meaningful release or extraction checkpoint, run the broader
standalone-relevant regression selected for that checkpoint.

Do not interpret a documentation-only validator SKIPPED result as source-code
validation.

Use `git diff --check` or the standalone repository equivalent to detect
whitespace errors in reviewed changes.

## Platform-sensitive behavior

The ordinary file and stdin CLI input paths do not require the macOS
Clipboard command.

`--clipboard` currently uses macOS `pbpaste`.

Missing-parent CREATE publication also requires the secure filesystem
capabilities documented by the implementation and CLI reference.

Development and CI environments should exercise supported capability paths
and verify fail-closed behavior when required capabilities are unavailable.

Do not claim broader platform support than the tested publication contract
actually establishes.

## Standalone boundary principle

This repository is the independent distribution boundary for `ep-edit`.

Maintain that boundary explicitly:

- package code must remain free of EP System runtime dependencies;
- this repository owns its standalone package metadata;
- standalone delivery tests verify standalone packaging assumptions;
- package-focused tests remain with the package;
- user-facing documentation uses standalone repository paths.

If maintaining independence ever appears to require changing core editing
semantics merely to separate `ep_edit` from another host application, treat
that as a boundary defect and investigate it rather than hiding the coupling
in packaging.

## Contributor rule

Keep the package generic, the CLI deterministic, and the publication path
fail-closed.

Standalone maintenance must preserve the generic package boundary and must
not introduce EP System coupling inside `ep_edit`.
