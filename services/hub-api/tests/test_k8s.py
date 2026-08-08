from __future__ import annotations

import importlib.util
from pathlib import Path
import shutil

import pytest
import yaml


REPOSITORY_ROOT = Path(__file__).parents[3]
PREFLIGHT_PATH = REPOSITORY_ROOT / "deploy" / "k8s" / "preflight.py"
SPEC = importlib.util.spec_from_file_location("hub_k8s_preflight", PREFLIGHT_PATH)
assert SPEC and SPEC.loader
preflight = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(preflight)


@pytest.mark.skipif(shutil.which("kubectl") is None, reason="kubectl is required for Kustomize")
def test_kubernetes_base_has_required_production_invariants():
    documents = preflight.render_kustomize(REPOSITORY_ROOT / "deploy" / "k8s" / "base")
    documents += preflight.read_documents(
        REPOSITORY_ROOT / "deploy" / "k8s" / "migration-job.yaml"
    )
    errors, placeholders = preflight.validate(documents, allow_placeholders=True)
    assert errors == []
    assert placeholders


@pytest.mark.skipif(shutil.which("kubectl") is None, reason="kubectl is required for Kustomize")
def test_production_preflight_rejects_checked_in_placeholders():
    documents = preflight.render_kustomize(REPOSITORY_ROOT / "deploy" / "k8s" / "base")
    documents += preflight.read_documents(
        REPOSITORY_ROOT / "deploy" / "k8s" / "migration-job.yaml"
    )
    errors, _ = preflight.validate(documents, allow_placeholders=False)
    assert errors == ["production preflight rejects placeholder image or host values"]


def test_kubernetes_sources_do_not_contain_secret_values():
    documents = []
    for path in (REPOSITORY_ROOT / "deploy" / "k8s").rglob("*.yaml"):
        documents.extend(item for item in yaml.safe_load_all(path.read_text(encoding="utf-8")) if item)
    assert all(document.get("kind") != "Secret" for document in documents)
    assert not (REPOSITORY_ROOT / "deploy" / "k8s" / "secret.yaml").exists()
