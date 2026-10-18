# Option A — Human-Reviewed AI Writer

Status: implemented at Checkpoint 4 under the user's explicit limited retention approval. No live Gemini request, new model, billing change or database migration is part of this work.

## Output and retention policy

Gemini writes the complete personalized email subject/body (empty subject for non-email channels). The structured schema contains only those two fields. It receives bounded approved public observations, confirmed eligible capabilities and only the selected public profile scope. No phrase copying or self-declared claim/link metadata is required. Generation never calls the local composer or switches providers/models.

There are two outcomes:

- **Hard blocked:** invalid schema/length/channel/finish state, known API secrets or recognizable credential strings, contact values, unauthorized URLs, unsafe controls/markup, unauthorized sender/service/demo offers, and explicit prohibited commitments. No subject/body from this outcome is stored, logged or displayed. Only static error codes, prompt/safety versions and measured usage may be retained. There is no repair/fallback request.
- **Review draft:** output passing all hard checks is stored unchanged as subject/body in the existing local draft row. Its factual status is always **unverified**. It displays **AI-generated · Unverified · Review required** until explicit human acknowledgement. Factual prose, questions, benefits and reasonable paraphrases are not rejected merely for differing from canonical text. This is not a factual-verification system.

The prompt still prohibits invented metrics, website problems, relationships, experience and achievements. Relevant completed-project experience requires confirmed profile projects; a portfolio URL alone is not evidence of completed work. Optional demo invitations require permission and a relevant existing project. Benefits must be possibilities; no free custom work, fixed timelines or specific unapproved deliverables may be promised. Human review must correct unsupported content that deterministic checks cannot identify.

## Review workflow and existing storage

New drafts carry `writer_version=human-reviewed-v1`, `validator_version=human-safety-v1`, and `prompt_version=human-writer-v2`. Evidence JSON includes a minimal authorization snapshot and:

- `review.state`: `required` or `ready`.
- `review.factual_status`: always `unverified`.
- `review.content_hash`: SHA-256 of the current `[subject, body]` JSON.
- `review.acknowledged_at`: present only after explicit human acknowledgement.

Saving does not mark a draft ready. The user saves, checks the exact text, acknowledges review and marks it ready for manual outreach. The API rejects stale hashes, unsaved drafts, missing/false/non-boolean acknowledgement and foreign-origin writes. Human approval is never labelled automated verification. The new mode's copy button remains disabled until ready. Sending/opening a recipient contact is never automatic.

Editing immediately disables readiness in the editor. A content-free `DELETE /drafts/{id}/review` revokes stored acknowledgement without sending the unsaved text. Saving changed text also revokes acknowledgement in the same transaction. Review is bound to a particular saved revision; if a network request fails the UI reports it and the local edited text remains unready. No offline queue or localStorage copy is introduced.

The existing assessment-scoped unsaved list and saved list recover drafts after reload. Late responses for other assessment revisions are ignored. Existing templates, historical Gemini-assisted drafts and the earlier annotated AI Writer retain their labels and content. Existing saved drafts are not backfilled, relabelled, reviewed or deleted. Dashboard counts distinguish saved-but-unreviewed new drafts from ready ones.

## Discard

Explicit discard applies only to the new mode, whether saved or unsaved. `DELETE /drafts/{id}` deletes the output row and its evidence JSON, replaces corresponding job reopening references with content-free `discarded=true`, and retains request/usage accounting. It does not create a trash/recovery copy. SQLite secure deletion is enabled for these deletes and edits. API responses use no-store; raw generated text is not added to application logs.

Discard clears the current editor and refreshes history/recovery lists. Later fetches return 404. Historical drafts are protected by 409. This is application deletion, not a promise to retract previously copied text or erase independently maintained external backups.

## Verification and limitations

Offline tests exercise the real Option A SDK adapter with mocked responses, all channels, natural independently written prose, explicit unverified states, privacy opt-out, authorized links/project demos, hard blocks, persistence, saving, acknowledgement, editing, revocation, stale revisions, discard, content-free usage, and history preservation. Tests use temporary databases. Historical strict-validator tests are explicitly retained as legacy coverage and do not define production acceptance.

Hard checks are deterministic pattern/allowlist checks, not complete semantic or de-obfuscation analysis. Conservative contact/credential detection may reject unusual benign strings. Assertions such as invented relationships or visitor metrics can require human correction and must never acquire an automated factual-verification label. Do not treat a passing hard check or a human acknowledgement as proof of truth. Live Gemini adherence remains untested by this change.

No new database tables or columns are needed: existing subject/body, saved status, evidence JSON, and usage JSON carry this versioned workflow. No consent expansion, quota/cooldown changes, automatic outreach or Checkpoint 5 features are included.

## Channel formatting

`human-writer-v2` adds per-channel writing instructions without changing the hard safety boundary. Email uses a separate subject, greeting, short blank-line-separated paragraphs, a natural CTA and a closing/signature. Only the explicitly shared approved freelancer name may be generated; when absent, use a courteous closing alone, without a placeholder or invented name. The JSON body contains real newline characters after parsing.

WhatsApp and Instagram use compact conversational messages; LinkedIn uses brief professional DM paragraphs; contact forms use a self-contained message. These channels keep an empty subject and do not inherit the formal email layout. The controlled textarea preserves paragraph breaks; the application does not auto-rewrite genuine AI prose into a template. Email copy uses `Subject: ...`, a blank line and the unchanged body; non-email copy uses only the message. Human review remains required, and no clipboard write occurs until the user clicks Copy.

Offline regressions cover SDK output, storage, editing, reload, approval and clipboard text with exact paragraph/signature breaks. They verify distinct channel instructions and no invented signature when profile sharing omits the sender. Live model adherence remains unverified.
