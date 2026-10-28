"""Consistent error type and JSON error handlers.

Every error response has the shape:
    {"error": {"code": "...", "message": "...", "details": ...}}
"""
from flask import jsonify
from werkzeug.exceptions import HTTPException


class ApiError(Exception):
    def __init__(self, status, code, message, details=None):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.details = details

    def to_response(self):
        body = {"code": self.code, "message": self.message}
        if self.details is not None:
            body["details"] = self.details
        return jsonify({"error": body}), self.status


class ValidationError(ApiError):
    def __init__(self, errors, message="Request validation failed"):
        super().__init__(400, "VALIDATION_ERROR", message, errors)


class AccountNotFound(ApiError):
    def __init__(self, account_id):
        super().__init__(404, "ACCOUNT_NOT_FOUND", f"Account '{account_id}' not found")


class InsufficientBalance(ApiError):
    def __init__(self, balance, requested):
        super().__init__(
            422,
            "INSUFFICIENT_BALANCE",
            "Insufficient balance for this debit",
            {"balance": balance, "requested": requested},
        )


class DuplicateTransaction(ApiError):
    def __init__(self, existing):
        super().__init__(
            409,
            "DUPLICATE_TRANSACTION",
            "A transaction with this reference_id already exists for this account",
            {"existing_transaction": existing},
        )


def register_error_handlers(app):
    @app.errorhandler(ApiError)
    def _api_error(err):
        return err.to_response()

    @app.errorhandler(HTTPException)
    def _http_error(err):
        codes = {
            404: "NOT_FOUND",
            405: "METHOD_NOT_ALLOWED",
            415: "UNSUPPORTED_MEDIA_TYPE",
        }
        code = codes.get(err.code, "HTTP_ERROR")
        message = err.description
        if err.code == 405:
            message = "Method not allowed for this resource (transactions are immutable)"
        return ApiError(err.code, code, message).to_response()

    @app.errorhandler(Exception)
    def _unexpected(err):
        app.logger.exception("Unhandled error")
        return ApiError(500, "INTERNAL_ERROR", "An unexpected error occurred").to_response()
