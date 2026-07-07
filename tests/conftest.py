import os

import pytest
from fastapi.testclient import TestClient

from gallery import config, db


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("GALLERY_DATA_DIR", str(tmp_path))
    db.reset_connection()
    cfg = config.init_config(force=True)
    yield tmp_path, cfg
    db.reset_connection()


@pytest.fixture
def client(data_dir):
    from gallery.server import app

    with TestClient(app) as c:
        yield c


@pytest.fixture
def token(data_dir):
    return data_dir[1]["token"]
