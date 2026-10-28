"""Business logic. All balance-changing operations run inside db.atomic()."""
import math
import sqlite3
import uuid
from datetime import datetime, timezone

from .db import atomic
from .errors import AccountNotFound, DuplicateTransaction, InsufficientBalance


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _money(minor):
    return round(minor / 100, 2)


def account_to_dict(row):
    return {
        "id": row["id"],
        "name": row["name"],
        "balance": _money(row["balance"]),
        "created_at": row["created_at"],
    }


def tx_to_dict(row):
    return {
        "id": row["id"],
        "account_id": row["account_id"],
        "type": row["type"],
        "amount": _money(row["amount"]),
        "description": row["description"],
        "reference_id": row["reference_id"],
        "transfer_id": row["transfer_id"],
        "created_at": row["created_at"],
    }


# ---------------------------------------------------------------- accounts
def create_account(conn, name):
    account_id = str(uuid.uuid4())
    # balance is never taken from the client: it always starts at 0.
    conn.execute(
        "INSERT INTO accounts (id, name, balance, created_at) VALUES (?, ?, 0, ?)",
        (account_id, name, _now()),
    )
    return get_account(conn, account_id)


def get_account(conn, account_id):
    row = conn.execute("SELECT * FROM accounts WHERE id = ?", (account_id,)).fetchone()
    if row is None:
        raise AccountNotFound(account_id)
    return row


# ------------------------------------------------------------ transactions
def _apply_transaction(conn, account_id, tx_type, amount, description, reference_id, transfer_id=None):
    """Insert a transaction and update the balance. MUST be called inside atomic()."""
    get_account(conn, account_id)  # 404 if missing

    existing = conn.execute(
        "SELECT * FROM transactions WHERE account_id = ? AND reference_id = ?",
        (account_id, reference_id),
    ).fetchone()
    if existing is not None:
        raise DuplicateTransaction(tx_to_dict(existing))

    if tx_type == "credit":
        conn.execute("UPDATE accounts SET balance = balance + ? WHERE id = ?", (amount, account_id))
    else:
        # Conditional update: succeeds only if funds are sufficient (also backed by CHECK balance >= 0).
        cur = conn.execute(
            "UPDATE accounts SET balance = balance - ? WHERE id = ? AND balance >= ?",
            (amount, account_id, amount),
        )
        if cur.rowcount == 0:
            balance = conn.execute("SELECT balance FROM accounts WHERE id = ?", (account_id,)).fetchone()[0]
            raise InsufficientBalance(_money(balance), _money(amount))

    tx_id = str(uuid.uuid4())
    try:
        conn.execute(
            """INSERT INTO transactions
               (id, account_id, type, amount, description, reference_id, transfer_id, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (tx_id, account_id, tx_type, amount, description, reference_id, transfer_id, _now()),
        )
    except sqlite3.IntegrityError:
        # Safety net: the UNIQUE(account_id, reference_id) constraint fired.
        existing = conn.execute(
            "SELECT * FROM transactions WHERE account_id = ? AND reference_id = ?",
            (account_id, reference_id),
        ).fetchone()
        if existing is None:
            raise
        raise DuplicateTransaction(tx_to_dict(existing))
    return conn.execute("SELECT * FROM transactions WHERE id = ?", (tx_id,)).fetchone()


def add_transaction(conn, account_id, tx_type, amount, description, reference_id):
    with atomic(conn):
        tx = _apply_transaction(conn, account_id, tx_type, amount, description, reference_id)
        account = get_account(conn, account_id)
    return tx, account


def list_transactions(conn, account_id, tx_type, page, limit):
    get_account(conn, account_id)
    where, params = "account_id = ?", [account_id]
    if tx_type:
        where += " AND type = ?"
        params.append(tx_type)
    total = conn.execute(f"SELECT COUNT(*) FROM transactions WHERE {where}", params).fetchone()[0]
    rows = conn.execute(
        f"""SELECT * FROM transactions WHERE {where}
            ORDER BY created_at DESC, seq DESC LIMIT ? OFFSET ?""",
        params + [limit, (page - 1) * limit],
    ).fetchall()
    return rows, total


# --------------------------------------------------------------- transfers
def transfer(conn, from_id, to_id, amount, description, reference_id):
    """Debit `from_id` and credit `to_id` in ONE database transaction.

    Any failure (missing account, insufficient funds, duplicate reference, crash)
    rolls back both legs, so a partial transfer is impossible.
    """
    transfer_id = str(uuid.uuid4())
    desc = description or "Transfer"
    with atomic(conn):
        get_account(conn, from_id)
        get_account(conn, to_id)
        debit = _apply_transaction(
            conn, from_id, "debit", amount, f"{desc} (to {to_id})", reference_id, transfer_id
        )
        credit = _apply_transaction(
            conn, to_id, "credit", amount, f"{desc} (from {from_id})", reference_id, transfer_id
        )
        src = get_account(conn, from_id)
        dst = get_account(conn, to_id)
    return transfer_id, debit, credit, src, dst


def pagination_meta(page, limit, total):
    return {
        "page": page,
        "limit": limit,
        "total_records": total,
        "total_pages": math.ceil(total / limit) if total else 0,
    }
