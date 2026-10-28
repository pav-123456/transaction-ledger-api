# Assumptions & Design Decisions

1. **Database:** SQLite (stdlib) so the project runs with only `pip install Flask`. Writers are serialised with `BEGIN IMMEDIATE`, which makes balance checks race-free. For a multi-node deployment I would move to PostgreSQL using `SELECT ... FOR UPDATE` (the schema/constraints port directly).
2. **IDs:** accounts and transactions use server-generated UUID v4. Clients cannot supply `id`, `created_at` or `balance`; such fields are rejected (400) rather than silently ignored, so mistakes are visible.
3. **Money:** amounts must be positive with at most 2 decimal places (max 1,000,000,000) and are stored as integer minor units to avoid floating-point drift. Amounts must be JSON numbers (not strings/booleans). Currency is not modelled (single implicit currency).
4. **Balances never go negative** (no overdraft) — enforced in code and by `CHECK (balance >= 0)`.
5. **Duplicate `reference_id`:** returns `409 DUPLICATE_TRANSACTION` including the existing transaction, creates nothing and leaves the balance unchanged. Uniqueness is per account; the same reference may be used on different accounts. A *rejected* (e.g. insufficient-balance) request stores nothing, so its reference can be reused.
6. **Transaction endpoint shape:** primary route is `POST /accounts/{id}/transactions`; `POST /transactions` with `account_id` in the body is also supported. If both are given they must match.
7. **Immutability:** there are no PUT/PATCH/DELETE routes (→ 405), and SQLite triggers block UPDATE/DELETE on `transactions` even for direct DB access. There is no API to delete accounts.
8. **Ordering:** history is sorted by `created_at` descending, with an internal auto-increment sequence as a tie-breaker so ordering is deterministic.
9. **Pagination:** `page` ≥ 1, `limit` 1–100 (default 10). A page past the end returns an empty list with correct metadata. Invalid values return 400.
10. **Account IDs in URLs** that are not valid UUIDs return `400 INVALID_ACCOUNT_ID`; valid but unknown IDs return `404`.
11. **Transfers:** one `reference_id` is supplied per transfer and is applied to both legs (debit on source, credit on destination), so it must be unused on both accounts; otherwise the whole transfer is rolled back with 409. Both legs share a `transfer_id` and appear in each account's history as normal debit/credit transactions. Transferring to the same account is rejected.
12. **Authentication/authorisation** is out of scope for this assessment.
13. **Rejected writes are not logged** as transactions; only valid, successful transactions exist in the ledger.
