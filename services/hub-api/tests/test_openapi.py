from __future__ import annotations

import json
from pathlib import Path

from hub_api.main import app


def test_checked_in_openapi_matches_application():
    contract = Path(__file__).parents[3] / "contracts" / "openapi" / "hub-api.openapi.json"
    assert json.loads(contract.read_text(encoding="utf-8")) == app.openapi()
