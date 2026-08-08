from pathlib import Path

from hub_api.config import _repository_root


def test_repository_root_supports_source_checkout_and_shallow_container_layout():
    assert _repository_root(Path("/repo/services/hub-api")) == Path("/repo")
    assert _repository_root(Path("/app")) == Path("/app")
