PRAGMA journal_mode = WAL;

-- Money is stored as INTEGER minor units (e.g. paise/cents) to avoid float errors.
CREATE TABLE IF NOT EXISTS accounts (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL CHECK (length(trim(name)) > 0),
    balance     INTEGER NOT NULL DEFAULT 0 CHECK (balance >= 0),
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS transactions (
    seq           INTEGER PRIMARY KEY AUTOINCREMENT,      -- stable tie-breaker for ordering
    id            TEXT NOT NULL UNIQUE,
    account_id    TEXT NOT NULL REFERENCES accounts(id) ON DELETE RESTRICT,
    type          TEXT NOT NULL CHECK (type IN ('credit', 'debit')),
    amount        INTEGER NOT NULL CHECK (amount > 0),
    description   TEXT NOT NULL DEFAULT '',
    reference_id  TEXT NOT NULL CHECK (length(trim(reference_id)) > 0),
    transfer_id   TEXT,                                   -- links the two legs of a transfer
    created_at    TEXT NOT NULL,
    -- reference_id is unique per account, but may repeat across accounts
    UNIQUE (account_id, reference_id)
);

CREATE INDEX IF NOT EXISTS idx_tx_account_created
    ON transactions (account_id, created_at DESC, seq DESC);
CREATE INDEX IF NOT EXISTS idx_tx_account_type_created
    ON transactions (account_id, type, created_at DESC, seq DESC);

-- Transaction immutability enforced at the database level.
CREATE TRIGGER IF NOT EXISTS trg_transactions_no_update
BEFORE UPDATE ON transactions
BEGIN
    SELECT RAISE(ABORT, 'transactions are immutable');
END;

CREATE TRIGGER IF NOT EXISTS trg_transactions_no_delete
BEFORE DELETE ON transactions
BEGIN
    SELECT RAISE(ABORT, 'transactions are immutable');
END;
