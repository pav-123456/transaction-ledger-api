import os
import sqlite3
import tempfile
import threading
import unittest

from app import create_app


class LedgerTestCase(unittest.TestCase):
    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self.app = create_app({"DATABASE": self.db_path, "TESTING": True})
        self.client = self.app.test_client()

    def tearDown(self):
        for suffix in ("", "-wal", "-shm"):
            try:
                os.remove(self.db_path + suffix)
            except FileNotFoundError:
                pass

    # helpers
    def new_account(self, name="Alice"):
        r = self.client.post("/accounts", json={"name": name})
        self.assertEqual(r.status_code, 201, r.get_json())
        return r.get_json()["id"]

    def tx(self, acc, type_, amount, ref, client=None, **extra):
        body = {"type": type_, "amount": amount, "reference_id": ref, "description": "t", **extra}
        return (client or self.client).post(f"/accounts/{acc}/transactions", json=body)

    def balance(self, acc):
        return self.client.get(f"/accounts/{acc}/balance").get_json()["balance"]


class AccountTests(LedgerTestCase):
    def test_create_account(self):
        r = self.client.post("/accounts", json={"name": "  Alice  "})
        self.assertEqual(r.status_code, 201)
        body = r.get_json()
        self.assertEqual(body["name"], "Alice")
        self.assertEqual(body["balance"], 0)
        self.assertTrue(body["id"] and body["created_at"])

    def test_ids_unique(self):
        self.assertNotEqual(self.new_account(), self.new_account())

    def test_name_required(self):
        for body in ({}, {"name": ""}, {"name": "   "}, {"name": 5}):
            r = self.client.post("/accounts", json=body)
            self.assertEqual(r.status_code, 400, body)
            self.assertEqual(r.get_json()["error"]["code"], "VALIDATION_ERROR")

    def test_client_cannot_set_balance_or_created_at(self):
        for extra in ({"balance": 500}, {"created_at": "2000-01-01"}, {"id": "x"}):
            r = self.client.post("/accounts", json={"name": "A", **extra})
            self.assertEqual(r.status_code, 400)

    def test_invalid_body(self):
        r = self.client.post("/accounts", data="not json", content_type="application/json")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.get_json()["error"]["code"], "INVALID_REQUEST_BODY")
        r = self.client.post("/accounts", json=[1, 2])
        self.assertEqual(r.status_code, 400)

    def test_get_account_and_balance_errors(self):
        r = self.client.get("/accounts/00000000-0000-4000-8000-000000000000/balance")
        self.assertEqual(r.status_code, 404)
        self.assertEqual(r.get_json()["error"]["code"], "ACCOUNT_NOT_FOUND")
        r = self.client.get("/accounts/not-a-uuid/balance")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.get_json()["error"]["code"], "INVALID_ACCOUNT_ID")


class TransactionTests(LedgerTestCase):
    def test_credit_and_debit(self):
        a = self.new_account()
        r = self.tx(a, "credit", 100, "r1")
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.get_json()["balance"], 100)
        self.assertEqual(self.tx(a, "credit", 50, "r2").get_json()["balance"], 150)
        self.assertEqual(self.tx(a, "debit", 30, "r3").get_json()["balance"], 120)
        self.assertEqual(self.tx(a, "debit", 20, "r4").get_json()["balance"], 100)
        self.assertEqual(self.balance(a), 100)

    def test_insufficient_balance_rejected(self):
        a = self.new_account()
        self.tx(a, "credit", 100, "r1")
        r = self.tx(a, "debit", 150, "r2")
        self.assertEqual(r.status_code, 422)
        self.assertEqual(r.get_json()["error"]["code"], "INSUFFICIENT_BALANCE")
        self.assertEqual(self.balance(a), 100)
        # rejected tx must not be stored, and its reference_id stays reusable
        hist = self.client.get(f"/accounts/{a}/transactions").get_json()
        self.assertEqual(hist["pagination"]["total_records"], 1)
        self.assertEqual(self.tx(a, "debit", 100, "r2").status_code, 201)

    def test_duplicate_reference_same_account(self):
        a = self.new_account()
        self.assertEqual(self.tx(a, "credit", 100, "dup").status_code, 201)
        r = self.tx(a, "credit", 100, "dup")
        self.assertEqual(r.status_code, 409)
        err = r.get_json()["error"]
        self.assertEqual(err["code"], "DUPLICATE_TRANSACTION")
        self.assertEqual(err["details"]["existing_transaction"]["reference_id"], "dup")
        self.assertEqual(self.balance(a), 100)
        self.assertEqual(
            self.client.get(f"/accounts/{a}/transactions").get_json()["pagination"]["total_records"], 1
        )

    def test_same_reference_different_accounts(self):
        a, b = self.new_account("A"), self.new_account("B")
        self.assertEqual(self.tx(a, "credit", 10, "same").status_code, 201)
        self.assertEqual(self.tx(b, "credit", 10, "same").status_code, 201)

    def test_validation(self):
        a = self.new_account()
        cases = [
            ({"type": "transfer", "amount": 5, "reference_id": "x"}, "type"),
            ({"amount": 5, "reference_id": "x"}, "type"),
            ({"type": "credit", "amount": 0, "reference_id": "x"}, "amount"),
            ({"type": "credit", "amount": -5, "reference_id": "x"}, "amount"),
            ({"type": "credit", "amount": "10", "reference_id": "x"}, "amount"),
            ({"type": "credit", "amount": True, "reference_id": "x"}, "amount"),
            ({"type": "credit", "amount": 1.234, "reference_id": "x"}, "amount"),
            ({"type": "credit", "reference_id": "x"}, "amount"),
            ({"type": "credit", "amount": 5}, "reference_id"),
            ({"type": "credit", "amount": 5, "reference_id": "  "}, "reference_id"),
            ({"type": "credit", "amount": 5, "reference_id": "x", "created_at": "z"}, "created_at"),
        ]
        for body, field in cases:
            r = self.client.post(f"/accounts/{a}/transactions", json=body)
            self.assertEqual(r.status_code, 400, body)
            fields = [e["field"] for e in r.get_json()["error"]["details"]]
            self.assertIn(field, fields, body)
        self.assertEqual(self.balance(a), 0)

    def test_account_must_exist(self):
        r = self.tx("00000000-0000-4000-8000-000000000000", "credit", 5, "x")
        self.assertEqual(r.status_code, 404)
        r = self.tx("garbage", "credit", 5, "x")
        self.assertEqual(r.status_code, 400)

    def test_body_account_id_form(self):
        a = self.new_account()
        r = self.client.post(
            "/transactions",
            json={"account_id": a, "type": "credit", "amount": 25.5, "reference_id": "b1"},
        )
        self.assertEqual(r.status_code, 201)
        self.assertEqual(self.balance(a), 25.5)
        r = self.client.post("/transactions", json={"type": "credit", "amount": 1, "reference_id": "b2"})
        self.assertEqual(r.status_code, 400)

    def test_decimal_precision(self):
        a = self.new_account()
        for i in range(10):
            self.tx(a, "credit", 0.1, f"c{i}")
        self.assertEqual(self.balance(a), 1.0)
        self.assertEqual(self.tx(a, "debit", 1.0, "d").status_code, 201)
        self.assertEqual(self.balance(a), 0)


class HistoryTests(LedgerTestCase):
    def seed(self):
        a = self.new_account()
        for i in range(7):
            self.tx(a, "credit", 100, f"c{i}")
        for i in range(3):
            self.tx(a, "debit", 10, f"d{i}")
        return a

    def test_latest_first_and_pagination(self):
        a = self.seed()
        body = self.client.get(f"/accounts/{a}/transactions?page=1&limit=4").get_json()
        self.assertEqual([t["reference_id"] for t in body["data"]], ["d2", "d1", "d0", "c6"])
        self.assertEqual(
            body["pagination"], {"page": 1, "limit": 4, "total_records": 10, "total_pages": 3}
        )
        last = self.client.get(f"/accounts/{a}/transactions?page=3&limit=4").get_json()
        self.assertEqual(len(last["data"]), 2)
        beyond = self.client.get(f"/accounts/{a}/transactions?page=9&limit=4").get_json()
        self.assertEqual(beyond["data"], [])

    def test_filter_by_type(self):
        a = self.seed()
        d = self.client.get(f"/accounts/{a}/transactions?type=debit").get_json()
        self.assertEqual(d["pagination"]["total_records"], 3)
        self.assertTrue(all(t["type"] == "debit" for t in d["data"]))
        c = self.client.get(f"/accounts/{a}/transactions?type=credit&limit=100").get_json()
        self.assertEqual(c["pagination"]["total_records"], 7)
        both = self.client.get(f"/accounts/{a}/transactions").get_json()
        self.assertEqual(both["pagination"]["total_records"], 10)

    def test_invalid_query_params(self):
        a = self.seed()
        for qs in ("page=0", "page=abc", "limit=0", "limit=101", "limit=-1", "type=foo"):
            r = self.client.get(f"/accounts/{a}/transactions?{qs}")
            self.assertEqual(r.status_code, 400, qs)
            self.assertEqual(r.get_json()["error"]["code"], "INVALID_QUERY_PARAMETERS")

    def test_history_unknown_account(self):
        r = self.client.get("/accounts/00000000-0000-4000-8000-000000000000/transactions")
        self.assertEqual(r.status_code, 404)


class IntegrityTests(LedgerTestCase):
    def test_transactions_immutable_via_api(self):
        a = self.new_account()
        txid = self.tx(a, "credit", 10, "r").get_json()["transaction"]["id"]
        for method in ("put", "patch", "delete"):
            for url in (f"/accounts/{a}/transactions/{txid}", f"/accounts/{a}/transactions", f"/transactions/{txid}"):
                r = getattr(self.client, method)(url, json={"amount": 1})
                self.assertIn(r.status_code, (404, 405), (method, url))
        self.assertEqual(self.balance(a), 10)

    def test_transactions_immutable_in_database(self):
        a = self.new_account()
        self.tx(a, "credit", 10, "r")
        conn = sqlite3.connect(self.db_path)
        with self.assertRaises(sqlite3.DatabaseError):
            conn.execute("UPDATE transactions SET amount = 999")
        with self.assertRaises(sqlite3.DatabaseError):
            conn.execute("DELETE FROM transactions")
        conn.close()

    def test_db_constraints(self):
        a = self.new_account()
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA foreign_keys = ON")
        with self.assertRaises(sqlite3.IntegrityError):
            conn.execute("UPDATE accounts SET balance = -1 WHERE id = ?", (a,))
        with self.assertRaises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO transactions (id, account_id, type, amount, reference_id, created_at) "
                "VALUES ('x', 'missing-account', 'credit', 5, 'r', 'now')"
            )
        with self.assertRaises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO transactions (id, account_id, type, amount, reference_id, created_at) "
                "VALUES ('y', ?, 'credit', 0, 'r', 'now')", (a,)
            )
        conn.close()

    def test_balance_equals_sum_of_transactions(self):
        a = self.new_account()
        self.tx(a, "credit", 100, "1")
        self.tx(a, "credit", 50, "2")
        self.tx(a, "debit", 30, "3")
        self.tx(a, "debit", 20, "4")
        self.tx(a, "debit", 500, "5")  # rejected
        conn = sqlite3.connect(self.db_path)
        s = conn.execute(
            "SELECT COALESCE(SUM(CASE type WHEN 'credit' THEN amount ELSE -amount END),0) "
            "FROM transactions WHERE account_id = ?", (a,)
        ).fetchone()[0]
        bal = conn.execute("SELECT balance FROM accounts WHERE id = ?", (a,)).fetchone()[0]
        conn.close()
        self.assertEqual(s, bal)
        self.assertEqual(self.balance(a), 100)

    def test_concurrent_debits_never_overdraw(self):
        a = self.new_account()
        self.tx(a, "credit", 100, "seed")
        results = []

        def worker(i):
            c = self.app.test_client()
            results.append(self.tx(a, "debit", 10, f"w{i}", client=c).status_code)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(25)]
        [t.start() for t in threads]
        [t.join() for t in threads]
        self.assertEqual(results.count(201), 10)
        self.assertEqual(results.count(422), 15)
        self.assertEqual(self.balance(a), 0)

    def test_concurrent_duplicate_reference(self):
        a = self.new_account()
        results = []

        def worker():
            c = self.app.test_client()
            results.append(self.tx(a, "credit", 10, "same", client=c).status_code)

        threads = [threading.Thread(target=worker) for _ in range(10)]
        [t.start() for t in threads]
        [t.join() for t in threads]
        self.assertEqual(results.count(201), 1)
        self.assertEqual(results.count(409), 9)
        self.assertEqual(self.balance(a), 10)

    def test_unknown_route_json_error(self):
        r = self.client.get("/nope")
        self.assertEqual(r.status_code, 404)
        self.assertEqual(r.get_json()["error"]["code"], "NOT_FOUND")


class TransferTests(LedgerTestCase):
    def setUp(self):
        super().setUp()
        self.a, self.b = self.new_account("A"), self.new_account("B")
        self.tx(self.a, "credit", 100, "seed-a")
        self.tx(self.b, "credit", 50, "seed-b")

    def transfer(self, **over):
        body = {"from_account_id": self.a, "to_account_id": self.b, "amount": 30, "reference_id": "t1"}
        body.update(over)
        return self.client.post("/transfers", json=body)

    def test_success(self):
        r = self.transfer()
        self.assertEqual(r.status_code, 201)
        body = r.get_json()
        self.assertEqual(body["from_account"]["balance"], 70)
        self.assertEqual(body["to_account"]["balance"], 80)
        self.assertEqual(self.balance(self.a), 70)
        self.assertEqual(self.balance(self.b), 80)
        types = sorted(t["type"] for t in body["transactions"])
        self.assertEqual(types, ["credit", "debit"])
        self.assertEqual(len({t["transfer_id"] for t in body["transactions"]}), 1)

    def test_insufficient_funds_changes_nothing(self):
        r = self.transfer(amount=500)
        self.assertEqual(r.status_code, 422)
        self.assertEqual((self.balance(self.a), self.balance(self.b)), (100, 50))
        for acc, n in ((self.a, 1), (self.b, 1)):
            h = self.client.get(f"/accounts/{acc}/transactions").get_json()
            self.assertEqual(h["pagination"]["total_records"], n)

    def test_missing_account(self):
        r = self.transfer(to_account_id="00000000-0000-4000-8000-000000000000")
        self.assertEqual(r.status_code, 404)
        r = self.transfer(from_account_id="00000000-0000-4000-8000-000000000000")
        self.assertEqual(r.status_code, 404)
        self.assertEqual(self.balance(self.a), 100)

    def test_same_account_and_validation(self):
        self.assertEqual(self.transfer(to_account_id=self.a).status_code, 400)
        self.assertEqual(self.transfer(amount=0).status_code, 400)
        self.assertEqual(self.transfer(reference_id="").status_code, 400)
        self.assertEqual(self.transfer(from_account_id="bad").status_code, 400)

    def test_duplicate_transfer_not_applied_twice(self):
        self.assertEqual(self.transfer().status_code, 201)
        r = self.transfer()
        self.assertEqual(r.status_code, 409)
        self.assertEqual((self.balance(self.a), self.balance(self.b)), (70, 80))

    def test_rollback_when_destination_leg_fails(self):
        # Destination already used this reference_id -> credit leg fails after debit leg ran.
        self.tx(self.b, "credit", 1, "clash")
        r = self.transfer(reference_id="clash")
        self.assertEqual(r.status_code, 409)
        self.assertEqual(self.balance(self.a), 100)  # debit leg rolled back
        self.assertEqual(self.balance(self.b), 51)
        h = self.client.get(f"/accounts/{self.a}/transactions").get_json()
        self.assertEqual(h["pagination"]["total_records"], 1)

    def test_concurrent_opposite_transfers(self):
        results = []

        def worker(i):
            c = self.app.test_client()
            src, dst = (self.a, self.b) if i % 2 == 0 else (self.b, self.a)
            r = c.post(
                "/transfers",
                json={"from_account_id": src, "to_account_id": dst, "amount": 5, "reference_id": f"c{i}"},
            )
            results.append(r.status_code)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(20)]
        [t.start() for t in threads]
        [t.join() for t in threads]
        self.assertTrue(all(s == 201 for s in results), results)
        self.assertEqual(self.balance(self.a) + self.balance(self.b), 150)


if __name__ == "__main__":
    unittest.main()
