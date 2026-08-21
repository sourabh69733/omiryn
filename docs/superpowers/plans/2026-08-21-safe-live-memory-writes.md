# Safe Live Memory Writes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Safely persist validated background-memory `add` and `reinforce` operations while deferring destructive operations and preserving the existing shadow flow.

**Architecture:** The validated shadow result passes through a provider-neutral application service. A dedicated storage module atomically mutates facts and writes an idempotency/audit ledger; the shadow worker advances its cursor only after successful application.

**Tech Stack:** Python 3.11, SQLAlchemy 2, SQLite/PostgreSQL, unittest/pytest.

**Spec:** `docs/superpowers/specs/2026-08-21-safe-live-memory-writes-design.md`

## Global Constraints

- `MEMORY_BACKGROUND_V2_LIVE_WRITES` defaults to `false`.
- Only `add` and `reinforce` mutate live facts in this phase.
- `supersede` and `retract` are audit-only deferred operations.
- No language-specific or semantic keyword rules may be added.
- The v1 extraction path and disabled shadow behavior must remain unchanged.

---

### Task 1: Transactional Memory Application Storage

**Files:**
- Modify: `src/storage/schema.py`
- Modify: `src/storage/database.py`
- Modify: `src/storage/profile_facts.py`
- Create: `src/storage/memory_applications.py`
- Modify: `src/storage/__init__.py`
- Modify: `src/storage/conversations.py`
- Modify: `src/storage/user_deletion.py`
- Test: `tests/test_memory_applications.py`

**Interfaces:**
- Produces: `apply_memory_operation_batch(payload: dict[str, Any]) -> dict[str, Any]`
- Produces: `list_memory_operation_applications(user_id: str, conversation_id: str | None = None) -> list[dict[str, Any]]`
- Produces: connection-aware profile-fact upsert used inside the shared transaction.

- [x] Write tests proving add persistence, reinforce-without-semantic-rewrite, deferred operations, retry idempotency, cross-user rejection, and atomic rollback.
- [x] Run `python -m pytest tests/test_memory_applications.py -q` and confirm failure because the storage interface does not exist.
- [x] Add the private operation-ledger table, ownership registration, storage module, and deletion lifecycle.
- [x] Refactor profile-fact upsert to accept an existing transaction without changing its public behavior.
- [x] Run `python -m pytest tests/test_memory_applications.py -q` and confirm all storage tests pass.

### Task 2: Memory Application Service

**Files:**
- Create: `src/agent/memory_engine/processing/application.py`
- Modify: `src/agent/memory_engine/processing/__init__.py`
- Test: `tests/test_memory_application_service.py`

**Interfaces:**
- Consumes: `MemoryBatch`, validated `ShadowMemoryAnalysis`, and `apply_memory_operation_batch`.
- Produces: `memory_background_v2_live_writes_enabled() -> bool`.
- Produces: `apply_validated_memory_analysis(batch, analysis) -> MemoryApplicationResult`.

- [x] Write tests proving the flag defaults off, evidence resolves only from eligible batch messages, invalid analyses are rejected, and operation results are mapped without semantic rules.
- [x] Run `python -m pytest tests/test_memory_application_service.py -q` and confirm failure because the service does not exist.
- [x] Implement immutable result contracts, evidence resolution, deterministic fingerprints, and storage delegation.
- [x] Run `python -m pytest tests/test_memory_application_service.py -q` and confirm all service tests pass.

### Task 3: Shadow Worker Integration

**Files:**
- Modify: `src/agent/memory_engine/processing/shadow.py`
- Modify: `tests/test_memory_shadow.py`

**Interfaces:**
- Consumes: `memory_background_v2_live_writes_enabled` and `apply_validated_memory_analysis`.
- Produces: worker statuses `shadow_valid`, `live_applied`, `live_deferred`, and `live_error`.

- [x] Add worker tests proving disabled mode remains observation-only, enabled valid results write before cursor advancement, deferred-only batches do not mutate facts, and application errors do not advance the cursor.
- [x] Run focused new worker tests and confirm they fail for the missing integration.
- [x] Integrate the service after validation and before processing-state persistence; preserve invalid-result and provider-error behavior.
- [x] Run `python -m pytest tests/test_memory_shadow.py -q` and confirm all worker tests pass.

### Task 4: Regression Verification

**Files:**
- Verify only; no production changes unless a regression exposes an in-scope defect.

**Interfaces:**
- Consumes the completed storage, service, and worker behavior.
- Produces fresh verification evidence.

- [x] Run `python -m pytest tests/test_memory_applications.py tests/test_memory_application_service.py tests/test_memory_shadow.py tests/test_memory_processing.py -q`.
- [x] Run the legacy agent and turn-output tests; isolate unrelated pre-existing flag and acknowledgement-policy failures without changing their contracts.
- [x] Run `python -m ruff check src/agent/memory_engine/processing src/storage/memory_applications.py tests/test_memory_applications.py tests/test_memory_application_service.py tests/test_memory_shadow.py`.
- [x] Run `git diff --check` and inspect the scoped diff without altering unrelated working-tree files.

Verification result: 27 focused memory tests passed. A broader run passed 507 tests with conversation-state shadow explicitly disabled, excluding two stale acknowledgement-policy tests and two tests for a missing frontend logger file; these baseline issues are unrelated to this feature.
