"""Testes de visuals.project: localização e validação da pasta .Report
(formato PBIR) de um projeto .pbip.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from errors import ReportProjectNotFoundError
from visuals.project import get_definition_dir, has_pbir_definition, is_legacy_report, resolve_report_dir


def _make_pbip_project(root: Path, name: str = "Vendas") -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / f"{name}.pbip").write_text("{}", encoding="utf-8")
    report_dir = root / f"{name}.Report"
    report_dir.mkdir()
    return report_dir


def test_resolve_report_dir_from_pbip_file_path(tmp_path: Path):
    report_dir = _make_pbip_project(tmp_path)

    resolved = resolve_report_dir(str(tmp_path / "Vendas.pbip"))

    assert resolved == report_dir


def test_resolve_report_dir_from_project_root(tmp_path: Path):
    report_dir = _make_pbip_project(tmp_path)

    resolved = resolve_report_dir(str(tmp_path))

    assert resolved == report_dir


def test_resolve_report_dir_from_report_dir_directly(tmp_path: Path):
    report_dir = _make_pbip_project(tmp_path)

    resolved = resolve_report_dir(str(report_dir))

    assert resolved == report_dir


def test_resolve_report_dir_raises_when_not_found(tmp_path: Path):
    empty_dir = tmp_path / "nothing-here"
    empty_dir.mkdir()

    with pytest.raises(ReportProjectNotFoundError):
        resolve_report_dir(str(empty_dir))


def test_has_pbir_definition_true_when_definition_pages_exist(tmp_path: Path):
    report_dir = _make_pbip_project(tmp_path)
    (report_dir / "definition" / "pages").mkdir(parents=True)

    assert has_pbir_definition(report_dir) is True
    assert is_legacy_report(report_dir) is False


def test_has_pbir_definition_false_for_brand_new_report(tmp_path: Path):
    report_dir = _make_pbip_project(tmp_path)

    assert has_pbir_definition(report_dir) is False
    assert is_legacy_report(report_dir) is False


def test_is_legacy_report_true_when_report_json_at_root(tmp_path: Path):
    report_dir = _make_pbip_project(tmp_path)
    (report_dir / "report.json").write_text("{}", encoding="utf-8")

    assert is_legacy_report(report_dir) is True
    assert has_pbir_definition(report_dir) is False


def test_get_definition_dir_returns_path_when_present(tmp_path: Path):
    report_dir = _make_pbip_project(tmp_path)
    definition_dir = report_dir / "definition"
    (definition_dir / "pages").mkdir(parents=True)

    assert get_definition_dir(report_dir) == definition_dir


def test_get_definition_dir_raises_with_legacy_message(tmp_path: Path):
    report_dir = _make_pbip_project(tmp_path)
    (report_dir / "report.json").write_text("{}", encoding="utf-8")

    with pytest.raises(ReportProjectNotFoundError, match="PBIR-Legacy"):
        get_definition_dir(report_dir)


def test_get_definition_dir_raises_when_never_saved(tmp_path: Path):
    report_dir = _make_pbip_project(tmp_path)

    with pytest.raises(ReportProjectNotFoundError):
        get_definition_dir(report_dir)


# Vários projetos na mesma pasta (achado 03/10: a página do dashboard Cristallo
# foi gravada no PowerBITest01.Report, o primeiro *.Report em ordem alfabética).


def test_resolve_report_dir_follows_pbip_artifact_with_two_projects(tmp_path: Path):
    (tmp_path / "AAA.Report").mkdir()
    (tmp_path / "Vendas.Report").mkdir()
    pbip = tmp_path / "Vendas.pbip"
    pbip.write_text('{"version": "1.0", "artifacts": [{"report": {"path": "Vendas.Report"}}]}', encoding="utf-8")

    assert resolve_report_dir(str(pbip)) == tmp_path / "Vendas.Report"


def test_resolve_report_dir_prefers_same_name_when_pbip_has_no_artifact(tmp_path: Path):
    (tmp_path / "AAA.Report").mkdir()
    (tmp_path / "Vendas.Report").mkdir()
    pbip = tmp_path / "Vendas.pbip"
    pbip.write_text("{}", encoding="utf-8")

    assert resolve_report_dir(str(pbip)) == tmp_path / "Vendas.Report"


def test_resolve_report_dir_refuses_to_guess_between_projects(tmp_path: Path):
    # revisão final: .pbip sem artifact válido e sem <nome>.Report, com dois
    # relatórios na pasta -> antes caía no primeiro em ordem alfabética.
    (tmp_path / "AAA.Report").mkdir()
    (tmp_path / "BBB.Report").mkdir()
    pbip = tmp_path / "Renomeado.pbip"
    pbip.write_text('{"artifacts": [{"report": {"path": "NaoExiste.Report"}}]}', encoding="utf-8")

    with pytest.raises(ReportProjectNotFoundError, match="Renomeado.pbip"):
        resolve_report_dir(str(pbip))
