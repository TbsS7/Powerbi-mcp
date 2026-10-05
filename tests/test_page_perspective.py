"""Testes de page_writer.set_page_perspective: perspectiva da página no
"Personalizar visuais".

Fontes: doc oficial "Let users personalize visuals" (Formatar página ->
Personalizar visual -> perspectiva do leitor); schema oficial page/1.4.0
(`PersonalizeVisual` = show / perspectiveRef / applyToAllPages); e
comparação com o Desktop (2026-09-30): ao escolher "Vendas" pela UI, o
page.json ganhou só `objects.personalizeVisual[0].properties.
perspectiveRef` = Literal "'Vendas'". O liga/desliga do recurso no
relatório é `settings.allowInlineExploration` do report.json (schema
report/3.3.0: "Allows personalize this visual").
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from errors import PerspectiveNotFoundError
from modeling import connection
from modeling.metadata import ColumnInfo, PerspectiveInfo, PerspectiveTableInfo, TableInfo
from tests.fakes.fake_tom import FakeTomRuntime
from tests.schema_validation import validate_page_json
from visuals import formatting, page_writer


@pytest.fixture
def project_dir(tmp_path: Path) -> Path:
    root = tmp_path / "VendasProject"
    root.mkdir()
    (root / "Vendas.pbip").write_text("{}", encoding="utf-8")
    (root / "Vendas.Report").mkdir()
    page_writer.create_report_page(pbip_path=str(root), page_name="Pagina1")
    return root


@pytest.fixture
def connected() -> FakeTomRuntime:
    fake = FakeTomRuntime(database_name="Vendas")
    fake.add_table(TableInfo(name="Vendas", columns=(ColumnInfo(name="Valor", data_type="Double"),)))
    fake.create_perspective(PerspectiveInfo(
        name="Visão D'Ávila", description=None, tables=(PerspectiveTableInfo(table_name="Vendas", include_all=True),),
    ))
    connection.set_active_runtime(fake)
    return fake


def _page(project_dir: Path) -> dict:
    return json.loads(
        (project_dir / "Vendas.Report" / "definition" / "pages" / "Pagina1" / "page.json").read_text(encoding="utf-8")
    )


def _report_path(project_dir: Path) -> Path:
    return project_dir / "Vendas.Report" / "definition" / "report.json"


def test_sets_perspective_like_desktop_and_keeps_other_objects(project_dir, connected):
    formatting.set_page_background(pbip_path=str(project_dir), page_name="Pagina1", color="#F3F2F1")

    result = page_writer.set_page_perspective(
        pbip_path=str(project_dir), page_name="Pagina1", perspective="Visão D'Ávila"
    )

    page = _page(project_dir)
    assert page["objects"]["personalizeVisual"] == [
        {"properties": {"perspectiveRef": {"expr": {"Literal": {"Value": "'Visão D''Ávila'"}}}}}
    ]
    assert "background" in page["objects"]
    validate_page_json(page)
    assert result["perspective"] == "Visão D'Ávila"


def test_none_goes_back_to_default_fields(project_dir, connected):
    page_writer.set_page_perspective(pbip_path=str(project_dir), page_name="Pagina1", perspective="Visão D'Ávila")

    page_writer.set_page_perspective(pbip_path=str(project_dir), page_name="Pagina1", perspective=None)

    assert "objects" not in _page(project_dir)


def test_unknown_perspective_is_rejected_without_writing(project_dir, connected):
    before = _page(project_dir)

    with pytest.raises(PerspectiveNotFoundError):
        page_writer.set_page_perspective(pbip_path=str(project_dir), page_name="Pagina1", perspective="NaoExiste")

    assert _page(project_dir) == before


def test_offline_reads_perspectives_from_tmdl(project_dir):
    connection.clear_active_runtime()
    perspectives_dir = project_dir / "Vendas.SemanticModel" / "definition" / "perspectives"
    perspectives_dir.mkdir(parents=True)
    (project_dir / "Vendas.SemanticModel" / "definition" / "tables").mkdir()
    (perspectives_dir / "Minha Visao.tmdl").write_text(
        "/// descrição\nperspective 'Minha Visão'\n\n\tperspectiveTable Vendas\n\t\tincludeAll\n", encoding="utf-8"
    )

    page_writer.set_page_perspective(pbip_path=str(project_dir), page_name="Pagina1", perspective="Minha Visão")

    ref = _page(project_dir)["objects"]["personalizeVisual"][0]["properties"]["perspectiveRef"]
    assert ref == {"expr": {"Literal": {"Value": "'Minha Visão'"}}}
    with pytest.raises(PerspectiveNotFoundError):
        page_writer.set_page_perspective(pbip_path=str(project_dir), page_name="Pagina1", perspective="Outra")


@pytest.mark.parametrize(("settings", "expected"), [
    ({"allowInlineExploration": True}, True),
    ({"allowInlineExploration": False}, False),
    ({}, False),
])
def test_reports_whether_personalize_visuals_is_on(project_dir, connected, settings, expected):
    report = json.loads(_report_path(project_dir).read_text(encoding="utf-8"))
    report["settings"] = settings
    _report_path(project_dir).write_text(json.dumps(report), encoding="utf-8")

    result = page_writer.set_page_perspective(
        pbip_path=str(project_dir), page_name="Pagina1", perspective="Visão D'Ávila"
    )

    assert result["personalize_visuals_enabled"] is expected
    if not expected:
        assert "Personalizar visuais" in result["note"]
