# ChatGPT Copy/Paste Workflow

This guide defines the recommended Human + browser ChatGPT + Terminal
operating procedure for `ep-edit`.

The CLI makes repository editing deterministic, but a Human may still need
to transfer LLM-authored text from a browser into the local environment.

That transfer is part of the workflow and must be handled deliberately.

## Core Clipboard rule

When a shell controller will capture ChatGPT-authored content with
`pbpaste`, the controller must already be running and stopped at `read -r`
before the Human copies the payload.

Required order:

    run controller
        ->
    controller reaches read -r
        ->
    Human copies only the intended payload
        ->
    Human presses Enter
        ->
    controller executes pbpaste
        ->
    payload is saved

Do not reverse this order.

## Why `read -r` matters

The system Clipboard is one mutable transport slot.

It is not a durable history of everything copied earlier.

For example, this sequence is unsafe:

    copy Edit Specification
        ->
    copy shell command
        ->
    shell later executes pbpaste

At the time `pbpaste` executes, the Clipboard contains the shell command,
not the earlier Edit Specification.

The result may be a parsing failure such as `INPUT_PARSE_ERROR`.

`ep-edit` should fail closed rather than treating those bytes as edit
authority, but the authoring attempt still has to be repeated.

An explicit `read -r` creates an ordered Human/Terminal handshake.

The Terminal visibly waits before the Human copies the payload that will be
captured next.

## Small-payload workflow

For a Specification that comfortably fits in one ChatGPT code block, a
controller can use this form:

    WORK=".ep-work/my-edit-v1"
    SPEC="$WORK/edit-spec.txt"
    rc=0

    mkdir -p "$WORK"

    printf '\nCopy only the Edit Specification, then press Enter.\n'
    read -r

    pbpaste > "$SPEC" || rc=$?

    if (( rc == 0 )); then
      ep-edit check --root . "$SPEC" || rc=$?
    fi

    if (( rc == 0 )); then
      ep-edit preview --root . "$SPEC" || rc=$?
    fi

    printf '\nrc=%s\n' "$rc"

The exact workspace name is not important.

The important order is:

    controller already running
        ->
    explicit operator stop
        ->
    payload copy
        ->
    capture

## What to copy

Copy only the complete Edit Specification payload.

Do not include:

- explanatory prose outside the Specification;
- a shell controller block;
- unrelated Markdown;
- another assistant response;
- an older failed Specification.

For new authoring, the payload should normally begin directly with a
`FILE:` block:

`FILE: relative/path/to/file.txt`

## Save once, reuse one Specification

After capture, the saved Specification becomes the stable authoring artifact
for that review cycle.

Use the same saved file for:

    ep-edit check --root . "$SPEC"
    ep-edit preview --root . "$SPEC"
    ep-edit apply --root . "$SPEC"

Do not reconstruct the Specification from the live Clipboard between those
steps.

The target filesystem remains the before-state authority.

The saved Specification is the stable proposed-edit payload used by CHECK,
PREVIEW, Human review, and APPLY.

## CHECK

`ep-edit check` is non-writing.

It parses the Specification, plans the requested edits against current target
state, and runs deterministic validation.

A successful CHECK means the current Specification can be deterministically
planned under the current state.

It does not mean the proposed change is semantically correct.

It does not authorize Apply.

## PREVIEW

`ep-edit preview` is also non-writing.

It renders the actual proposed mutation.

Review at least:

- target path;
- operation type;
- generated EditRef;
- inserted content;
- removed content;
- warnings;
- validation result;
- newline behavior where relevant;
- parent-directory creation where relevant.

If the proposed result is wrong, do not Apply it.

## APPLY

After accepting the exact Preview, run Apply against the same saved
Specification.

For example:

    SPEC=".ep-work/my-edit-v1/edit-spec.txt"
    rc=0

    ep-edit apply --root . "$SPEC" || rc=$?

    printf '\nrc=%s\n' "$rc"

`apply` renders its own Preview and asks:

`Apply these changes? [y/N]`

Only `y` and `yes`, case-insensitively, authorize interactive Apply.

An empty response, EOF, or keyboard interruption does not publish the target
changes.

Do not recopy the Specification immediately before Apply.

Use the same saved file that was checked and reviewed.

## Stable review identity

The saved-file workflow ensures that:

    authored bytes
        ->
    checked bytes
        ->
    previewed bytes
        ->
    submitted Apply bytes

refer to one stable payload.

If a file-backed Specification changes after Preview, stale revalidation can
reject it rather than silently applying different bytes.

If target state changes after Preview, publication similarly fails closed
instead of automatically adapting.

## Large-payload workflow

A large Specification does not need to fit in one ChatGPT code block.

Split the transport into multiple Clipboard chunks.

For example:

    part-01.txt
    part-02.txt
    part-03.txt
        ->
    deterministic concatenation
        ->
    edit-spec.txt
        ->
    check
        ->
    preview
        ->
    apply

Each chunk is only a transport artifact.

No individual chunk is an Edit Specification authority.

Only the completed concatenated `edit-spec.txt` is submitted to `ep-edit`.

A three-part controller can use this shape:

    WORK=".ep-work/my-large-edit-v1"
    PART1="$WORK/part-01.txt"
    PART2="$WORK/part-02.txt"
    PART3="$WORK/part-03.txt"
    SPEC="$WORK/edit-spec.txt"
    rc=0

    mkdir -p "$WORK"

    printf '\nPART 1: copy payload, then press Enter.\n'
    read -r
    pbpaste > "$PART1" || rc=$?

    if (( rc == 0 )); then
      printf '\nPART 2: copy payload, then press Enter.\n'
      read -r
      pbpaste > "$PART2" || rc=$?
    fi

    if (( rc == 0 )); then
      printf '\nPART 3: copy payload, then press Enter.\n'
      read -r
      pbpaste > "$PART3" || rc=$?
    fi

    if (( rc == 0 )); then
      cat "$PART1" "$PART2" "$PART3" > "$SPEC" || rc=$?
    fi

    if (( rc == 0 )); then
      ep-edit check --root . "$SPEC" || rc=$?
    fi

    if (( rc == 0 )); then
      ep-edit preview --root . "$SPEC" || rc=$?
    fi

    printf '\nrc=%s\n' "$rc"

This separates:

    ChatGPT display / Clipboard transport size

from:

    logical Edit Specification size

A long Specification can therefore be transported as many small chunks as
needed without weakening the deterministic review model.

## Canonical multi-part browser controller

For browser-based ChatGPT work, the following is the recommended complete
pattern when one logical Edit Specification is too large for one convenient
code block.

The Human copies and runs the controller once.

The controller then remains active and explicitly stops before every
Clipboard capture.

Example with three payload chunks:

    WORK=".ep-work/my-large-edit-v1"
    PART1="$WORK/part-01.txt"
    PART2="$WORK/part-02.txt"
    PART3="$WORK/part-03.txt"
    SPEC="$WORK/edit-spec.txt"
    rc=0

    mkdir -p "$WORK"

    printf '\n=== PART 1 / 3 ===\n'
    printf 'Copy PART 1 only, then press Enter.\n'
    read -r
    pbpaste > "$PART1" || rc=$?

    if (( rc == 0 )); then
      printf '\n=== PART 2 / 3 ===\n'
      printf 'Copy PART 2 only, then press Enter.\n'
      read -r
      pbpaste > "$PART2" || rc=$?
    fi

    if (( rc == 0 )); then
      printf '\n=== PART 3 / 3 ===\n'
      printf 'Copy PART 3 only, then press Enter.\n'
      read -r
      pbpaste > "$PART3" || rc=$?
    fi

    if (( rc == 0 )); then
      printf '\n=== CONCATENATE COMPLETE SPECIFICATION ===\n'
      cat "$PART1" "$PART2" "$PART3" > "$SPEC" || rc=$?
    fi

    if (( rc == 0 )); then
      printf '\n=== PART IDENTITIES ===\n'
      wc -c "$PART1" "$PART2" "$PART3" "$SPEC"
      shasum -a 256 "$PART1" "$PART2" "$PART3" "$SPEC"

      printf '\n=== SPECIFICATION BOUNDARY CHECK ===\n'
      head -n 5 "$SPEC"
      printf '\n--- tail ---\n'
      tail -n 5 "$SPEC"

      awk 'NF { found=1; exit($0 !~ /^FILE: /) } END { if (!found) exit 1 }' \
        "$SPEC" || rc=$?
    fi

    if (( rc == 0 )); then
      printf '\n=== CHECK ===\n'
      ep-edit check --root . "$SPEC" || rc=$?
    fi

    if (( rc == 0 )); then
      printf '\n=== ACTUAL PREVIEW ===\n'
      ep-edit preview --root . "$SPEC" || rc=$?
    fi

    printf '\n=== PRE-APPLY RESULT ===\n'
    printf 'rc=%s\n' "$rc"

The Human interaction for this controller is:

    1. Copy the controller block.
    2. Run it once in the Terminal.
    3. Wait until `PART 1 / 3` is displayed.
    4. Copy only ChatGPT's PART 1 block.
    5. Press Enter.
    6. Wait until `PART 2 / 3` is displayed.
    7. Copy only PART 2.
    8. Press Enter.
    9. Wait until `PART 3 / 3` is displayed.
    10. Copy only PART 3.
    11. Press Enter.
    12. Let the controller concatenate the parts.
    13. Review byte counts, hashes, and file boundaries.
    14. Let `ep-edit check` operate on the completed Specification.
    15. Let `ep-edit preview` operate on that same completed Specification.
    16. Review the Actual Preview.
    17. Apply later using that same completed Specification file.

The controller itself is copied only once.

After it starts, each additional browser Copy action is reserved for the
payload that corresponds to the currently displayed `read -r` stop.

This is preferable to repeatedly copying shell commands between payload
captures because every extra Copy would replace the Clipboard content.

### Transport chunks are not edit authority

`part-01.txt`, `part-02.txt`, and `part-03.txt` are transport fragments.

They are useful for:

- avoiding browser code-block size problems;
- reducing the amount that must be recopied after a truncated block;
- preserving evidence of each transferred payload;
- checking chunk ordering and identity.

They must not be passed independently to `ep-edit`.

Only the concatenated `edit-spec.txt` is the logical Edit Specification used
for deterministic planning and review.

### Verify concatenation before CHECK

Before the completed file reaches `ep-edit`, inspect at least:

- byte count for every chunk;
- byte count for the completed Specification;
- SHA-256 identity of every chunk;
- SHA-256 identity of the completed Specification;
- the beginning of the completed file;
- the end of the completed file;
- the expected Specification version header.

These checks are especially valuable when a browser UI may truncate a long
code block.

A missing final delimiter, duplicated chunk, wrong chunk order, or incomplete
copy can then be discovered before the completed payload is treated as a
Specification.

`ep-edit check` remains the parser and deterministic planning authority after
transport verification.

### Apply must reuse the concatenated file

After an accepted Preview, do not rebuild the Specification from the
individual chunks and do not return to the live Clipboard.

Use the already reviewed completed file:

    SPEC=".ep-work/my-large-edit-v1/edit-spec.txt"
    rc=0

    ep-edit apply --root . "$SPEC" || rc=$?

    printf '\nrc=%s\n' "$rc"

The intended identity chain is therefore:

    ChatGPT payload chunks
        ->
    separately captured part files
        ->
    deterministic concatenation
        ->
    one completed Specification
        ->
    check
        ->
    preview
        ->
    Human review
        ->
    apply the same completed Specification

This separates transport mechanics from mutation authority.

## Chunk boundary discipline

Split chunks only at ordinary text boundaries.

Prefer boundaries between complete lines or sections.

Do not intentionally split:

- a structural delimiter token;
- a version declaration;
- a target path;
- a representation directive;
- another syntax element whose bytes must remain contiguous.

The controller should preserve each captured chunk exactly and concatenate
them in explicit numeric order.

`cat` performs byte concatenation. It does not invent a newline, blank line,
or other separator at a chunk boundary.

The composition step must therefore distinguish between:

- a pure transport split inside one continuous byte stream; and
- an intentional section boundary that requires separator bytes.

For a pure transport split, concatenate the chunks without inserting bytes
that were not part of the intended Specification.

For section-aligned chunks, an explicit separator may be inserted when that
separator is part of the intended final bytes.

For example:

    {
      cat "$WORK/part-01.txt"
      printf '\n'
      cat "$WORK/part-02.txt"
    } > "$SPEC"

is appropriate only when the intended completed Specification actually needs
that newline between those sections.

Do not add newline separators blindly to arbitrary SEARCH, REPLACE, CONTENT,
or other semantic payload fragments. Extra bytes there change the authored
edit.

For review-sensitive work, it is useful to print:

- byte counts;
- hashes for each chunk;
- hash for the completed Specification;
- beginning and end of the concatenated file.

This helps detect a missing, duplicated, or incorrectly ordered chunk before
the Specification reaches `ep-edit`.

## One `read -r` per Clipboard payload

For multiple payloads, every Clipboard capture gets its own explicit stop:

    stop
        ->
    copy payload A
        ->
    capture A

    stop
        ->
    copy payload B
        ->
    capture B

    stop
        ->
    copy payload C
        ->
    capture C

Never assume several previously copied browser payloads can later be
recovered from Clipboard history.

`pbpaste` reads only the Clipboard value that exists at capture time.

## Failed CHECK recovery

If CHECK reports `SEARCH_ZERO_MATCH`, `SEARCH_MULTIPLE_MATCH`,
`EDIT_OVERLAP`, or another deterministic planning failure, do not mutate
targets.

Inspect the exact current target state first.

Then author a corrected Specification.

Recommended sequence:

    failed Specification
        ->
    read-only target inspection
        ->
    identify exact mismatch
        ->
    create fresh corrected Specification
        ->
    check
        ->
    preview

A `SEARCH_ZERO_MATCH` is not permission to choose the most similar candidate.

## Authoring workspace lifecycle

A browser-assisted authoring workflow should keep transient transport and
review artifacts in an explicit workspace.

A common layout is:

    .ep-work/my-edit-v1/
        part-01.txt
        part-02.txt
        part-03.txt
        edit-spec.txt

The exact directory name is project policy. `.ep-work` is the convention used
in this guide.

The important distinction is authority:

- target project files are the current before-state being edited;
- `part-*.txt` files are Clipboard transport artifacts and diagnostic evidence;
- the completed `edit-spec.txt` is the stable proposed-edit artifact for one
  review cycle;
- CHECK and PREVIEW outputs are evidence about that completed Specification;
- workspace artifacts do not replace the target project's source of truth.

Individual part files are not mutation authority.

Only the completed Specification is submitted to `ep-edit check`,
`ep-edit preview`, and later `ep-edit apply`.

### Fresh workspaces after failed or rejected authoring

When an authoring attempt fails or its Preview is rejected, prefer a fresh
versioned workspace.

The normal lifecycle is:

    create v1 workspace
        ->
    capture payload or chunks
        ->
    compose edit-spec.txt
        ->
    check
        ->
    preview
        |
        +-- accepted
        |     ->
        |   apply the same edit-spec.txt
        |
        +-- failed or rejected
              ->
            preserve v1
              ->
            create v2 workspace
              ->
            corrected composition
              ->
            check
              ->
            preview

The failed or rejected workspace should normally remain unchanged while the
problem is diagnosed.

A fresh workspace makes it explicit which Specification bytes produced which
CHECK and Preview results.

An old Preview does not authorize a newly composed Specification.

### Reusing known-good transport chunks

A fresh workspace does not require recopying every chunk when the captured
chunk bytes themselves are known to be correct.

For example, if only the composition boundary was wrong, the preserved part
files may be copied into a fresh workspace and recomposed there:

    v1/part-01.txt
    v1/part-02.txt
        ->
    preserve v1
        ->
    copy known-good parts into v2
        ->
    compose v2/edit-spec.txt
        ->
    verify bytes, hashes, and boundaries
        ->
    check
        ->
    preview

The newly composed `edit-spec.txt` has its own identity and begins a new
review cycle even when most transport chunks were reused.

For example:

    .ep-work/my-edit-v1/
        failed Specification

    .ep-work/my-edit-v2/
        corrected Specification

Do not silently overwrite evidence from the failed attempt while diagnosing
why it failed.

This is especially useful when a mismatch came from:

- omitted blank lines;
- indentation differences;
- stale target content;
- an incomplete Clipboard capture;
- a truncated browser code block.

## Repair diagnostics are not authority

`ep-edit` may return bounded read-only diagnostics such as:

- same-target similarity candidates for `SEARCH_ZERO_MATCH`;
- exact occurrence ranges for `SEARCH_MULTIPLE_MATCH`;
- machine-readable `ep-edit-repair-v1` metadata.

These outputs help a Human or LLM understand the failure.

They do not authorize:

- fuzzy matching;
- automatic candidate selection;
- automatic occurrence selection;
- target switching;
- partial Apply.

Use them to author a new exact Specification.

## Valid Preview that needs revision

A different case is:

    Specification is valid
        ->
    Preview is exact
        ->
    Human decides the proposed edit itself should change

An explicit Revision Specification may then be used with:

`ep-edit revise`

Revision changes the saved Edit Specification draft only.

It does not modify target project files.

After revision:

    check again
        ->
    preview again
        ->
    review again

An earlier Preview is not authority for revised Specification bytes.

A fresh complete Edit Specification is also valid when that is clearer.

## Direct `--clipboard`

On macOS:

    ep-edit preview --root . --clipboard

reads the complete current Clipboard through `pbpaste`.

This is useful for a quick one-shot operation.

It is not the recommended route for a longer browser review cycle because
the Clipboard may change between commands.

For repeatable review:

    capture once
        ->
    save file
        ->
    check
        ->
    preview
        ->
    apply

If `pbpaste` is unavailable, `--clipboard` fails closed.

File and stdin input remain available.

## Standard input

A complete Edit Specification may be supplied using `-`.

This can be useful when an automation already owns immutable input bytes.

For interactive browser development, a saved Specification is usually easier
for Humans and agents to inspect and reuse.

## Missing-parent CREATE

A whole-file CREATE may target a file whose parent directories do not yet
exist.

CHECK and PREVIEW remain non-writing.

The missing parent chain is planned and displayed but is established only
during Apply.

Rollback ownership applies only to directories created by that exact Apply
operation.

A pre-existing directory is never rollback-owned.

A foreign file or directory appearing during a race is not silently adopted
as operation-owned state.

If the platform cannot provide the required secure no-follow,
descriptor-relative publication facilities, publication fails closed rather
than using a weaker fallback.

## Shell controller safety

The shell controller is part of the browser-copy transport boundary.

Keep controller syntax deliberately conservative so a transport script does
not create failures unrelated to `ep-edit`.

### Avoid shell-special variable names

When the controller is intended for zsh, do not use shell-special parameter
names as ordinary scratch variables.

In particular, avoid:

    path
    status

In zsh, `path` is a special array parameter tied to `PATH`.

Assigning to it as an ordinary loop variable can therefore change command
lookup and make later commands such as `grep`, `git`, or `find` appear to be
unavailable.

`status` is also a zsh special parameter and should not be used as an
ordinary controller variable.

Prefer explicit names such as:

    doc_path
    command_name
    diff_rc
    grep_rc
    rc

### Do not depend on pasted interactive comments

Do not rely on explanatory lines beginning with `#` inside a controller that
a Human will paste directly into an interactive zsh session.

Interactive comment handling depends on shell configuration.

A line that was intended only as commentary may therefore be parsed as shell
input rather than ignored.

Use prose outside the controller or `printf` labels inside it instead.

### Distinguish grep no-match from grep failure

When an audit expects no matching lines, do not collapse every non-zero
`grep` result into PASS.

For `grep`:

    0 = one or more matches
    1 = no matches
    greater than 1 = command or execution failure

For example:

    audit_output="$(
      grep -nE 'pattern' "$TARGET"
    )"
    grep_rc=$?

    if (( grep_rc == 0 )); then
      printf '%s\n' "$audit_output"
      printf 'ERROR: unexpected match found.\n'
      rc=1
    elif (( grep_rc == 1 )); then
      printf 'PASS: no unexpected match found.\n'
    else
      printf 'ERROR: audit command failed.\n'
      rc=$grep_rc
    fi

This prevents a missing command, unreadable input, or other `grep` execution
failure from being reported as a successful no-match audit.

The same principle applies to other commands whose non-zero values have more
than one meaning.

## After Apply

After successful publication:

1. run focused tests for the changed behavior;
2. run relevant continuity tests;
3. run repository consistency checks required by the target project;
4. inspect changed files or working-tree state.

`ep-edit` establishes deterministic publication of the authored bytes.

It does not prove the semantic correctness of what the Human or LLM authored.

## What ChatGPT should do after failure

When `ep-edit` rejects an authored operation, ChatGPT should not guess a
replacement mutation.

Preferred collaboration:

    Terminal reports deterministic failure
        ->
    Human returns the exact failure and current-file context
        ->
    ChatGPT compares intended and actual text
        ->
    ChatGPT authors a fresh exact Specification
        ->
    Human repeats controlled capture
        ->
    check
        ->
    preview

This preserves the distinction between:

    diagnostic assistance

and:

    mutation authority

## No LLM runtime dependency

ChatGPT is one possible author and review participant.

It is not part of the `ep-edit` runtime authority.

The same deterministic CLI can be used with:

- a Human-authored Specification;
- another LLM;
- a coding agent;
- deterministic automation.

The browser-copy procedure described here is an operating pattern around the
CLI, not a runtime dependency of the CLI itself.
