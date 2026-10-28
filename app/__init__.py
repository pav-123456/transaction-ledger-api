"""Transaction Ledger API (Flask + SQLite)."""
import os

from flask import Flask

from .db import close_db, init_db
from .errors import register_error_handlers
from .routes import bp


def create_app(config=None):
    app = Flask(__name__)
    app.config["DATABASE"] = os.environ.get(
        "LEDGER_DB", os.path.join(os.path.dirname(os.path.dirname(__file__)), "ledger.db")
    )
    app.config["JSON_SORT_KEYS"] = False
    app.json.sort_keys = False
    if config:
        app.config.update(config)

    init_db(app.config["DATABASE"])
    app.teardown_appcontext(close_db)
    register_error_handlers(app)
    app.register_blueprint(bp)
    return app
