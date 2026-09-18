# ep-edit Agent Operating Contract

This file defines the default operating rules for coding agents working on
`ep-edit` or using `ep-edit` to modify another project.

## Default authoring route

For ordinary deterministic text editing, use:

    author Edit Specification
        ->
    ep-edit check
        ->
    ep-edit preview
        ->
    review exact proposed result
        ->
    ep-edit apply
        ->
    run relevant tests

Do not replace an exact-edit failure with fuzzy patching merely to make the
change succeed.

## Edit Specification

For new work, begin directly with a `FILE:` block.

`ep-edit` derives deterministic EditRefs from canonical semantic edit
identity.

Do not invent authored EditRefs.

`LABEL:` is optional display context for Humans and agents. It is excluded
from EditRef identity.

## Exact matching is authority

For partial SEARCH / REPLACE edits:

- SEARCH must match exactly once in the declared target;
- zero matches are failure;
- multiple matches are failure;
- overlapping edits are failure;
- repair candidates are diagnostic evidence only.

Do not:

- choose the nearest similarity candidate automatically;
- choose an occurrence by guess;
- switch to another file;
- widen the target root;
- normalize or rewrite whitespace merely to force a match;
- partially apply the rest of a failed Specification.

If exact planning fails, inspect the current target read-only and author a
corrected exact Specification.

## Preview is not approval

A successful `check` proves that the current Specification can be parsed,
planned, and validated under the current state.

It does not prove that the proposed change is semantically correct.

Before Apply, inspect the Actual Preview for at least:

- declared target paths;
- CREATE, REPLACE, or DELETE operation;
- exact inserted and removed content;
- warnings;
- validation results;
- newline and final-newline behavior where relevant;
- parent-directory creation where relevant.

Do not treat parser success, validation success, or an agent's own proposal
as Human approval.

## Interactive Apply

`ep-edit apply` renders the proposed result and asks:

`Apply these changes? [y/N]`

Only `y` and `yes`, case-insensitively, authorize interactive Apply.

A coding agent must not manufacture Human approval when the surrounding
workflow assigns approval to a Human operator.

If a higher-authority automation explicitly owns Apply authorization, follow
that workflow instead of inventing another approval model.

## Browser ChatGPT Clipboard workflow

When a Human uses browser ChatGPT and a shell controller captures an
LLM-authored payload with `pbpaste`, the controller must be running and
waiting before the Human copies that payload.

Required order:

    run controller
        ->
    controller stops at read -r
        ->
    Human copies only the intended payload
        ->
    Human presses Enter
        ->
    pbpaste captures the current Clipboard

The Clipboard is a mutable single transport slot.

Do not assume an Edit Specification remains on the Clipboard after another
command or payload has been copied.

For a review cycle, capture the Specification once into a saved file and use
that exact file for:

    check
        ->
    preview
        ->
    apply

See:

`docs/CHATGPT_COPY_PASTE_WORKFLOW.md`

## Failed Specification recovery

If parsing, planning, or exact preflight fails:

1. do not mutate target files;
2. inspect the exact current target state;
3. identify why the authored Specification does not match;
4. produce a fresh corrected exact Specification;
5. save it as a new authoring attempt;
6. rerun `check`;
7. rerun `preview`.

A failure such as `SEARCH_ZERO_MATCH` is not permission to adopt a
similarity candidate.

Repair metadata is advisory diagnostic output.

It never grants mutation authority.

## Valid Preview that needs changes

A separate case is:

    Specification is valid
        ->
    Preview is exact
        ->
    review decides the proposal itself should change

For this case, an explicit Revision Specification may be used with:

`ep-edit revise`

Revision modifies the saved Edit Specification draft only.

It does not modify target project files.

After revision, rerun `check` and `preview`.

Never reuse a Preview produced from earlier Specification bytes as authority
for revised bytes.

## Do not bypass a rejection

Do not fall back to uncontrolled mutation with tools such as:

- `sed -i`;
- one-off Python rewriting;
- Perl rewriting;
- unreviewed editor macros;
- fuzzy patch utilities;

merely because `ep-edit` rejected the authored operation.

A rejection means the proposed deterministic operation and the current
authority do not agree.

Repair the proposal or deliberately choose another editing workflow under
the target project's own rules.

## Whole-file operations

Whole-file operations are:

- `CREATE`;
- `REPLACE_FILE`;
- `DELETE`.

Representation directives may control newline style, final newline, and BOM
behavior where applicable.

### Missing-parent CREATE

A CREATE target may have missing parent directories.

`check` and `preview` must remain non-writing.

Do not pre-create missing parents merely to make Preview succeed.

During Apply, only directories created by that exact operation may become
rollback-owned.

Pre-existing directories are never rollback-owned.

Foreign state appearing during a race must not be silently adopted.

Cleanup may remove only safely removable Apply-created directories whose
identity still matches the operation that created them.

If secure publication primitives are unavailable on the platform, fail
closed rather than weakening the publication model.

## Generic package boundary

`ep_edit` is a generic editing package.

Do not introduce product-specific semantic dependencies merely to make one
consumer easier to edit.

In particular, standalone `ep_edit` must not depend on an application
package such as EP System.

Git is optional.

An LLM is optional.

ChatGPT is optional.

Aider is optional.

macOS `pbpaste` is only an optional Clipboard input provider.

## Public interface discipline

Treat the `ep-edit` CLI as the primary supported interface.

Do not make internal planner, publisher, or filesystem helpers part of the
stable public API merely because tests import them directly.

Internal-module imports in tests do not automatically define a public
library contract.

Keep the deliberately exported Python API small unless a separate public API
decision expands it.

## Testing after Apply

After an authorized Apply:

1. run focused tests for the changed behavior;
2. run relevant continuity tests;
3. run formatting or consistency checks required by the target project;
4. run broader regression at the target project's meaningful checkpoint.

Successful byte publication does not by itself prove semantic correctness.

## Documentation authority

For normal use, consult:

- `README.md` for the product overview and primary command surface;
- `docs/CLI_REFERENCE.md` for the exact public CLI contract;
- `docs/CHATGPT_COPY_PASTE_WORKFLOW.md` for browser-copy operation and
  authoring workspace lifecycle;
- `docs/EDIT_SPECIFICATION.md` for Specification and Revision grammar;
- `DEVELOPMENT.md` for contributor, test, packaging, and extraction
  boundaries.

When documentation and implementation appear inconsistent, do not silently
guess which behavior was intended.

Inspect the current implementation and tests, resolve the discrepancy, and
update the public documentation deliberately.
