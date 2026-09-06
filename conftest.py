import os

import pytest

import database.db as db


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", os.path.join(tmp_path, "test.db"))
    db.init_db()
    db.seed_db()

    from app import app as flask_app

    flask_app.config["TESTING"] = True
    with flask_app.test_client() as test_client:
        yield test_client
