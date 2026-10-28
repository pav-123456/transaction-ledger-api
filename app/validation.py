"""Input validation. Raises ValidationError with per-field details."""
import math
import uuid
from decimal import Decimal, InvalidOperation

from .errors import ApiError, ValidationError

MAX_AMOUNT = Decimal("1000000000")  # 1 billion
MAX_NAME = 100
MAX_DESCRIPTION = 255
MAX_REFERENCE = 100
TX_TYPES = ("credit", "debit")


def _err(field, code, message):
    return {"field": field, "code": code, "message": message}


def is_valid_uuid(value):
    try:
        return str(uuid.UUID(str(value))) == str(value).lower()
    except (ValueError, AttributeError, TypeError):
        return False


def validate_account_id_path(account_id):
    if not is_valid_uuid(account_id):
        raise ApiError(400, "INVALID_ACCOUNT_ID", f"'{account_id}' is not a valid account id")
    return account_id.lower()


def _amount(value, errors, field="amount"):
    """Returns amount in minor units (int) or None (and appends an error)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        errors.append(_err(field, "INVALID_AMOUNT", "amount must be a number"))
        return None
    if isinstance(value, float) and not math.isfinite(value):
        errors.append(_err(field, "INVALID_AMOUNT", "amount must be a finite number"))
        return None
    d = Decimal(str(value))
    if d <= 0:
        errors.append(_err(field, "INVALID_AMOUNT", "amount must be greater than 0"))
        return None
    if d > MAX_AMOUNT:
        errors.append(_err(field, "INVALID_AMOUNT", f"amount must not exceed {MAX_AMOUNT}"))
        return None
    try:
        if d != d.quantize(Decimal("0.01")):
            errors.append(_err(field, "INVALID_AMOUNT", "amount can have at most 2 decimal places"))
            return None
    except InvalidOperation:
        errors.append(_err(field, "INVALID_AMOUNT", "amount is not valid"))
        return None
    return int(d * 100)


def _string(data, field, errors, *, required, max_len):
    value = data.get(field)
    if value is None:
        if required:
            errors.append(_err(field, "REQUIRED", f"{field} is required"))
        return None
    if not isinstance(value, str):
        errors.append(_err(field, "INVALID_TYPE", f"{field} must be a string"))
        return None
    value = value.strip()
    if required and not value:
        errors.append(_err(field, "REQUIRED", f"{field} must not be empty"))
        return None
    if len(value) > max_len:
        errors.append(_err(field, "TOO_LONG", f"{field} must be at most {max_len} characters"))
        return None
    return value


def _reject_unknown(data, allowed, errors):
    for key in data:
        if key not in allowed:
            msg = (
                "balance cannot be set by the client; it is always managed by the system"
                if key == "balance"
                else f"unknown or read-only field '{key}'"
            )
            errors.append(_err(key, "UNKNOWN_FIELD", msg))


def validate_account_payload(data):
    errors = []
    _reject_unknown(data, {"name"}, errors)
    name = _string(data, "name", errors, required=True, max_len=MAX_NAME)
    if errors:
        raise ValidationError(errors)
    return name


def _account_id_field(value, field, errors):
    if value is None:
        errors.append(_err(field, "REQUIRED", f"{field} is required"))
        return None
    if not isinstance(value, str) or not is_valid_uuid(value):
        errors.append(_err(field, "INVALID_ACCOUNT_ID", f"{field} is not a valid account id"))
        return None
    return value.lower()


def validate_transaction_payload(data, path_account_id=None):
    errors = []
    _reject_unknown(data, {"account_id", "type", "amount", "description", "reference_id"}, errors)

    body_account = data.get("account_id")
    if path_account_id is not None:
        account_id = path_account_id
        if body_account is not None and str(body_account).lower() != path_account_id:
            errors.append(_err("account_id", "MISMATCH", "account_id in body does not match the URL"))
    else:
        account_id = _account_id_field(body_account, "account_id", errors)

    tx_type = data.get("type")
    if tx_type is None:
        errors.append(_err("type", "REQUIRED", "type is required"))
    elif tx_type not in TX_TYPES:
        errors.append(_err("type", "INVALID_TYPE", "type must be either 'credit' or 'debit'"))

    if "amount" not in data:
        errors.append(_err("amount", "REQUIRED", "amount is required"))
        amount = None
    else:
        amount = _amount(data["amount"], errors)

    reference_id = _string(data, "reference_id", errors, required=True, max_len=MAX_REFERENCE)
    description = _string(data, "description", errors, required=False, max_len=MAX_DESCRIPTION) or ""

    if errors:
        raise ValidationError(errors)
    return {
        "account_id": account_id,
        "type": tx_type,
        "amount": amount,
        "description": description,
        "reference_id": reference_id,
    }


def validate_transfer_payload(data):
    errors = []
    _reject_unknown(
        data, {"from_account_id", "to_account_id", "amount", "description", "reference_id"}, errors
    )
    src = _account_id_field(data.get("from_account_id"), "from_account_id", errors)
    dst = _account_id_field(data.get("to_account_id"), "to_account_id", errors)
    if src and dst and src == dst:
        errors.append(_err("to_account_id", "SAME_ACCOUNT", "cannot transfer to the same account"))
    if "amount" not in data:
        errors.append(_err("amount", "REQUIRED", "amount is required"))
        amount = None
    else:
        amount = _amount(data["amount"], errors)
    reference_id = _string(data, "reference_id", errors, required=True, max_len=MAX_REFERENCE)
    description = _string(data, "description", errors, required=False, max_len=MAX_DESCRIPTION) or ""
    if errors:
        raise ValidationError(errors)
    return {
        "from_account_id": src,
        "to_account_id": dst,
        "amount": amount,
        "description": description,
        "reference_id": reference_id,
    }


def parse_pagination(args):
    errors = []

    def _int(name, default, minimum, maximum=None):
        raw = args.get(name)
        if raw is None:
            return default
        if not raw.isdigit():
            errors.append(_err(name, "INVALID_PAGINATION", f"{name} must be a positive integer"))
            return default
        value = int(raw)
        if value < minimum or (maximum is not None and value > maximum):
            rng = f">= {minimum}" if maximum is None else f"between {minimum} and {maximum}"
            errors.append(_err(name, "INVALID_PAGINATION", f"{name} must be {rng}"))
            return default
        return value

    page = _int("page", 1, 1)
    limit = _int("limit", 10, 1, 100)
    tx_type = args.get("type")
    if tx_type is not None and tx_type not in TX_TYPES:
        errors.append(_err("type", "INVALID_TYPE", "type must be either 'credit' or 'debit'"))
    if errors:
        raise ApiError(400, "INVALID_QUERY_PARAMETERS", "Invalid query parameters", errors)
    return page, limit, tx_type
