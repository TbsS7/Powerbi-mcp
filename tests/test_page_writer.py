"""Testes de visuals.page_writer: create_report_page e a escrita de
page.json / pages.json / version.json / report.json.

Cada arquivo escrito é validado contra o schema oficial correspondente
(tests/schema_validation.py), não contra suposições deste projeto.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from errors import (
    DrillthroughFieldAlreadyExistsError,
    DrillthroughFieldNotFoundError,
    PageAlreadyExistsError,
    PageNotFoundError,
    ReportProjectNotFoundError,
    UnknownFieldError,
)
from modeling import connection
from modeling.metadata import ColumnInfo, TableInfo
from tests.fakes.fake_tom import FakeTomRuntime
from tests.schema_validation import (
    validate_page_json,
    validate_pages_metadata_json,
    validate_report_json,
    validate_version_json,
)
from visuals import page_writer


@pytest.fixture
def brand_new_project(tmp_path: Path) -> Path:
    """Projeto .pbip cujo relatório nunca foi salvo em PBIR nem em
    PBIR-Legacy -- create_report_page precisa criar o esqueleto
    definition/ do zero."""
    root = tmp_path / "VendasProject"
    root.mkdir()
    (root / "Vendas.pbip").write_text("{}", encoding="utf-8")
    (root / "Vendas.Report").mkdir()
    return root


@pytest.fixture
def legacy_project(tmp_path: Path) -> Path:
    root = tmp_path / "LegacyProject"
    root.mkdir()
    (root / "Legado.pbip").write_text("{}", encoding="utf-8")
    report_dir = root / "Legado.Report"
    report_dir.mkdir()
    (report_dir / "report.json").write_text("{}", encoding="utf-8")
    return root


def _definition_dir(project_root: Path, report_name: str = "Vendas") -> Path:
    return project_root / f"{report_name}.Report" / "definition"


def test_creates_scaffold_and_first_page_when_never_saved(brand_new_project: Path):
    result = page_writer.create_report_page(
        pbip_path=str(brand_new_project), page_name="Pagina1", display_name="Visão geral"
    )

    assert result["page_name"] == "Pagina1"

    definition_dir = _definition_dir(brand_new_project)
    assert (definition_dir / "version.json").is_file()
    assert (definition_dir / "report.json").is_file()
    assert (definition_dir / "pages" / "pages.json").is_file()
    assert (definition_dir / "pages" / "Pagina1" / "page.json").is_file()

    validate_version_json(json.loads((definition_dir / "version.json").read_text(encoding="utf-8")))
    validate_report_json(json.loads((definition_dir / "report.json").read_text(encoding="utf-8")))
    pages_json = json.loads((definition_dir / "pages" / "pages.json").read_text(encoding="utf-8"))
    validate_pages_metadata_json(pages_json)
    page_json = json.loads(
        (definition_dir / "pages" / "Pagina1" / "page.json").read_text(encoding="utf-8")
    )
    validate_page_json(page_json)

    assert page_json["displayName"] == "Visão geral"
    assert page_json["name"] == "Pagina1"


def test_first_page_becomes_active_page(brand_new_project: Path):
    page_writer.create_report_page(pbip_path=str(brand_new_project), page_name="Pagina1")

    pages_json = json.loads(
        (_definition_dir(brand_new_project) / "pages" / "pages.json").read_text(encoding="utf-8")
    )
    assert pages_json["activePageName"] == "Pagina1"
    assert pages_json["pageOrder"] == ["Pagina1"]


def test_second_page_is_appended_without_changing_active_page(brand_new_project: Path):
    page_writer.create_report_page(pbip_path=str(brand_new_project), page_name="Pagina1")
    page_writer.create_report_page(pbip_path=str(brand_new_project), page_name="Pagina2")

    pages_json = json.loads(
        (_definition_dir(brand_new_project) / "pages" / "pages.json").read_text(encoding="utf-8")
    )
    assert pages_json["pageOrder"] == ["Pagina1", "Pagina2"]
    assert pages_json["activePageName"] == "Pagina1"


def test_does_not_recreate_scaffold_when_definition_already_exists(brand_new_project: Path):
    page_writer.create_report_page(pbip_path=str(brand_new_project), page_name="Pagina1")
    definition_dir = _definition_dir(brand_new_project)
    version_before = (definition_dir / "version.json").read_text(encoding="utf-8")

    page_writer.create_report_page(pbip_path=str(brand_new_project), page_name="Pagina2")

    assert (definition_dir / "version.json").read_text(encoding="utf-8") == version_before


def test_display_name_defaults_to_page_name(brand_new_project: Path):
    page_writer.create_report_page(pbip_path=str(brand_new_project), page_name="Resumo")

    page_json = json.loads(
        (_definition_dir(brand_new_project) / "pages" / "Resumo" / "page.json").read_text(
            encoding="utf-8"
        )
    )
    assert page_json["displayName"] == "Resumo"


def test_raises_when_page_name_already_exists(brand_new_project: Path):
    page_writer.create_report_page(pbip_path=str(brand_new_project), page_name="Pagina1")

    with pytest.raises(PageAlreadyExistsError):
        page_writer.create_report_page(pbip_path=str(brand_new_project), page_name="Pagina1")


def test_raises_for_legacy_pbir_report(legacy_project: Path):
    with pytest.raises(ReportProjectNotFoundError, match="PBIR-Legacy"):
        page_writer.create_report_page(pbip_path=str(legacy_project), page_name="Pagina1")


# --- delete_report_page -----------------------------------------------


def test_delete_report_page_removes_folder_and_page_order_entry(brand_new_project: Path):
    page_writer.create_report_page(pbip_path=str(brand_new_project), page_name="Pagina1")
    page_writer.create_report_page(pbip_path=str(brand_new_project), page_name="Pagina2")

    result = page_writer.delete_report_page(pbip_path=str(brand_new_project), page_name="Pagina2")

    assert result == {"page_name": "Pagina2", "deleted": True}
    definition_dir = _definition_dir(brand_new_project)
    assert not (definition_dir / "pages" / "Pagina2").exists()
    pages_json = json.loads((definition_dir / "pages" / "pages.json").read_text(encoding="utf-8"))
    assert pages_json["pageOrder"] == ["Pagina1"]


def test_delete_report_page_moves_active_page_when_it_was_deleted(brand_new_project: Path):
    page_writer.create_report_page(pbip_path=str(brand_new_project), page_name="Pagina1")
    page_writer.create_report_page(pbip_path=str(brand_new_project), page_name="Pagina2")

    page_writer.delete_report_page(pbip_path=str(brand_new_project), page_name="Pagina1")

    pages_json = json.loads(
        (_definition_dir(brand_new_project) / "pages" / "pages.json").read_text(encoding="utf-8")
    )
    assert pages_json["activePageName"] == "Pagina2"
    assert pages_json["pageOrder"] == ["Pagina2"]


def test_delete_report_page_clears_active_page_when_it_was_the_last_one(brand_new_project: Path):
    page_writer.create_report_page(pbip_path=str(brand_new_project), page_name="Pagina1")

    page_writer.delete_report_page(pbip_path=str(brand_new_project), page_name="Pagina1")

    pages_json = json.loads(
        (_definition_dir(brand_new_project) / "pages" / "pages.json").read_text(encoding="utf-8")
    )
    assert pages_json["pageOrder"] == []
    assert "activePageName" not in pages_json


def test_delete_report_page_raises_when_page_does_not_exist(brand_new_project: Path):
    page_writer.create_report_page(pbip_path=str(brand_new_project), page_name="Pagina1")

    with pytest.raises(PageNotFoundError):
        page_writer.delete_report_page(pbip_path=str(brand_new_project), page_name="Fantasma")


# --- add_drillthrough_field / remove_drillthrough_field --------------------


@pytest.fixture
def fake_runtime() -> FakeTomRuntime:
    fake = FakeTomRuntime(database_name="Vendas")
    fake.add_table(
        TableInfo(
            name="Regiao",
            columns=(
                ColumnInfo(name="RegiaoId", data_type="Int64"),
                ColumnInfo(name="Nome", data_type="String"),
                ColumnInfo(name="Pais", data_type="String"),
            ),
        )
    )
    connection.set_active_runtime(fake)
    return fake


def test_add_drillthrough_field_writes_schema_valid_filter_and_binding(
    brand_new_project: Path, fake_runtime: FakeTomRuntime
):
    page_writer.create_report_page(pbip_path=str(brand_new_project), page_name="Detalhe")

    result = page_writer.add_drillthrough_field(
        pbip_path=str(brand_new_project), page_name="Detalhe", query_ref="Regiao.Nome"
    )

    assert result["page_name"] == "Detalhe"
    assert result["query_ref"] == "Regiao.Nome"

    page_json_path = _definition_dir(brand_new_project) / "pages" / "Detalhe" / "page.json"
    page = json.loads(page_json_path.read_text(encoding="utf-8"))
    validate_page_json(page)

    filters = page["filterConfig"]["filters"]
    assert len(filters) == 1
    assert filters[0]["name"] == result["filter_name"]
    assert filters[0]["type"] == "Categorical"
    assert filters[0]["howCreated"] == "Drillthrough"
    assert filters[0]["field"]["Column"] == {
        "Expression": {"SourceRef": {"Entity": "Regiao"}},
        "Property": "Nome",
    }

    binding = page["pageBinding"]
    assert binding["type"] == "Drillthrough"
    assert len(binding["parameters"]) == 1
    assert binding["parameters"][0]["boundFilter"] == result["filter_name"]
    assert binding["parameters"][0]["fieldExpr"] == filters[0]["field"]


def test_add_drillthrough_field_second_field_reuses_same_page_binding(
    brand_new_project: Path, fake_runtime: FakeTomRuntime
):
    page_writer.create_report_page(pbip_path=str(brand_new_project), page_name="Detalhe")

    page_writer.add_drillthrough_field(
        pbip_path=str(brand_new_project), page_name="Detalhe", query_ref="Regiao.Nome"
    )
    page_writer.add_drillthrough_field(
        pbip_path=str(brand_new_project), page_name="Detalhe", query_ref="Regiao.Pais"
    )

    page_json_path = _definition_dir(brand_new_project) / "pages" / "Detalhe" / "page.json"
    page = json.loads(page_json_path.read_text(encoding="utf-8"))
    validate_page_json(page)

    assert len(page["filterConfig"]["filters"]) == 2
    assert len(page["pageBinding"]["parameters"]) == 2
    assert page["pageBinding"]["name"] == "Pod"


def test_add_drillthrough_field_raises_for_duplicate_field(
    brand_new_project: Path, fake_runtime: FakeTomRuntime
):
    page_writer.create_report_page(pbip_path=str(brand_new_project), page_name="Detalhe")
    page_writer.add_drillthrough_field(
        pbip_path=str(brand_new_project), page_name="Detalhe", query_ref="Regiao.Nome"
    )

    with pytest.raises(DrillthroughFieldAlreadyExistsError):
        page_writer.add_drillthrough_field(
            pbip_path=str(brand_new_project), page_name="Detalhe", query_ref="Regiao.Nome"
        )


def test_add_drillthrough_field_raises_for_unknown_field(
    brand_new_project: Path, fake_runtime: FakeTomRuntime
):
    page_writer.create_report_page(pbip_path=str(brand_new_project), page_name="Detalhe")

    with pytest.raises(UnknownFieldError):
        page_writer.add_drillthrough_field(
            pbip_path=str(brand_new_project), page_name="Detalhe", query_ref="Regiao.Fantasma"
        )


def test_add_drillthrough_field_raises_when_page_does_not_exist(
    brand_new_project: Path, fake_runtime: FakeTomRuntime
):
    page_writer.create_report_page(pbip_path=str(brand_new_project), page_name="Pagina1")

    with pytest.raises(PageNotFoundError):
        page_writer.add_drillthrough_field(
            pbip_path=str(brand_new_project), page_name="Fantasma", query_ref="Regiao.Nome"
        )


def test_remove_drillthrough_field_clears_filter_config_and_binding_when_last_field(
    brand_new_project: Path, fake_runtime: FakeTomRuntime
):
    page_writer.create_report_page(pbip_path=str(brand_new_project), page_name="Detalhe")
    page_writer.add_drillthrough_field(
        pbip_path=str(brand_new_project), page_name="Detalhe", query_ref="Regiao.Nome"
    )

    result = page_writer.remove_drillthrough_field(
        pbip_path=str(brand_new_project), page_name="Detalhe", query_ref="Regiao.Nome"
    )

    assert result == {"page_name": "Detalhe", "query_ref": "Regiao.Nome", "deleted": True}
    page_json_path = _definition_dir(brand_new_project) / "pages" / "Detalhe" / "page.json"
    page = json.loads(page_json_path.read_text(encoding="utf-8"))
    validate_page_json(page)
    assert "filterConfig" not in page
    assert "pageBinding" not in page


def test_remove_drillthrough_field_keeps_other_fields_on_the_same_binding(
    brand_new_project: Path, fake_runtime: FakeTomRuntime
):
    page_writer.create_report_page(pbip_path=str(brand_new_project), page_name="Detalhe")
    page_writer.add_drillthrough_field(
        pbip_path=str(brand_new_project), page_name="Detalhe", query_ref="Regiao.Nome"
    )
    page_writer.add_drillthrough_field(
        pbip_path=str(brand_new_project), page_name="Detalhe", query_ref="Regiao.Pais"
    )

    page_writer.remove_drillthrough_field(
        pbip_path=str(brand_new_project), page_name="Detalhe", query_ref="Regiao.Nome"
    )

    page_json_path = _definition_dir(brand_new_project) / "pages" / "Detalhe" / "page.json"
    page = json.loads(page_json_path.read_text(encoding="utf-8"))
    validate_page_json(page)
    assert len(page["filterConfig"]["filters"]) == 1
    assert page["filterConfig"]["filters"][0]["field"]["Column"]["Property"] == "Pais"
    assert len(page["pageBinding"]["parameters"]) == 1


def test_remove_drillthrough_field_raises_when_field_was_never_added(
    brand_new_project: Path, fake_runtime: FakeTomRuntime
):
    page_writer.create_report_page(pbip_path=str(brand_new_project), page_name="Detalhe")

    with pytest.raises(DrillthroughFieldNotFoundError):
        page_writer.remove_drillthrough_field(
            pbip_path=str(brand_new_project), page_name="Detalhe", query_ref="Regiao.Nome"
        )


def test_remove_drillthrough_field_raises_when_page_does_not_exist(
    brand_new_project: Path, fake_runtime: FakeTomRuntime
):
    page_writer.create_report_page(pbip_path=str(brand_new_project), page_name="Pagina1")

    with pytest.raises(PageNotFoundError):
        page_writer.remove_drillthrough_field(
            pbip_path=str(brand_new_project), page_name="Fantasma", query_ref="Regiao.Nome"
        )


def _user_filter_on_regiao_nome() -> dict:
    return {
        "name": "Filter000000000000000000000000",
        "field": {"Column": {"Expression": {"SourceRef": {"Entity": "Regiao"}}, "Property": "Nome"}},
        "type": "Categorical",
        "howCreated": "User",
    }


def test_drillthrough_ignores_user_filter_on_same_field(
    brand_new_project: Path, fake_runtime: FakeTomRuntime
):
    """Regressão: `_filter_matches` casava só por campo, ignorando
    `howCreated` -- um filtro de usuário (filtros de página com valor)
    no mesmo campo bloqueava o add do drillthrough como "duplicado" e
    podia ser apagado pelo remove."""
    page_writer.create_report_page(pbip_path=str(brand_new_project), page_name="Detalhe")
    page_json_path = _definition_dir(brand_new_project) / "pages" / "Detalhe" / "page.json"
    page = json.loads(page_json_path.read_text(encoding="utf-8"))
    page["filterConfig"] = {"filters": [_user_filter_on_regiao_nome()]}
    page_json_path.write_text(json.dumps(page), encoding="utf-8")

    page_writer.add_drillthrough_field(
        pbip_path=str(brand_new_project), page_name="Detalhe", query_ref="Regiao.Nome"
    )
    page_writer.remove_drillthrough_field(
        pbip_path=str(brand_new_project), page_name="Detalhe", query_ref="Regiao.Nome"
    )

    page = json.loads(page_json_path.read_text(encoding="utf-8"))
    assert page["filterConfig"]["filters"] == [_user_filter_on_regiao_nome()]
    assert "pageBinding" not in page
