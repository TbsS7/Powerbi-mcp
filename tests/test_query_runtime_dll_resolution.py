"""Testes da resolução do diretório das DLLs do ADOMD.NET
(modeling.query_runtime.resolve_adomd_dll_dir).

Espelha tests/test_tom_runtime_dll_resolution.py: é a única parte de
modeling.query_runtime testável sem pythonnet instalado e sem as DLLs
reais -- filtragem de caminhos de arquivo pura. A conexão .NET
propriamente dita (connect()) só é exercida numa máquina com Power BI
Desktop + ADOMD.NET instalados -- ver README.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from errors import AdomdDllNotFoundError
from modeling import query_runtime
from modeling.query_runtime import REQUIRED_DLLS, resolve_adomd_dll_dir


@pytest.fixture(autouse=True)
def _isolate_from_real_installations(monkeypatch):
    """resolve_adomd_dll_dir cai para instalações reais conhecidas
    (Power BI Desktop, Tabular Editor) quando nenhum outro candidato
    bate. Sem isolar isso, estes testes de "não encontrado"
    dependeriam de a máquina que os executa não ter nenhuma dessas
    ferramentas instaladas."""
    monkeypatch.setattr(query_runtime, "_candidate_dll_dirs", lambda: [])


def _write_fake_dlls(directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    for dll_name in REQUIRED_DLLS:
        (directory / dll_name).write_bytes(b"")


def test_raises_with_no_candidates_and_no_env_var(monkeypatch, tmp_path: Path):
    monkeypatch.delenv("ADOMD_DLL_PATH", raising=False)
    empty_dir = tmp_path / "nowhere"

    with pytest.raises(AdomdDllNotFoundError) as exc_info:
        resolve_adomd_dll_dir(extra_candidates=[empty_dir])

    assert str(empty_dir) in exc_info.value.searched_paths


def test_finds_dlls_via_adomd_dll_path_env_var(monkeypatch, tmp_path: Path):
    dll_dir = tmp_path / "custom_adomd_dlls"
    _write_fake_dlls(dll_dir)
    monkeypatch.setenv("ADOMD_DLL_PATH", str(dll_dir))

    resolved = resolve_adomd_dll_dir()

    assert resolved == dll_dir


def test_env_var_takes_priority_over_other_candidates(monkeypatch, tmp_path: Path):
    env_dir = tmp_path / "env_dlls"
    other_dir = tmp_path / "other_dlls"
    _write_fake_dlls(env_dir)
    _write_fake_dlls(other_dir)
    monkeypatch.setenv("ADOMD_DLL_PATH", str(env_dir))

    resolved = resolve_adomd_dll_dir(extra_candidates=[other_dir])

    assert resolved == env_dir


def test_falls_back_to_extra_candidates_when_env_var_unset(monkeypatch, tmp_path: Path):
    monkeypatch.delenv("ADOMD_DLL_PATH", raising=False)
    candidate_dir = tmp_path / "power_bi_desktop_bin"
    _write_fake_dlls(candidate_dir)

    resolved = resolve_adomd_dll_dir(extra_candidates=[candidate_dir])

    assert resolved == candidate_dir


def test_skips_candidate_missing_one_required_dll(monkeypatch, tmp_path: Path):
    monkeypatch.delenv("ADOMD_DLL_PATH", raising=False)
    incomplete_dir = tmp_path / "incomplete"
    incomplete_dir.mkdir()
    (incomplete_dir / REQUIRED_DLLS[0]).write_bytes(b"")
    # faltam as outras DLLs obrigatórias

    complete_dir = tmp_path / "complete"
    _write_fake_dlls(complete_dir)

    resolved = resolve_adomd_dll_dir(extra_candidates=[incomplete_dir, complete_dir])

    assert resolved == complete_dir


def test_returns_first_matching_candidate_in_order(monkeypatch, tmp_path: Path):
    monkeypatch.delenv("ADOMD_DLL_PATH", raising=False)
    first_dir = tmp_path / "first"
    second_dir = tmp_path / "second"
    _write_fake_dlls(first_dir)
    _write_fake_dlls(second_dir)

    resolved = resolve_adomd_dll_dir(extra_candidates=[first_dir, second_dir])

    assert resolved == first_dir


def test_error_lists_all_searched_paths(monkeypatch, tmp_path: Path):
    monkeypatch.delenv("ADOMD_DLL_PATH", raising=False)
    dir_a = tmp_path / "a"
    dir_b = tmp_path / "b"

    with pytest.raises(AdomdDllNotFoundError) as exc_info:
        resolve_adomd_dll_dir(extra_candidates=[dir_a, dir_b])

    assert str(dir_a) in exc_info.value.searched_paths
    assert str(dir_b) in exc_info.value.searched_paths
