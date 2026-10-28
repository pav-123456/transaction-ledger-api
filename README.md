# Transaction Ledger API

A backend API for a simple transaction ledger: create accounts, post credit/debit
transactions, read balances, browse paginated history, and (bonus) transfer money
between accounts atomically.

**Stack:** Python 3.10+, Flask, SQLite (Python standard library `sqlite3`).

## Run locally

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python run.py                      # http://127.0.0.1:5000
```

Optional environment variables: `PORT` (default 5000), `HOST` (default 127.0.0.1),
`LEDGER_DB` (SQLite file path, default `./ledger.db`). The schema is created automatically on startup.

## Run the tests

```bash
python -m unittest discover -s tests -t . -v
```

The suite (32 tests) covers every rule in the assessment, including concurrency
(25 parallel debits never overdraw; duplicate references under race create one
transaction) and rollback of failed transfers.

## Quick try

```bash
curl -s -X POST localhost:5000/accounts -H 'Content-Type: application/json' -d '{"name":"Alice"}'
# copy the id, then:
curl -s -X POST localhost:5000/accounts/<ID>/transactions -H 'Content-Type: application/json' \
  -d '{"type":"credit","amount":100,"reference_id":"r1","description":"Deposit"}'
curl -s localhost:5000/accounts/<ID>/balance
curl -s "localhost:5000/accounts/<ID>/transactions?type=credit&page=1&limit=10"
```

## Project structure

```
run.py                 entry point
app/
  __init__.py          app factory
  routes.py            HTTP layer (parse -> validate -> service -> JSON)
  services.py          business logic; every balance change runs inside one DB transaction
  validation.py        input validation with per-field errors
  errors.py            ApiError types + consistent JSON error handlers
  db.py                SQLite connections + atomic() helper
  schema.sql           tables, constraints, indexes, immutability triggers
tests/test_api.py      test suite
docs/API.md            full API documentation
ASSUMPTIONS.md         design decisions and assumptions
```

## How the key requirements are met

| Requirement | Approach |
|---|---|
| Atomicity | Transaction insert + balance update (and both transfer legs) run in one `BEGIN IMMEDIATE ... COMMIT`; any error triggers `ROLLBACK`. |
| No overdraft / races | `BEGIN IMMEDIATE` serialises writers; debit uses `UPDATE ... WHERE balance >= amount`; DB `CHECK (balance >= 0)` as a backstop. |
| Duplicate `reference_id` | `UNIQUE (account_id, reference_id)` plus a pre-check returning `409` with the existing transaction. Same reference allowed across accounts. |
| Immutability | No update/delete endpoints (`405`), and DB triggers abort any `UPDATE`/`DELETE` on `transactions`. |
| Balance consistency | Balance only changes together with a stored transaction; rejected requests change nothing. |
| Money precision | Stored as integer minor units (e.g. paise), max 2 decimal places accepted. |
| Client can't set balance | `balance`, `id`, `created_at` in request bodies are rejected with a validation error. |

See `docs/API.md` for endpoints and `ASSUMPTIONS.md` for decisions.
