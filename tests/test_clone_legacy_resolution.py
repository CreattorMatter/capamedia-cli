"""Tests for clone legacy-repo resolution (Fix A + Fix B, 2026-05-15).

Origen: `capamedia clone orqclientes0027` fallaba con un generico "no se
encontro en ningun proyecto Azure conocido" que ocultaba el motivo real
(404 vs 401). Jean Pierre lo reporto en pantalla compartida.

Fix A: `_resolve_azure_repo` acumula y devuelve los errores reales de cada
       intento; `_classify_clone_failures` los clasifica en auth/not_found/mixed.
Fix B: flag `--legacy-repo` permite override del nombre del repo cuando
       ningun patron de AZURE_FALLBACK_PATTERNS matchea.
"""

from __future__ import annotations

from pathlib import Path

from capamedia_cli.commands import clone as clone_mod
from capamedia_cli.commands.clone import _classify_clone_failures, _resolve_azure_repo


# ---------------------------------------------------------------------------
# _classify_clone_failures
# ---------------------------------------------------------------------------


def test_classify_all_auth_failures() -> None:
    attempts = [
        ("tpl-bus-omnicanal/sqb-msa-x", "fatal: Authentication failed for 'https://...'"),
        ("tpl-integration-services-was/ws-x-was", "remote: TF400813: rejected"),
    ]
    assert _classify_clone_failures(attempts) == "auth"


def test_classify_all_not_found() -> None:
    attempts = [
        ("tpl-bus-omnicanal/sqb-msa-x", "remote: TF401019: The Git repository does not exist"),
        ("tpl-integration-services-was/ws-x-was", "repository not found"),
    ]
    assert _classify_clone_failures(attempts) == "not_found"


def test_classify_mixed() -> None:
    attempts = [
        ("tpl-bus-omnicanal/sqb-msa-x", "Authentication failed"),
        ("tpl-integration-services-was/ws-x-was", "repository not found"),
    ]
    assert _classify_clone_failures(attempts) == "mixed"


def test_classify_empty_is_mixed() -> None:
    assert _classify_clone_failures([]) == "mixed"


def test_classify_network_error_is_mixed() -> None:
    attempts = [("tpl-bus-omnicanal/sqb-msa-x", "timeout")]
    assert _classify_clone_failures(attempts) == "mixed"


# ---------------------------------------------------------------------------
# _resolve_azure_repo — Fix A: attempts en el 4to elemento
# ---------------------------------------------------------------------------


def test_resolve_returns_attempts_on_total_failure(tmp_path: Path, monkeypatch) -> None:
    """Cuando ningun patron funciona, se devuelven los intentos con su error."""
    def _fail(repo_name, dest, project_key="bus", shallow=False, no_single_branch=False):
        return (False, "remote: TF401019: The Git repository does not exist")

    monkeypatch.setattr(clone_mod, "_git_clone", _fail)

    path, project, repo, attempts = _resolve_azure_repo("wsclientes0099", tmp_path, False)

    assert path is None
    assert project == ""
    assert repo == ""
    # 3 patrones de AZURE_FALLBACK_PATTERNS + 2 split repos = 5 intentos
    assert len(attempts) == 5
    assert all("does not exist" in err for _repo, err in attempts)


def test_resolve_first_pattern_wins_empty_attempts(tmp_path: Path, monkeypatch) -> None:
    """Si el primer patron funciona, attempts queda vacio."""
    def _first_ok(repo_name, dest, project_key="bus", shallow=False, no_single_branch=False):
        # sqb-msa-{svc} es el primer patron (project bus)
        return (project_key == "bus" and repo_name.startswith("sqb-msa-"), "")

    monkeypatch.setattr(clone_mod, "_git_clone", _first_ok)

    path, project, repo, attempts = _resolve_azure_repo("wsclientes0076", tmp_path, False)

    assert path is not None
    assert project == "bus"
    assert repo == "sqb-msa-wsclientes0076"
    assert attempts == []


# ---------------------------------------------------------------------------
# _resolve_azure_repo — Fix B: override_repo
# ---------------------------------------------------------------------------


def test_resolve_with_override_repo_found_in_bus(tmp_path: Path, monkeypatch) -> None:
    """override_repo se prueba en los proyectos; si existe en bus, lo usa."""
    def _only_override(repo_name, dest, project_key="bus", shallow=False, no_single_branch=False):
        return (repo_name == "orq-clientes-0027-special" and project_key == "bus", "404 not found")

    monkeypatch.setattr(clone_mod, "_git_clone", _only_override)

    path, project, repo, attempts = _resolve_azure_repo(
        "orqclientes0027", tmp_path, False, override_repo="orq-clientes-0027-special"
    )

    assert path is not None
    assert project == "bus"
    assert repo == "orq-clientes-0027-special"
    assert attempts == []


def test_resolve_with_override_repo_not_found_anywhere(tmp_path: Path, monkeypatch) -> None:
    """override_repo que no existe en ningun proyecto -> None + 3 intentos."""
    def _fail(repo_name, dest, project_key="bus", shallow=False, no_single_branch=False):
        return (False, "repository not found")

    monkeypatch.setattr(clone_mod, "_git_clone", _fail)

    path, project, repo, attempts = _resolve_azure_repo(
        "orqclientes0027", tmp_path, False, override_repo="nombre-inexistente"
    )

    assert path is None
    # se probo en bus + was + middleware = 3 intentos
    assert len(attempts) == 3
    projects_tried = {repo_full.split("/")[0] for repo_full, _err in attempts}
    assert projects_tried == {
        "tpl-bus-omnicanal",
        "tpl-integration-services-was",
        "tpl-middleware",
    }


def test_resolve_override_repo_bypasses_pattern_loop(tmp_path: Path, monkeypatch) -> None:
    """Con override_repo, NO se prueban los patrones sqb-msa-/ws-/ms-."""
    tried_repos: list[str] = []

    def _record(repo_name, dest, project_key="bus", shallow=False, no_single_branch=False):
        tried_repos.append(repo_name)
        return (False, "404 not found")

    monkeypatch.setattr(clone_mod, "_git_clone", _record)

    _resolve_azure_repo(
        "orqclientes0027", tmp_path, False, override_repo="custom-repo-name"
    )

    # Solo se probo el override, ningun patron sqb-msa-/ws-/ms-
    assert tried_repos == ["custom-repo-name", "custom-repo-name", "custom-repo-name"]
