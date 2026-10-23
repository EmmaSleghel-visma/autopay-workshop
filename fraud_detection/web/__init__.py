"""Flask app factory. Pages (upload, transaction list, import summary) are owned by Iulia."""

import io
import os
from datetime import date

from flask import Flask, current_app, render_template, request

from .. import rules
from ..service import import_transactions, importer_for
from ..storage import TransactionStore

DEFAULT_DB = "fraud_detection.db"


def create_app(db_path: str | None = None) -> Flask:
    app = Flask(__name__)
    app.config["STORE"] = TransactionStore(db_path or os.environ.get("FRAUD_DB", DEFAULT_DB))

    @app.get("/health")
    def health():
        return {"ok": True}

    @app.get("/")
    def upload_form():
        return render_template("upload.html")

    @app.post("/upload")
    def upload():
        upload_file = request.files.get("file")
        if upload_file is None or not upload_file.filename:
            response = render_template("upload.html", error="Choose a file to upload."), 400
        else:
            source = io.TextIOWrapper(upload_file.stream, encoding="utf-8", newline="")
            summary = import_transactions(
                source,
                importer_for(upload_file.filename),
                current_app.config["STORE"],
                rules.evaluate,
                date.today(),
            )
            response = render_template("summary.html", filename=upload_file.filename, summary=summary)
        return response

    @app.get("/transactions")
    def transactions():
        return render_template("transactions.html", transactions=current_app.config["STORE"].all())

    return app
