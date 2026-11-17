# Schema v2 — sample batches

Adds batch-managed telemetry samples on top of v1.

- New table `sample_batches`: `batch_no` UNIQUE (client idempotency key), `content_hash` (SHA-256 of the exact file content), `row_count`, `status` (`importing` → `active` → `retired` → `cleaned`, or `failed` keeping the previous active batch untouched), `table_name`, `error`, `created_at`, `activated_at`.
- `experiments` gains nullable `batch_id` FK to `sample_batches`; the immutable snapshot also embeds the batch descriptor. Seed runs an idempotent `ALTER TABLE` for databases created under v1.
- Every imported batch is loaded into its own physical table `telemetry_batch_<id>` (same columns as `telemetry`). The seeded 5,000-row dataset stays in `telemetry` as the initial active batch (`seed-20261101`) and is never dropped.
- Trials (EXPLAIN, timed queries, 20-row write probe, `trial_candidate` index) run entirely against the batch table bound at experiment creation, so an import can switch the active batch concurrently without waiting for queued or running trials.
- Retired `telemetry_batch_*` tables are dropped only after no queued/running experiment references them; cleanup runs after each activation and after each trial reaches a terminal state.
