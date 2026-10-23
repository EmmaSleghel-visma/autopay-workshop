"""Flask app factory. Pages (upload, transaction list, import summary) are owned by Iulia."""

import io
import math
import os
from datetime import date

from flask import Flask, current_app, render_template, request

from .. import rules
from ..service import import_transactions, importer_for
from ..storage import TransactionStore
from .reasons import reason

DEFAULT_DB = "fraud_detection.db"
PAGE_SIZE = 100  # transactions per page, newest first


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
        store = current_app.config["STORE"]
        total = store.count()
        pages = max(1, math.ceil(total / PAGE_SIZE))
        page = min(max(request.args.get("page", 1, type=int), 1), pages)
        offset = (page - 1) * PAGE_SIZE
        rows = store.page(offset, PAGE_SIZE)
        return render_template(
            "transactions.html",
            transactions=rows,
            page=page,
            pages=pages,
            total=total,
            first=offset + 1 if rows else 0,
            last=offset + len(rows),
            reason=reason,
        )

    return app
