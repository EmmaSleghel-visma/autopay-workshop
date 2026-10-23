"""Flask app factory. Pages (upload, transaction list, import summary) are owned by Iulia."""

import os

from flask import Flask

from ..storage import TransactionStore

DEFAULT_DB = "fraud_detection.db"


def create_app(db_path: str | None = None) -> Flask:
    app = Flask(__name__)
    app.config["STORE"] = TransactionStore(db_path or os.environ.get("FRAUD_DB", DEFAULT_DB))

    @app.get("/health")
    def health():
        return {"ok": True}

    return app
