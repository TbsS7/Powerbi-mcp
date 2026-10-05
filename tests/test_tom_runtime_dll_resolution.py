"""Testes da resolução do diretório das DLLs do TOM
(modeling.tom_runtime.resolve_tom_dll_dir).

Esta é a única parte de modeling.tom_runtime testável sem pythonnet
instalado e sem as DLLs reais: é filtragem de caminhos de arquivo pura.
A conexão .NET propriamente dita (connect()) só é exercida em uma
máquina com Power BI Desktop + TOM instalados -- ver README.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from errors import TomDllNotFoundError
from modeling import tom_runtime
from modeling.tom_runtime import REQUIRED_DLLS, resolve_tom_dll_dir


@pytest.fixture(autouse=True)
def _isolate_from_real_installations(monkeypatch):
    """resolve_tom_dll_dir cai para instalações reais conhecidas
    (Power BI Desktop, Tabular Editor, SQL Server SDK) quando nenhum
    outro candidato bate. Sem isolar isso, estes testes de "não
    encontrado" dependeriam de a máquina que os executa não ter nenhuma
    dessas ferramentas instaladas -- o que não é uma suposição segura em
    CI ou na máquina de outro desenvolvedor."""
    monkeypatch.setattr(tom_runtime, "_candidate_dll_dirs", lambda: [])


def _write_fake_dlls(directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    for dll_name in REQUIRED_DLLS:
        (directory / dll_name).write_bytes(b"")


def test_raises_with_no_candidates_and_no_env_var(monkeypatch, tmp_path: Path):
    monkeypatch.delenv("TOM_DLL_PATH", raising=False)
    empty_dir = tmp_path / "nowhere"

    with pytest.raises(TomDllNotFoundError) as exc_info:
        resolve_tom_dll_dir(extra_candidates=[empty_dir])

    assert str(empty_dir) in exc_info.value.searched_paths


def test_finds_dlls_via_tom_dll_path_env_var(monkeypatch, tmp_path: Path):
    dll_dir = tmp_path / "custom_tom_dlls"
    _write_fake_dlls(dll_dir)
    monkeypatch.setenv("TOM_DLL_PATH", str(dll_dir))

    resolved = resolve_tom_dll_dir()

    assert resolved == dll_dir


def test_env_var_takes_priority_over_other_candidates(monkeypatch, tmp_path: Path):
    env_dir = tmp_path / "env_dlls"
    other_dir = tmp_path / "other_dlls"
    _write_fake_dlls(env_dir)
    _write_fake_dlls(other_dir)
    monkeypatch.setenv("TOM_DLL_PATH", str(env_dir))

    resolved = resolve_tom_dll_dir(extra_candidates=[other_dir])

    assert resolved == env_dir


def test_falls_back_to_extra_candidates_when_env_var_unset(monkeypatch, tmp_path: Path):
    monkeypatch.delenv("TOM_DLL_PATH", raising=False)
    candidate_dir = tmp_path / "power_bi_desktop_bin"
    _write_fake_dlls(candidate_dir)

    resolved = resolve_tom_dll_dir(extra_candidates=[candidate_dir])

    assert resolved == candidate_dir


def test_skips_candidate_missing_one_required_dll(monkeypatch, tmp_path: Path):
    monkeypatch.delenv("TOM_DLL_PATH", raising=False)
    incomplete_dir = tmp_path / "incomplete"
    incomplete_dir.mkdir()
    (incomplete_dir / REQUIRED_DLLS[0]).write_bytes(b"")
    # faltam as outras DLLs obrigatórias

    complete_dir = tmp_path / "complete"
    _write_fake_dlls(complete_dir)

    resolved = resolve_tom_dll_dir(extra_candidates=[incomplete_dir, complete_dir])

    assert resolved == complete_dir


def test_returns_first_matching_candidate_in_order(monkeypatch, tmp_path: Path):
    monkeypatch.delenv("TOM_DLL_PATH", raising=False)
    first_dir = tmp_path / "first"
    second_dir = tmp_path / "second"
    _write_fake_dlls(first_dir)
    _write_fake_dlls(second_dir)

    resolved = resolve_tom_dll_dir(extra_candidates=[first_dir, second_dir])

    assert resolved == first_dir


def test_error_lists_all_searched_paths(monkeypatch, tmp_path: Path):
    monkeypatch.delenv("TOM_DLL_PATH", raising=False)
    dir_a = tmp_path / "a"
    dir_b = tmp_path / "b"

    with pytest.raises(TomDllNotFoundError) as exc_info:
        resolve_tom_dll_dir(extra_candidates=[dir_a, dir_b])

    assert str(dir_a) in exc_info.value.searched_paths
    assert str(dir_b) in exc_info.value.searched_paths
