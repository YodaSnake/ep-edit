# Edit Specification Reference

This document describes the public authoring grammar used by `ep-edit`.

The authoring grammar is unversioned. Edit Specifications begin directly
with `FILE:` blocks, and Revision Specifications begin directly with revision
operations.

## Authoring model

An Edit Specification describes one or more deterministic text mutations.

The Specification identifies:

- the declared target;
- the exact operation;
- the semantic payload;
- representation directives where applicable.

The Specification does not authorize fuzzy matching or target discovery.

Planning succeeds only when the declared operation is valid against the
current target state.

## Edit Specification

A Specification contains one or more `FILE:` blocks.

The first non-blank line is therefore normally a `FILE:` declaration.

A basic SEARCH / REPLACE edit is:

    FILE: src/example.py
    LABEL: update example

    <<<<<<< SEARCH
    old_value = 1
    =======
    old_value = 2
    >>>>>>> REPLACE

`LABEL:` is optional.

There is no authored `EDIT:` line.

If an `EDIT:` line is present, parsing fails with `INPUT_PARSE_ERROR`.

## FILE target

Each edit begins with:

    FILE: relative/path/to/file.txt

The target is normalized as a root-relative path and must satisfy the
tool's target-path safety rules.

`ep-edit` does not use a failed target as permission to search for another
file.

## LABEL

An optional `LABEL:` may appear immediately after `FILE:`.

Example:

    FILE: src/example.py
    LABEL: update parser error handling

A LABEL:

- must not be empty;
- must not contain NUL;
- is intended for Human and agent review;
- is not part of deterministic EditRef identity.

Changing only the LABEL therefore leaves the EditRef unchanged.

## SEARCH / REPLACE

The partial-edit form is:

    FILE: path/to/file.txt
    LABEL: optional description

    <<<<<<< SEARCH
    exact old text
    =======
    exact new text
    >>>>>>> REPLACE

SEARCH must contain at least one logical line.

REPLACE may be empty when the intended operation is deletion of the matched
SEARCH text.

The planner requires SEARCH to identify exactly one eligible location in the
declared target.

Zero exact matches fail with `SEARCH_ZERO_MATCH`.

Multiple exact matches fail with `SEARCH_MULTIPLE_MATCH`.

Overlapping planned edits fail with `EDIT_OVERLAP`.

Blank lines inside SEARCH and REPLACE are semantic payload and therefore
matter to exact matching.

Similarity diagnostics do not change these rules.

## Deterministic EditRef

`ep-edit` generates an EditRef for every edit.

The public form is:

    e_0123456789abcdef

That is `e_` followed by 16 lowercase hexadecimal characters.

The current identity schema is:

    ep-edit-ref-v1

The implementation canonicalizes the semantic identity payload as JSON using
UTF-8, sorted keys, and compact separators, hashes it with SHA-256, and uses
the first 16 hexadecimal digest characters.

SEARCH / REPLACE identity includes the target, operation, decoded SEARCH
lines, and decoded REPLACE lines.

Whole-file identity includes the target, operation, decoded CONTENT where
applicable, and the resolved representation directives.

LABEL is excluded.

Changing semantic content can therefore change the EditRef even when the
Human-facing label does not.

Two identical semantic edits in one Specification generate the same EditRef
and fail closed with `DUPLICATE_EDIT_REF`.

## Whole-file operations

The supported whole-file modes are:

- `CREATE`;
- `REPLACE_FILE`;
- `DELETE`.

A whole-file block begins with `MODE:` instead of `<<<<<<< SEARCH`.

Representation directives, when allowed, appear between `MODE:` and
`<<<<<<< CONTENT`.

The available directive values are:

| Directive | Values |
| --- | --- |
| `NEWLINE` | `LF`, `CRLF`, `PRESERVE` |
| `FINAL_NEWLINE` | `YES`, `NO`, `PRESERVE` |
| `BOM` | `YES`, `NO`, `PRESERVE` |

Each directive may appear at most once in a whole-file block.

## CREATE

Example:

    FILE: generated/example.txt
    LABEL: create example
    MODE: CREATE
    NEWLINE: LF
    FINAL_NEWLINE: YES
    BOM: NO
    <<<<<<< CONTENT
    created content
    >>>>>>> CONTENT

CREATE defaults are:

| Directive | CREATE default |
| --- | --- |
| `NEWLINE` | `LF` |
| `FINAL_NEWLINE` | `YES` |
| `BOM` | `NO` |

`PRESERVE` is invalid for CREATE because no prior file representation exists
to preserve.

The CONTENT payload may be empty.

A CREATE target must satisfy CREATE preflight requirements.

If the target already exists, CREATE fails rather than changing operation
type automatically.

### Missing parent directories

A CREATE target may name a file beneath parent directories that do not yet
exist.

CHECK and PREVIEW remain non-writing.

The parent chain is planned during authoring and is established only during
authorized Apply.

Only safe directories created by that exact Apply operation are eligible for
rollback cleanup.

Pre-existing directories are not rollback-owned.

If required secure no-follow, descriptor-relative publication capabilities
are unavailable, missing-parent publication fails closed rather than using a
weaker compatibility path.

## REPLACE_FILE

Example:

    FILE: config/example.txt
    MODE: REPLACE_FILE
    NEWLINE: LF
    FINAL_NEWLINE: NO
    BOM: NO
    <<<<<<< CONTENT
    complete replacement
    >>>>>>> CONTENT

REPLACE_FILE defaults are:

| Directive | REPLACE_FILE default |
| --- | --- |
| `NEWLINE` | `PRESERVE` |
| `FINAL_NEWLINE` | `PRESERVE` |
| `BOM` | `PRESERVE` |

Explicit values may override those defaults.

REPLACE_FILE is a whole-file operation. It is not a fuzzy fallback for a
failed SEARCH / REPLACE edit.

## DELETE

DELETE contains no CONTENT and no representation directives.

Example:

    FILE: obsolete.txt
    LABEL: remove obsolete file
    MODE: DELETE

Adding `NEWLINE`, `FINAL_NEWLINE`, `BOM`, or CONTENT to DELETE is a parse
error.

## Mixing operations for one target

A target may contain multiple partial SEARCH / REPLACE edits when those edits
can be planned deterministically.

A target must not combine a whole-file edit with additional edits for that
same target.

Such an operation mix fails during Specification validation rather than
defining an implicit order.

## Revision Specifications

`ep-edit revise` transforms a saved Edit Specification draft.

It does not mutate repository target files.

Command shape:

    ep-edit revise EDIT_SPECIFICATION REVISION_SPECIFICATION

After revision, rerun `check` and `preview`.

An earlier Preview does not authorize revised Specification bytes.

## Revision Specification

A Revision Specification begins directly with a revision operation.

The supported operations are:

- `REVISE_EDIT`;
- `REMOVE_EDIT`;
- `ADD_EDIT`.

### REVISE_EDIT

`REVISE_EDIT` selects an existing generated EditRef.

Example:

    REVISE_EDIT: e_0123456789abcdef

    <<<<<<< EDIT
    FILE: src/example.py
    LABEL: revised example

    <<<<<<< SEARCH
    old_value = 1
    =======
    old_value = 3
    >>>>>>> REPLACE
    >>>>>>> EDIT

The embedded block begins directly with `FILE:` and must describe exactly
one valid edit.

The selector is the old EditRef.

The replacement block derives its own EditRef from its semantic content.

A semantic revision may therefore map:

    old EditRef -> new EditRef

A LABEL-only revision keeps the same EditRef because LABEL is excluded from
identity.

A revision may also change the target. That produces identity according to
the replacement block rather than preserving the old EditRef artificially.

### REMOVE_EDIT

REMOVE uses an existing generated EditRef and has no embedded edit block.

Example:

    REMOVE_EDIT: e_0123456789abcdef

The selector must have generated EditRef form.

A Human-authored arbitrary name is not accepted as a selector.

### ADD_EDIT

ADD has no authored identifier after the colon.

Example:

    ADD_EDIT:

    <<<<<<< EDIT
    FILE: src/new.py

    <<<<<<< SEARCH
    old()
    =======
    new()
    >>>>>>> REPLACE
    >>>>>>> EDIT

The added edit identity is derived from the embedded block.

This is invalid:

    ADD_EDIT: authored-name

because the author does not assign an EditRef.

### Duplicate revision targets

The same EditRef must not be targeted more than once in one Revision
Specification.

Duplicate targeting fails with `REVISION_DUPLICATE_TARGET`.

The same generated EditRef must also not be added more than once.

## Structural escaping

Edit Specification syntax uses structural delimiter lines.

A payload that needs to contain one of those lines literally must escape it.

The reserved payload markers are context-specific.

| Payload context | Reserved semantic lines |
| --- | --- |
| SEARCH | `=======`, `>>>>>>> REPLACE` |
| REPLACE | `>>>>>>> REPLACE` |
| CONTENT | `>>>>>>> CONTENT` |
| outer Revision EDIT block | `>>>>>>> EDIT` |

The canonical escape operation adds one leading backslash to a payload line
that would otherwise be interpreted as a structural marker.

For example, to put this semantic line inside SEARCH:

    =======

author:

    \=======

To put this semantic line inside REPLACE:

    >>>>>>> REPLACE

author:

    \>>>>>>> REPLACE

The parser removes the structural escape and restores the intended semantic
payload line.

Ordinary leading backslashes that do not form an escaped reserved marker are
left unchanged.

If the semantic line already begins with backslashes immediately before a
reserved marker, the encoder adds one additional protective backslash so the
existing semantic backslashes survive decoding.

## Nested Revision escaping

A Revision Specification introduces an additional outer `<<<<<<< EDIT` /
`>>>>>>> EDIT` grammar layer.

Escaping is interpreted by the grammar layer in which a delimiter would
otherwise be structural.

This matters when an embedded edit itself contains text resembling either an
Edit Specification delimiter or a Revision delimiter.

Do not remove escape prefixes merely because the rendered text looks like a
delimiter.

Use the encoded form required by each enclosing parser layer.

EditRef identity is calculated from decoded semantic content, not from the
protective escape bytes used to transport structural-looking lines.

## Parsing and deterministic failure

Malformed syntax fails closed.

Important Specification and Revision parsing categories include:

- `INPUT_PARSE_ERROR`;
- `DUPLICATE_EDIT_REF`;
- `UNSUPPORTED_ENCODING`;
- `REVISION_PARSE_ERROR`;
- `REVISION_DUPLICATE_TARGET`;
- `REVISION_EDIT_NOT_FOUND`;
- `REVISION_EDIT_ALREADY_EXISTS`;
- `REVISION_BASE_NOT_FOUND`.

Planning and publication can additionally surface deterministic categories
such as:

- `SEARCH_ZERO_MATCH`;
- `SEARCH_MULTIPLE_MATCH`;
- `EDIT_OVERLAP`;
- `NO_CHANGE`;
- `TARGET_ALREADY_EXISTS`;
- `TARGET_NOT_FOUND`;
- `TARGET_OUTSIDE_ROOT`;
- `TARGET_SYMLINK`;
- `TARGET_HARDLINK`;
- `TARGET_NOT_REGULAR_FILE`;
- `UNSUPPORTED_NEWLINE`;
- `VALIDATION_FAILED`;
- `STALE_SPECIFICATION`;
- `STALE_PREVIEW`;
- `PREVIEW_RENDER_ERROR`;
- `APPLY_FAILED_ROLLED_BACK`;
- `APPLY_CLEANUP_FAILED`;
- `POST_APPLY_VERIFY_FAILED`;
- `ROLLBACK_FAILED`.

The error code identifies the deterministic failure category.

Human-readable messages and repair metadata explain the current failure but
do not grant permission to select a different mutation.

## Repair diagnostics

Some preflight failures expose bounded repair information.

Examples include:

- same-target similarity candidates for `SEARCH_ZERO_MATCH`;
- exact occurrence ranges for `SEARCH_MULTIPLE_MATCH`;
- deterministic `ep-edit-repair-v1` machine-readable metadata.

These diagnostics are read-only.

They must not be interpreted as:

- automatic fuzzy-match authority;
- nearest-candidate selection;
- occurrence selection;
- permission to switch targets;
- permission to partially Apply unaffected edits.

Normal recovery is:

    deterministic failure
        ->
    inspect current target state
        ->
    author corrected exact Specification
        ->
    check
        ->
    preview
        ->
    Human review
        ->
    apply

## CHECK, PREVIEW, and APPLY relationship

A syntactically valid Specification is not automatically authorized for
publication.

`check` is non-writing and establishes current parse, planning, and
validation acceptance.

`preview` is non-writing and renders the concrete proposed mutation.

`apply` performs its own review/revalidation path before publication.

For browser-assisted Human workflows, capture one complete Specification
into a saved file and reuse that same file for:

    ep-edit check --root . "$SPEC"
    ep-edit preview --root . "$SPEC"
    ep-edit apply --root . "$SPEC"

For large browser payloads, multiple Clipboard chunks may be concatenated
first, but only the final concatenated Specification is submitted to
`ep-edit`.

See:

`CHATGPT_COPY_PASTE_WORKFLOW.md`

for the canonical `read -r`, multi-part capture, hashing, boundary-check,
Preview, and same-Specification Apply procedure.

## Authoring recommendations

For new work:

1. use root-relative target paths;
2. use the smallest exact SEARCH block that is unique;
3. preserve meaningful blank lines exactly;
4. use LABEL for review context, not identity;
5. use whole-file modes only when the whole-file operation is intentional;
6. use structural escaping when literal payload lines collide with grammar
   delimiters;
7. treat repair metadata as evidence, not mutation authority;
8. rerun CHECK and PREVIEW after any revision;
9. apply only the exact saved Specification that was reviewed.

The core rule is simple:

`ep-edit` applies the authored deterministic operation or fails closed.

It does not guess a different edit.
