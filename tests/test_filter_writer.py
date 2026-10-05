"""Testes de visuals.filter_writer: filtros com valor em page.json e
report.json. Cada arquivo escrito é validado contra o schema oficial
(page -> filterConfiguration/1.1.0, report -> filterConfiguration/1.3.0,
ambos vendorizados em tests/schemas/)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from errors import (
    FilterAlreadyExistsError,
    FilterNotFoundError,
    InvalidFilterDefinitionError,
    PageNotFoundError,
    UnknownFieldError,
)
from modeling import connection
from modeling.metadata import ColumnInfo, TableInfo
from tests.fakes.fake_tom import FakeTomRuntime
from tests.schema_validation import validate_page_json, validate_report_json
from visuals import filter_writer, page_writer


@pytest.fixture
def project(tmp_path: Path) -> Path:
    root = tmp_path / "VendasProject"
    root.mkdir()
    (root / "Vendas.pbip").write_text("{}", encoding="utf-8")
    (root / "Vendas.Report").mkdir()
    page_writer.create_report_page(pbip_path=str(root), page_name="Pagina1")
    return root


@pytest.fixture(autouse=True)
def fake_runtime() -> FakeTomRuntime:
    fake = FakeTomRuntime(database_name="Vendas")
    fake.add_table(
        TableInfo(
            name="financials",
            columns=(
                ColumnInfo(name="Segment", data_type="String"),
                ColumnInfo(name="Year", data_type="Int64"),
            ),
        )
    )
    connection.set_active_runtime(fake)
    return fake


def _definition(root: Path) -> Path:
    return root / "Vendas.Report" / "definition"


def _page_json(root: Path, page: str = "Pagina1") -> dict:
    return json.loads((_definition(root) / "pages" / page / "page.json").read_text(encoding="utf-8"))


def _report_json(root: Path) -> dict:
    return json.loads((_definition(root) / "report.json").read_text(encoding="utf-8"))


# --- página -----------------------------------------------------------------


def test_add_page_filter_categorical_is_schema_valid(project: Path):
    result = filter_writer.add_page_filter(
        pbip_path=str(project), page_name="Pagina1", query_ref="financials.Segment",
        filter_type="categorical", values=["Government"],
    )

    page = _page_json(project)
    validate_page_json(page)
    [entry] = page["filterConfig"]["filters"]
    assert entry["name"] == result["filter_name"]
    assert entry["type"] == "Categorical"
    assert entry["howCreated"] == "User"
    assert result["scope"] == "Pagina1"


def test_add_page_filter_between_and_comparison_are_schema_valid(project: Path):
    filter_writer.add_page_filter(
        pbip_path=str(project), page_name="Pagina1", query_ref="financials.Year",
        filter_type="between", lower=2013, upper=2014,
    )
    filter_writer.add_page_filter(
        pbip_path=str(project), page_name="Pagina1", query_ref="financials.Segment",
        filter_type="comparison", operator="eq", value="Government",
    )

    page = _page_json(project)
    validate_page_json(page)
    assert len(page["filterConfig"]["filters"]) == 2


def test_add_page_filter_rejects_duplicate_on_same_field(project: Path):
    kwargs = dict(
        pbip_path=str(project), page_name="Pagina1", query_ref="financials.Segment",
        filter_type="categorical", values=["Government"],
    )
    filter_writer.add_page_filter(**kwargs)
    with pytest.raises(FilterAlreadyExistsError):
        filter_writer.add_page_filter(**kwargs)


def test_add_page_filter_rejects_unknown_field(project: Path):
    with pytest.raises(UnknownFieldError):
        filter_writer.add_page_filter(
            pbip_path=str(project), page_name="Pagina1", query_ref="financials.Fantasma",
            filter_type="categorical", values=["x"],
        )


def test_add_page_filter_rejects_unknown_filter_type(project: Path):
    with pytest.raises(InvalidFilterDefinitionError):
        filter_writer.add_page_filter(
            pbip_path=str(project), page_name="Pagina1", query_ref="financials.Segment",
            filter_type="topn", values=["x"],
        )


def test_add_page_filter_raises_when_page_missing(project: Path):
    with pytest.raises(PageNotFoundError):
        filter_writer.add_page_filter(
            pbip_path=str(project), page_name="Fantasma", query_ref="financials.Segment",
            filter_type="categorical", values=["x"],
        )


def test_remove_page_filter_clears_filter_config_when_last(project: Path):
    filter_writer.add_page_filter(
        pbip_path=str(project), page_name="Pagina1", query_ref="financials.Segment",
        filter_type="categorical", values=["Government"],
    )

    result = filter_writer.remove_page_filter(
        pbip_path=str(project), page_name="Pagina1", query_ref="financials.Segment"
    )

    assert result["deleted"] is True
    assert "filterConfig" not in _page_json(project)


def test_remove_page_filter_raises_when_absent(project: Path):
    with pytest.raises(FilterNotFoundError):
        filter_writer.remove_page_filter(
            pbip_path=str(project), page_name="Pagina1", query_ref="financials.Segment"
        )


def test_page_filter_and_drillthrough_coexist_on_same_field(project: Path):
    page_writer.add_drillthrough_field(
        pbip_path=str(project), page_name="Pagina1", query_ref="financials.Segment"
    )
    filter_writer.add_page_filter(
        pbip_path=str(project), page_name="Pagina1", query_ref="financials.Segment",
        filter_type="categorical", values=["Government"],
    )
    filter_writer.remove_page_filter(
        pbip_path=str(project), page_name="Pagina1", query_ref="financials.Segment"
    )

    page = _page_json(project)
    validate_page_json(page)
    [remaining] = page["filterConfig"]["filters"]
    assert remaining["howCreated"] == "Drillthrough"
    assert page["pageBinding"]["parameters"][0]["boundFilter"] == remaining["name"]


# --- relatório ----------------------------------------------------------------


def test_add_report_filter_is_schema_valid_and_preserves_other_keys(project: Path):
    report_path = _definition(project) / "report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    # themeCollection copiado do report.json real do projeto de teste
    # (PowerBITest01) -- o filtro de relatório não pode apagar isto.
    report["themeCollection"] = {
        "baseTheme": {
            "name": "Fluent2-CY26SU08",
            "reportVersionAtImport": {"visual": "2.12.0", "report": "3.4.0", "page": "2.3.1"},
            "type": "SharedResources",
        }
    }
    report_path.write_text(json.dumps(report), encoding="utf-8")

    result = filter_writer.add_report_filter(
        pbip_path=str(project), query_ref="financials.Year",
        filter_type="between", lower=2013, upper=2014,
    )

    report = _report_json(project)
    validate_report_json(report)
    assert report["themeCollection"]["baseTheme"]["name"] == "Fluent2-CY26SU08"
    [entry] = report["filterConfig"]["filters"]
    assert entry["name"] == result["filter_name"]
    assert result["scope"] == "report"


def test_add_report_filter_rejects_duplicate(project: Path):
    kwargs = dict(
        pbip_path=str(project), query_ref="financials.Year", filter_type="comparison",
        operator="gte", value=2014,
    )
    filter_writer.add_report_filter(**kwargs)
    with pytest.raises(FilterAlreadyExistsError):
        filter_writer.add_report_filter(**kwargs)


def test_remove_report_filter_clears_filter_config_when_last(project: Path):
    filter_writer.add_report_filter(
        pbip_path=str(project), query_ref="financials.Segment",
        filter_type="categorical", values=["Government"], exclude=True,
    )

    filter_writer.remove_report_filter(pbip_path=str(project), query_ref="financials.Segment")

    report = _report_json(project)
    assert "filterConfig" not in report
    validate_report_json(report)


def test_remove_report_filter_raises_when_absent(project: Path):
    with pytest.raises(FilterNotFoundError):
        filter_writer.remove_report_filter(pbip_path=str(project), query_ref="financials.Segment")


# --- visual (visual.json -> filterConfig na raiz) -------------------------------
#
# Doc oficial filters.md: relatório, página e VISUAL usam o mesmo array
# `filterConfig.filters`; schema oficial visualContainer/2.7.0 tem
# `filterConfig` na raiz ("Filters that apply to all this visual") ->
# filterConfiguration/1.3.0. Uso típico: limitar um gráfico a alguns itens
# de um calculation group (ex: só "Atual" e "PY").


def _chart(root: Path) -> str:
    from visuals import visual_writer

    return visual_writer.add_visual(
        pbip_path=str(root), page_name="Pagina1", visual_type="clusteredColumnChart",
        x=0, y=0, width=300, height=200, fields={"Category": ["financials.Segment"], "Y": ["financials.Year"]},
    )["visual_name"]


def _visual_json(root: Path, name: str) -> dict:
    from tests.schema_validation import validate_visual_json

    data = json.loads((_definition(root) / "pages" / "Pagina1" / "visuals" / name / "visual.json").read_text(encoding="utf-8"))
    validate_visual_json(data)
    return data


def test_add_visual_filter_is_schema_valid_and_only_on_that_visual(project: Path):
    name = _chart(project)

    result = filter_writer.add_visual_filter(
        pbip_path=str(project), page_name="Pagina1", visual_name=name,
        query_ref="financials.Segment", filter_type="categorical", values=["Government", "Enterprise"],
    )

    visual = _visual_json(project, name)
    [entry] = visual["filterConfig"]["filters"]
    assert entry["name"] == result["filter_name"]
    assert entry["type"] == "Categorical"
    assert result["scope"] == f"Pagina1/{name}"
    assert "filterConfig" not in _page_json(project)


def test_visual_filter_duplicate_and_remove(project: Path):
    name = _chart(project)
    filter_writer.add_visual_filter(
        pbip_path=str(project), page_name="Pagina1", visual_name=name,
        query_ref="financials.Segment", filter_type="categorical", values=["Government"],
    )
    with pytest.raises(FilterAlreadyExistsError):
        filter_writer.add_visual_filter(
            pbip_path=str(project), page_name="Pagina1", visual_name=name,
            query_ref="financials.Segment", filter_type="categorical", values=["Enterprise"],
        )

    filter_writer.remove_visual_filter(
        pbip_path=str(project), page_name="Pagina1", visual_name=name, query_ref="financials.Segment",
    )
    assert "filterConfig" not in _visual_json(project, name)
    with pytest.raises(FilterNotFoundError):
        filter_writer.remove_visual_filter(
            pbip_path=str(project), page_name="Pagina1", visual_name=name, query_ref="financials.Segment",
        )


def test_visual_filter_on_missing_visual(project: Path):
    from errors import VisualNotFoundError

    with pytest.raises(VisualNotFoundError):
        filter_writer.add_visual_filter(
            pbip_path=str(project), page_name="Pagina1", visual_name="nao_existe",
            query_ref="financials.Segment", filter_type="categorical", values=["Government"],
        )
