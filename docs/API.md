# API Documentation

Base URL: `http://127.0.0.1:5000` — JSON requests/responses. Timestamps are ISO-8601 UTC.
Amounts are JSON numbers with at most 2 decimal places.

## Error format (all errors)

```json
{ "error": { "code": "VALIDATION_ERROR", "message": "Request validation failed",
             "details": [ { "field": "amount", "code": "INVALID_AMOUNT", "message": "amount must be greater than 0" } ] } }
```
`details` is present when useful.

| HTTP | code | When |
|---|---|---|
| 400 | `INVALID_REQUEST_BODY` | Body is not a valid JSON object |
| 400 | `VALIDATION_ERROR` | Field validation failed (name, type, amount, reference_id, unknown/read-only fields such as `balance`) |
| 400 | `INVALID_ACCOUNT_ID` | Account id in the URL is not a valid UUID |
| 400 | `INVALID_QUERY_PARAMETERS` | Bad `page`, `limit` or `type` |
| 404 | `ACCOUNT_NOT_FOUND` | Account does not exist |
| 404 / 405 | `NOT_FOUND` / `METHOD_NOT_ALLOWED` | Unknown route; edit/delete of transactions is not supported |
| 409 | `DUPLICATE_TRANSACTION` | `reference_id` already used for this account (nothing is changed; existing transaction returned in `details`) |
| 422 | `INSUFFICIENT_BALANCE` | Debit/transfer exceeds balance (nothing is changed) |
| 500 | `INTERNAL_ERROR` | Unexpected error |

---

## 1. Create account — `POST /accounts`

Body: `{ "name": "Alice" }` (only `name`; sending `balance`, `id`, `created_at` → 400)

`201`:
```json
{ "id": "6f1c...-uuid", "name": "Alice", "balance": 0, "created_at": "2026-10-28T14:40:11.123456Z" }
```

## 2. Get account — `GET /accounts/{account_id}`
Returns the account object above. `404` if missing.

## 3. Get balance — `GET /accounts/{account_id}/balance`
`200`: `{ "account_id": "6f1c...", "balance": 150.0 }`

## 4. Add transaction — `POST /accounts/{account_id}/transactions`
Also available as `POST /transactions` with `account_id` in the body.

Body:
```json
{ "type": "credit", "amount": 50, "reference_id": "ref-001", "description": "Salary" }
```
- `type`: `credit` | `debit` (required)
- `amount`: number > 0, max 2 decimals, ≤ 1,000,000,000 (required)
- `reference_id`: non-empty string ≤ 100 chars, unique per account (required)
- `description`: optional string ≤ 255 chars

`201`:
```json
{ "transaction": { "id": "...", "account_id": "...", "type": "credit", "amount": 50.0,
                   "description": "Salary", "reference_id": "ref-001", "transfer_id": null,
                   "created_at": "2026-10-28T14:41:00.000001Z" },
  "balance": 150.0 }
```
Errors: `400` validation, `404` account, `409` duplicate reference, `422` insufficient balance.

## 5. Transaction history — `GET /accounts/{account_id}/transactions`

Query params: `type` (`credit`|`debit`, optional), `page` (default 1), `limit` (default 10, max 100).
Sorted latest-first by `created_at`.

`200`:
```json
{ "account_id": "...",
  "data": [ { "id": "...", "type": "debit", "amount": 10.0, "...": "..." } ],
  "pagination": { "page": 1, "limit": 10, "total_records": 42, "total_pages": 5 } }
```

## 6. Bonus: Transfer — `POST /transfers`

Body:
```json
{ "from_account_id": "<uuid>", "to_account_id": "<uuid>", "amount": 30,
  "reference_id": "transfer-001", "description": "Rent" }
```
`201`:
```json
{ "transfer_id": "...", "amount": 30.0, "reference_id": "transfer-001",
  "from_account": { "id": "...", "balance": 70.0 },
  "to_account":   { "id": "...", "balance": 80.0 },
  "transactions": [ { "type": "debit", "...": "..." }, { "type": "credit", "...": "..." } ] }
```
Debit and credit are created in a single database transaction; any failure (missing account,
insufficient funds, duplicate reference on either account) rolls back everything.
Errors: `400`, `404`, `409`, `422`.

## 7. Health — `GET /health` → `{ "status": "ok" }`
