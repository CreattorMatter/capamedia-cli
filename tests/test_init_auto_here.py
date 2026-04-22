"""Tests para init: auto-deteccion de --here cuando CWD ya parece workspace."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from capamedia_cli.commands.init import init_project


def test_init_auto_here_when_cwd_has_legacy(tmp_path: Path, monkeypatch) -> None:
    """Si CWD tiene legacy/, usar --here automatico (no crear subcarpeta)."""
    workspace = tmp_path / "wstecnicos0008"
    workspace.mkdir()
    (workspace / "legacy").mkdir()
    monkeypatch.chdir(workspace)

    with patch("capamedia_cli.commands.init.scaffold_project") as mock_scaffold:
        mock_scaffold.return_value = (0, [])
        init_project(service_name="wstecnicos0008", ai="none", here=False, force=True)

    mock_scaffold.assert_called_once()
    target_dir = mock_scaffold.call_args.kwargs["target_dir"]
    # El target debe ser el workspace actual, NO workspace/wstecnicos0008
    assert target_dir == workspace
    # La subcarpeta NO debe existir
    assert not (workspace / "wstecnicos0008").exists()


def test_init_auto_here_when_cwd_has_destino(tmp_path: Path, monkeypatch) -> None:
    workspace = tmp_path / "svc-workspace"
    workspace.mkdir()
    (workspace / "destino").mkdir()
    monkeypatch.chdir(workspace)

    with patch("capamedia_cli.commands.init.scaffold_project") as mock_scaffold:
        mock_scaffold.return_value = (0, [])
        init_project(service_name="somesvc", ai="none", here=False, force=True)

    target_dir = mock_scaffold.call_args.kwargs["target_dir"]
    assert target_dir == workspace


def test_init_auto_here_when_cwd_name_matches_service(tmp_path: Path, monkeypatch) -> None:
    """Si CWD se llama igual que el servicio, usar --here automatico."""
    workspace = tmp_path / "wsclientes0007"
    workspace.mkdir()
    monkeypatch.chdir(workspace)

    with patch("capamedia_cli.commands.init.scaffold_project") as mock_scaffold:
        mock_scaffold.return_value = (0, [])
        init_project(service_name="wsclientes0007", ai="none", here=False, force=True)

    target_dir = mock_scaffold.call_args.kwargs["target_dir"]
    assert target_dir == workspace


def test_init_creates_subfolder_when_cwd_not_workspace(tmp_path: Path, monkeypatch) -> None:
    """Si CWD NO es workspace, crear subcarpeta como antes (comportamiento clasico)."""
    parent = tmp_path / "BancoPichincha"
    parent.mkdir()
    monkeypatch.chdir(parent)

    with patch("capamedia_cli.commands.init.scaffold_project") as mock_scaffold:
        mock_scaffold.return_value = (0, [])
        init_project(service_name="newsvc0001", ai="none", here=False, force=True)

    target_dir = mock_scaffold.call_args.kwargs["target_dir"]
    # Debe crear subcarpeta
    assert target_dir == parent / "newsvc0001"


def test_init_explicit_here_still_works(tmp_path: Path, monkeypatch) -> None:
    """--here explicito sigue funcionando igual."""
    workspace = tmp_path / "empty-dir"
    workspace.mkdir()
    monkeypatch.chdir(workspace)

    with patch("capamedia_cli.commands.init.scaffold_project") as mock_scaffold:
        mock_scaffold.return_value = (0, [])
        init_project(service_name=None, ai="none", here=True, force=True)

    target_dir = mock_scaffold.call_args.kwargs["target_dir"]
    assert target_dir == workspace
