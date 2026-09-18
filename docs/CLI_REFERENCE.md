# CLI Reference

This document describes the public command-line interface of `ep-edit`.

The CLI is the primary supported integration surface.

For Edit Specification grammar, EditRef identity, whole-file operations, and
Revision Specification grammar, see `EDIT_SPECIFICATION.md`.

For browser Clipboard capture and authoring workspace operation, see
`CHATGPT_COPY_PASTE_WORKFLOW.md`.

## Command overview

The command surface is:

    ep-edit check
    ep-edit preview
    ep-edit apply
    ep-edit revise

Top-level help describes the tool as deterministic exact text editing with a
preview-first interactive Apply workflow.

The common lifecycle is:

    author Specification
        ->
    check
        ->
    preview
        ->
    Human review
        ->
    apply

`revise` operates on a saved Specification draft and is separate from target
publication.

## check

Usage:

    ep-edit check [--clipboard] [--root ROOT] [specification]

`check`:

- reads the complete Edit Specification;
- parses it;
- plans all declared edits;
- runs applicable validation;
- does not render the full combined Preview;
- does not modify target files.

Successful output has the form:

    CHECK OK: N file(s), N edit(s), N warning(s), N validation PASS, N validation SKIPPED

A successful CHECK returns status 0.

A handled deterministic failure returns status 1.

CHECK acceptance is current-state evidence. If the Specification or target
state changes afterward, run CHECK again.

## preview

Usage:

    ep-edit preview [--clipboard] [--root ROOT] [specification]

`preview`:

- reads the complete Edit Specification;
- parses and plans it;
- runs validation;
- renders the combined concrete Preview;
- does not modify target files.

A Preview includes plan and target information such as:

- root display;
- target path;
- operation;
- EditRef or edit identities;
- before and after SHA-256 prefixes;
- changed-line counts;
- representation information where relevant;
- unified diff;
- warnings and validation results.

The displayed root and target paths use operator-facing path rendering rather
than intentionally exposing an absolute host path where that is unnecessary.

A successful Preview returns status 0.

A Preview is evidence for Human review. It is not publication approval by
itself.

## apply

Usage:

    ep-edit apply [--clipboard] [--root ROOT] [specification]

`apply` first builds and renders the same validated Preview path used for
review.

Only after that does it request explicit approval:

    Apply these changes? [y/N]

Approval is accepted only when the stripped response, case-insensitively, is:

    y

or:

    yes

Examples such as `Y`, `YES`, or surrounding whitespace therefore resolve to
approval.

Any other ordinary response declines publication.

## Declining Apply

A declined Apply prints:

    NOT APPLIED: approval declined.

and returns status 0.

Declining is intentionally a non-error result: the requested safety behavior
was to leave the targets unchanged.

An empty response also declines.

EOF while reading approval declines.

Keyboard interruption while reading approval also declines.

None of those cases authorizes a write.

## Approval input

For the default interactive reader, `ep-edit` first attempts to open:

    /dev/tty

for the approval prompt.

This keeps approval interaction separate from an Edit Specification that may
have arrived through stdin.

If opening `/dev/tty` fails, the CLI falls back to ordinary `input()`.

This approval mechanism is separate from Specification input selection.

## Specification input modes

`check`, `preview`, and `apply` support three Specification input modes:

1. saved file;
2. stdin using `-`;
3. macOS Clipboard using `--clipboard`.

Exactly one effective input source is required.

### Saved file

Example:

    ep-edit check --root . .ep-work/my-edit-v1/edit-spec.txt
    ep-edit preview --root . .ep-work/my-edit-v1/edit-spec.txt
    ep-edit apply --root . .ep-work/my-edit-v1/edit-spec.txt

A saved-file workflow is recommended for review-sensitive browser-assisted
authoring because the same bytes can be reused through CHECK, PREVIEW, and
APPLY.

If the Specification file cannot be read, the command fails closed with
`INPUT_PARSE_ERROR`.

### stdin

Use `-` as the Specification argument:

    cat edit-spec.txt | ep-edit check --root . -
    cat edit-spec.txt | ep-edit preview --root . -

The complete received stdin bytes are decoded once as the Specification
input.

For Apply, stdin Specification bytes are the received in-memory proposal;
there is no saved Specification path to re-read during publication.

### Clipboard

Use:

    ep-edit preview --root . --clipboard

`--clipboard` reads the complete current Clipboard value using the macOS
`pbpaste` command.

The Clipboard convenience path is therefore macOS-specific.

The file and stdin paths do not depend on `pbpaste`.

If `pbpaste` is unavailable, `--clipboard` fails closed with
`INPUT_PARSE_ERROR`.

If `pbpaste` itself returns failure, the command also fails closed with
`INPUT_PARSE_ERROR`.

`--clipboard` must not be combined with a Specification path.

Doing so fails with `INPUT_PARSE_ERROR`.

For Human + ChatGPT browser operation, prefer the durable capture procedure
documented in `CHATGPT_COPY_PASTE_WORKFLOW.md` rather than relying on a live
Clipboard value through the entire review cycle.

## Missing input

The Specification positional argument is syntactically optional so that
`--clipboard` can be used without it.

Operationally, one input source is required.

Running `check`, `preview`, or `apply` without:

- a Specification path;
- `-`; or
- `--clipboard`

fails with `INPUT_PARSE_ERROR`.

## Encoding

Edit Specification input must be valid UTF-8.

A UTF-8 BOM at the beginning of the Specification is not supported and fails
with `UNSUPPORTED_ENCODING`.

Invalid UTF-8 also fails with `UNSUPPORTED_ENCODING`.

Revision Specification input follows the same UTF-8 and no-BOM requirement.

## Target root

`check`, `preview`, and `apply` accept:

    --root ROOT

If `--root` is omitted, the current working directory is the target root.

If supplied, the explicit root is authoritative for the operation.

The CLI does not silently widen an explicit root because a target happens to
exist elsewhere.

A target that is not valid inside the selected root fails through the
deterministic planning or target-safety contract.

## Apply revalidation and stale state

Approval does not disable stale-state protection.

For a file-backed Specification, publication can recheck the saved
Specification identity.

If the saved Specification changes after Preview but before publication, the
operation fails with:

    STALE_SPECIFICATION

and the target is not changed by that stale proposal.

Target state is also revalidated.

If a target changes after Preview and the Preview no longer represents the
current before-state, Apply fails with:

    STALE_PREVIEW

rather than publishing against different target bytes.

This means:

    Preview
        ->
    Human approval
        ->
    revalidation
        ->
    publication

not:

    Preview
        ->
    approval permanently freezes authority

The reviewed proposal and the current publication state must still agree.

## Successful publication

When publication succeeds, Apply prints:

    APPLIED: N target(s).

and returns status 0.

Publication may still fail after approval if deterministic preconditions or
safe-publication guarantees no longer hold.

Such handled failures return status 1.

## revise

Usage:

    ep-edit revise specification revision

Both arguments are saved file paths.

`specification` is the saved Edit Specification draft to revise.

`revision` is the Revision Specification describing edits to that draft.

`revise` does not take `--root`.

It does not publish the resulting edits to project target files.

Instead, it revises the saved Specification draft itself.

After revision, run CHECK and PREVIEW again before any Apply.

## revise output

A successful revision reports the revised draft using operator-facing path
rendering:

    REVISED DRAFT: edit-spec.txt

It then reports identity information:

    Revised edits: ...
    Removed edits: ...
    Added edits: ...
    Specification fingerprint: ...

For v2 revisions that replace semantic edit identity, output also includes:

    Revised EditRefs: old_ref -> new_ref

When a category has no identifiers, the CLI renders:

    None

The Specification fingerprint identifies the revised draft bytes produced by
the revision workflow.

The draft is changed; repository target files named by that draft are not
changed by `revise`.

## Revision input failures

If the Revision Specification file cannot be read, the operation fails with
`REVISION_PARSE_ERROR`.

Malformed Revision Specification grammar also fails through the Revision
contract.

Unsupported or invalid encoding fails closed rather than being guessed.

See `EDIT_SPECIFICATION.md` for Revision grammar and EditRef selectors.

## Exit behavior

The core command result contract is:

| Situation | Result |
| --- | --- |
| successful CHECK | 0 |
| successful PREVIEW | 0 |
| successful APPLY | 0 |
| explicit or default Apply decline | 0 |
| EOF during Apply approval | 0, not applied |
| keyboard interrupt during Apply approval | 0, not applied |
| successful REVISE | 0 |
| handled deterministic edit failure | 1 |
| handled preflight failure | 1 |
| handled filesystem failure at the CLI boundary | 1 |

Argument syntax and subcommand usage errors are handled by Python's argument
parser before the normal deterministic command body proceeds.

Scripts should distinguish a successful no-op approval decline from an error
by reading the command output when that distinction matters.

In particular:

    NOT APPLIED: approval declined.

means publication did not happen even though the command result is successful.

## Error rendering

A handled deterministic failure is written to stderr in the form:

    ERROR CODE: message

Preflight failures may contain multiple numbered diagnostics followed by
machine-readable repair metadata.

Those diagnostics do not authorize mutation.

Examples include exact-match failures such as:

- `SEARCH_ZERO_MATCH`;
- `SEARCH_MULTIPLE_MATCH`;
- `EDIT_OVERLAP`.

The tool may show bounded candidates or exact occurrence information to help
author a corrected Specification, but Apply does not automatically select a
candidate.

## IO failure boundary

Unwrapped filesystem failures reaching the top CLI boundary are normalized
to:

    ERROR IO_ERROR: filesystem operation failed

with status 1.

More specific input and revision read failures are converted earlier to their
deterministic input or revision error categories.

## Non-writing command boundary

These commands do not publish target changes:

    ep-edit check
    ep-edit preview

`ep-edit revise` writes only the saved Specification draft it was asked to
revise.

Target publication belongs to:

    ep-edit apply

and only after validated Preview plus explicit approval.

## Recommended browser-assisted usage

For a durable Human + ChatGPT workflow:

    capture complete Specification into workspace
        ->
    verify saved bytes
        ->
    ep-edit check --root . "$SPEC"
        ->
    ep-edit preview --root . "$SPEC"
        ->
    Human accepts exact Preview
        ->
    ep-edit apply --root . "$SPEC"

The same completed saved Specification should be used for all three commands
in one accepted review cycle.

If CHECK fails or Preview is rejected:

    preserve current workspace
        ->
    create fresh versioned workspace
        ->
    correct or recompose Specification
        ->
    CHECK again
        ->
    PREVIEW again

Do not treat an old Preview as approval for newly composed bytes.

## Platform boundary

The core file/stdin authoring path does not require `pbpaste`.

The `--clipboard` convenience option does.

Missing-parent CREATE publication additionally depends on secure filesystem
capabilities required by the publication implementation. If those required
capabilities are unavailable, publication fails closed rather than silently
using a weaker path.

The CLI documentation therefore does not claim that every optional workflow
has identical behavior on every operating system.

## Related documentation

- `../README.md` — product overview and starting point.
- `EDIT_SPECIFICATION.md` — Edit and Revision grammar.
- `CHATGPT_COPY_PASTE_WORKFLOW.md` — browser Clipboard capture, multi-part
  transport, workspace lifecycle, and same-Specification review workflow.
- `../AGENTS.md` — agent-facing authoring and safety rules.

## Contract summary

`ep-edit` is CLI-first.

The supported operating model is:

- exact authored operation;
- explicit target root;
- deterministic planning;
- non-writing CHECK;
- non-writing PREVIEW;
- Human-approved APPLY;
- stale-state revalidation;
- fail-closed publication;
- explicit saved-draft revision.

The CLI applies the reviewed deterministic proposal or reports why it cannot.

It does not guess a different edit.
