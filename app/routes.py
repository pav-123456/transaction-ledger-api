"""HTTP layer: parse -> validate -> call service -> serialise."""
from flask import Blueprint, jsonify, request

from . import services, validation
from .db import get_db
from .errors import ApiError

bp = Blueprint("api", __name__)


def _json_body():
    data = request.get_json(force=True, silent=True)
    if not isinstance(data, dict):
        raise ApiError(400, "INVALID_REQUEST_BODY", "Request body must be a valid JSON object")
    return data


@bp.get("/health")
def health():
    return jsonify({"status": "ok"})


# ---------------------------------------------------------------- accounts
@bp.post("/accounts")
def create_account():
    name = validation.validate_account_payload(_json_body())
    account = services.create_account(get_db(), name)
    return jsonify(services.account_to_dict(account)), 201


@bp.get("/accounts/<account_id>")
def get_account(account_id):
    account_id = validation.validate_account_id_path(account_id)
    return jsonify(services.account_to_dict(services.get_account(get_db(), account_id)))


@bp.get("/accounts/<account_id>/balance")
def get_balance(account_id):
    account_id = validation.validate_account_id_path(account_id)
    account = services.get_account(get_db(), account_id)
    return jsonify({"account_id": account["id"], "balance": services._money(account["balance"])})


# ------------------------------------------------------------ transactions
def _create_transaction(path_account_id=None):
    data = _json_body()
    payload = validation.validate_transaction_payload(data, path_account_id)
    tx, account = services.add_transaction(
        get_db(),
        payload["account_id"],
        payload["type"],
        payload["amount"],
        payload["description"],
        payload["reference_id"],
    )
    return (
        jsonify(
            {
                "transaction": services.tx_to_dict(tx),
                "balance": services._money(account["balance"]),
            }
        ),
        201,
    )


@bp.post("/accounts/<account_id>/transactions")
def add_transaction_for_account(account_id):
    return _create_transaction(validation.validate_account_id_path(account_id))


@bp.post("/transactions")
def add_transaction():
    """Alternative form: account_id supplied in the request body."""
    return _create_transaction()


@bp.get("/accounts/<account_id>/transactions")
def list_transactions(account_id):
    account_id = validation.validate_account_id_path(account_id)
    page, limit, tx_type = validation.parse_pagination(request.args)
    rows, total = services.list_transactions(get_db(), account_id, tx_type, page, limit)
    return jsonify(
        {
            "account_id": account_id,
            "data": [services.tx_to_dict(r) for r in rows],
            "pagination": services.pagination_meta(page, limit, total),
        }
    )


# --------------------------------------------------------------- transfers
@bp.post("/transfers")
def create_transfer():
    payload = validation.validate_transfer_payload(_json_body())
    transfer_id, debit, credit, src, dst = services.transfer(
        get_db(),
        payload["from_account_id"],
        payload["to_account_id"],
        payload["amount"],
        payload["description"],
        payload["reference_id"],
    )
    return (
        jsonify(
            {
                "transfer_id": transfer_id,
                "amount": services._money(payload["amount"]),
                "reference_id": payload["reference_id"],
                "from_account": {"id": src["id"], "balance": services._money(src["balance"])},
                "to_account": {"id": dst["id"], "balance": services._money(dst["balance"])},
                "transactions": [services.tx_to_dict(debit), services.tx_to_dict(credit)],
            }
        ),
        201,
    )
