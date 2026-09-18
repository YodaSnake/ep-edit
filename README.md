# ep-edit

`ep-edit` is a deterministic, review-first text editing CLI for Human,
ChatGPT, coding-agent, and automation workflows.

Its purpose is simple: apply only the exact edit that was authored and
reviewed. If the current file state does not support that exact edit,
`ep-edit` fails closed instead of guessing.

## Safety model

`ep-edit` provides:

- exact unique matching for partial edits;
- no fuzzy auto-apply;
- no nearest-match or occurrence guessing;
- no target switching;
- no partial Apply after planning failure;
- non-writing `check` and `preview`;
- explicit confirmation before interactive Apply;
- stale Specification and target-state revalidation;
- deterministic validation;
- handled-failure rollback;
- root-relative target boundaries;
- fail-closed symlink and unsafe-path handling;
- deterministic diagnostics for Human and LLM-assisted repair.

Repair candidates and repair metadata are diagnostic evidence only.
They never authorize mutation.

## Runtime independence

The editing core does not require:

- Git;
- ChatGPT or another LLM;
- Aider;
- an IDE;
- EP System.

The current runtime implementation uses the Python standard library.

The optional `--clipboard` input provider uses macOS `pbpaste`.

## Installation

`ep-edit` currently supports Python 3.12.

Install directly from GitHub with standard Python packaging tools.

Using `pip`:

```bash
python3.12 -m pip install "git+https://github.com/YodaSnake/ep-edit.git"
```

Using `uv` as an isolated command-line tool:

```bash
uv tool install "git+https://github.com/YodaSnake/ep-edit.git"
```

Then verify the installed command:

```bash
ep-edit --help
```

No Git installation is required at runtime after the package has been
installed. Git is only needed when installing directly from the Git
repository.

## Commands

The CLI surface is:

    ep-edit check [--root ROOT] SPECIFICATION
    ep-edit preview [--root ROOT] SPECIFICATION
    ep-edit apply [--root ROOT] SPECIFICATION
    ep-edit revise EDIT_SPECIFICATION REVISION_SPECIFICATION

For `check`, `preview`, and `apply`, the Specification may be supplied by:

- file path;
- `-` for standard input;
- `--clipboard` on macOS.

If `--root` is omitted, the current working directory is used.

## Recommended Human + ChatGPT workflow

For browser-based ChatGPT development, capture the authored Edit
Specification once into a saved file and reuse that same file.

Recommended sequence:

    author Specification
        ->
    save Specification
        ->
    check
        ->
    preview
        ->
    Human reviews Actual Preview
        ->
    apply
        ->
    tests

Do not repeatedly reconstruct the Specification from the live Clipboard
between `check`, `preview`, and `apply`.

The canonical browser-copy procedure is documented in:

`docs/CHATGPT_COPY_PASTE_WORKFLOW.md`

The important Clipboard rule is:

    start controller
        ->
    controller stops at read -r
        ->
    copy only the intended payload
        ->
    press Enter
        ->
    pbpaste captures that payload

The Clipboard is a mutable single transport slot. Copying another command
replaces the previously copied Specification.

## Edit Specification

An Edit Specification begins directly with a `FILE:` block.

`ep-edit` generates deterministic EditRefs instead of requiring the author
to invent edit identifiers.

An EditRef has the form:

`e_` followed by 16 lowercase hexadecimal characters.

`LABEL:` is optional human-readable review context and is not part of edit
identity.

Detailed syntax is documented in:

`docs/EDIT_SPECIFICATION.md`

## Supported operations

Partial editing uses an exact SEARCH payload and replacement payload.

Whole-file operations are:

- `CREATE`;
- `REPLACE_FILE`;
- `DELETE`.

Whole-file operations can explicitly control newline style, final-newline
state, and BOM behavior where applicable.

### Missing-parent CREATE

`CREATE` may target a file whose parent directories do not yet exist.

`check` and `preview` remain non-writing.

Required parent directories are established only during Apply.

Only safe empty directories created by that exact Apply operation are
eligible for rollback cleanup. Pre-existing or foreign directories are never
rollback-owned.

If the platform cannot provide the filesystem capabilities required for
secure no-follow, descriptor-relative publication, the operation fails
closed rather than weakening the safety model.

## Exact matching failures

For partial edits:

- zero exact matches fail with `SEARCH_ZERO_MATCH`;
- multiple exact matches fail with `SEARCH_MULTIPLE_MATCH`.

The CLI may return bounded same-target repair candidates.

Those candidates help an author understand the failure. They do not permit
automatic fuzzy editing.

Normal recovery is:

    failure
        ->
    inspect current target
        ->
    author corrected exact Specification
        ->
    check
        ->
    preview
        ->
    review
        ->
    apply

## Preview and approval

`check` parses, plans, and validates without changing targets.

`preview` additionally renders the complete planned result and remains
non-writing.

`apply` renders the Preview and asks:

`Apply these changes? [y/N]`

Only `y` and `yes`, case-insensitively, approve interactive Apply.

An empty answer, EOF, or keyboard interruption does not publish the target
changes.

## Revision

`ep-edit revise` changes a saved Edit Specification draft.

It does not modify the target project files.

After revising a draft, rerun `check` and `preview`. A previous Preview is
not authority for revised bytes.

Revision Specifications use deterministic EditRefs as selectors.

## Exit behavior

Successful CLI operations return exit code `0`.

Deterministic operational failures return exit code `1` and expose a stable
machine-readable error category such as:

- `INPUT_PARSE_ERROR`;
- `SEARCH_ZERO_MATCH`;
- `SEARCH_MULTIPLE_MATCH`;
- `EDIT_OVERLAP`;
- `VALIDATION_FAILED`;
- `STALE_SPECIFICATION`;
- `STALE_PREVIEW`;
- `APPLY_FAILED_ROLLED_BACK`;
- `ROLLBACK_FAILED`.

The complete behavior of individual error categories is documented in the
Specification reference rather than inferred from similarity diagnostics.

## Documentation

- `docs/CHATGPT_COPY_PASTE_WORKFLOW.md`
  - canonical browser ChatGPT and Terminal procedure;
  - `read -r` Clipboard handshake;
  - saved-Specification workflow;
  - failed authoring recovery.

- `docs/EDIT_SPECIFICATION.md`
  - Edit Specification grammar;
  - whole-file operations;
  - deterministic EditRef;
  - Revision Specification;
  - structural escaping;
  - repair diagnostics and error behavior.

- `docs/CLI_REFERENCE.md`
  - public `check`, `preview`, `apply`, and `revise` CLI contract;
  - input modes, approval, exit behavior, and platform boundaries.

- `DEVELOPMENT.md`
  - contributor and standalone extraction boundary;
  - package, test, metadata, and delivery responsibilities.

- `AGENTS.md`
  - default operating contract for coding agents.

## License

`ep-edit` is released under the MIT License. See `LICENSE`.
