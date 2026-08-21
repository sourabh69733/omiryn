# Safe Live Memory Writes Design

## Goal

Persist validated background-memory proposals safely while preserving the existing shadow and v1 extraction flows.

## Scope

The first live-write release applies only `add` and `reinforce`. It records `supersede` and `retract` as deferred operations without changing live facts. A new feature flag is disabled by default.

## Architecture

`shadow.py` continues to build batches, call the model, and validate its complete response. A new `MemoryApplicationService` receives only a valid `ShadowMemoryAnalysis`, separates applicable from deferred operations, and delegates persistence to a dedicated storage boundary. The storage boundary owns one database transaction containing idempotency checks, all allowed fact mutations, and operation audit records.

The model never writes directly to storage. The application service contains no language-specific or semantic keyword rules; it only enforces the approved operation allowlist and integrity boundaries.

## Data Flow

1. The background worker builds and validates a memory batch as it does today.
2. If live writes are disabled, the worker remains observation-only and advances the shadow cursor as before.
3. If live writes are enabled and validation succeeds, the application service submits the batch operations to storage.
4. Storage checks the batch ledger. A previously committed batch returns its recorded outcome without repeating mutations.
5. Storage applies every `add` and `reinforce` in one transaction and records every `supersede` or `retract` as deferred.
6. Only after the transaction commits does the worker advance its processing cursor and save the new handoff.
7. If cursor persistence fails after the fact transaction commits, a retry sees the application ledger, performs no duplicate mutation, and can advance the cursor safely.

## Persistence

A `memory_operation_applications` table records one row per proposed operation:

- stable `id`
- `user_id`, `conversation_id`, and `batch_key`
- `operation_index` and deterministic `operation_fingerprint`
- operation kind and outcome: `applied` or `deferred`
- optional target and resulting fact identifiers
- encrypted operation, before-state, and after-state JSON
- creation timestamp

A unique constraint on `(user_id, conversation_id, batch_key, operation_index)` prevents duplicate application. The fingerprint makes audit comparison possible without depending on model wording.

## Operation Semantics

### Add

Create or merge a fact using the existing profile-fact normalization and deduplication behavior. Evidence is resolved from eligible user messages in the validated batch and stored with the conversation ID and message index. The stored fact type, category, key, label, value, and confidence come from the validated model operation.

### Reinforce

The target must be an active fact belonging to the same user. Reinforcement adds new eligible evidence and may raise confidence, but it does not rewrite the target's semantic type, category, key, label, or value.

### Supersede and Retract

Record the proposal and its target as `deferred`. Do not mutate the target fact in this release.

## Failure Behavior

- Invalid model output performs no live write and follows existing shadow-invalid handling.
- A missing, inactive, or cross-user reinforcement target rejects the complete application transaction.
- Any operation failure rolls back all fact and ledger changes for that batch.
- Application failure does not advance the processing cursor.
- Debug output distinguishes `shadow_valid`, `live_applied`, `live_deferred`, and `live_error` and includes no unencrypted private evidence.

## Compatibility and Rollout

- `MEMORY_BACKGROUND_V2_LIVE_WRITES=false` is the default.
- `MEMORY_BACKGROUND_V2_SHADOW` and the existing v1 extraction path keep their current behavior.
- Enabling live writes changes only valid background-v2 batches.
- Initial rollout is limited to internal testing before any production cohort is enabled.

## Tests

Automated tests must prove:

- disabled flag produces zero live writes;
- `add` persists evidence-backed memory;
- `reinforce` adds evidence without rewriting semantics;
- `supersede` and `retract` are deferred;
- retrying the same batch is idempotent;
- mixed-operation failure rolls back the complete batch;
- cross-user and inactive targets are rejected;
- application failure does not advance the cursor;
- the existing observation-only shadow flow remains unchanged.

## Out of Scope

Live supersession, live retraction, automatic rollback tools, confidence calibration, queues, and production cohort management remain later phases.
