"""Testes de bookmark_writer.create_reset_bookmark -- bookmark "voltar ao
padrão" (Dados ligado) que captura o estado SALVO da página.

Formato copiado de um bookmark criado pelo próprio Power BI Desktop
(técnica de comparação com o Desktop, réplica página 2, 2026-09-30) e da
doc oficial bookmark.md ("Reset filters/slicers": Data On, Current page
Off; seleção de slicer em `singleVisual.objects.merge.general[].
properties.filter.filter`; filtros em `filters.byExpr`):
- slicer com seleção salva -> `objects.merge.general` com o mesmo filtro
  de `visual.objects.general` + `objects.merge.selection`;
- slicer sem seleção -> `objects: {}`;
- filtro de visual (filterConfig) -> `filters.byExpr[]` com `expression`
  (= `field`) e `howCreated: 1`;
- gráfico com drill -> `activeProjections.Category` = níveis ativos;
- visual escondido -> `display.mode: hidden`.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from errors import BookmarkAlreadyExistsError, PageNotFoundError
from modeling import connection
from modeling.metadata import ColumnInfo, TableInfo
from tests.fakes.fake_tom import FakeTomRuntime
from tests.schema_validation import validate_bookmark_json
from visuals import bookmark_writer, filter_writer, visual_writer


@pytest.fixture
def project_dir(tmp_path: Path) -> Path:
    root = tmp_path / "VendasProject"
    root.mkdir()
    (root / "Vendas.pbip").write_text("{}", encoding="utf-8")
    report_dir = root / "Vendas.Report"
    pages_dir = report_dir / "definition" / "pages"
    page_dir = pages_dir / "Pagina1"
    page_dir.mkdir(parents=True)
    (page_dir / "page.json").write_text("{}", encoding="utf-8")
    (pages_dir / "pages.json").write_text("{}", encoding="utf-8")
    (report_dir / "definition" / "version.json").write_text("{}", encoding="utf-8")
    (report_dir / "definition" / "report.json").write_text("{}", encoding="utf-8")
    return root


@pytest.fixture(autouse=True)
def fake_runtime() -> FakeTomRuntime:
    fake = FakeTomRuntime(database_name="Vendas")
    fake.add_table(TableInfo(name="Vendas", columns=(
        ColumnInfo(name="Valor", data_type="Double"),
        ColumnInfo(name="Segmento", data_type="String"),
        ColumnInfo(name="Produto", data_type="String"),
        ColumnInfo(name="Moeda", data_type="String"),
    )))
    fake.create_measure("Vendas", "Total Vendas", "SUM(Vendas[Valor])", "#,##0.00")
    connection.set_active_runtime(fake)
    return fake


def _add(project_dir: Path, visual_type: str, fields: dict) -> str:
    return visual_writer.add_visual(
        pbip_path=str(project_dir), page_name="Pagina1", visual_type=visual_type,
        x=0, y=0, width=200, height=100, fields=fields,
    )["visual_name"]


def _visual_path(project_dir: Path, name: str) -> Path:
    return project_dir / "Vendas.Report" / "definition" / "pages" / "Pagina1" / "visuals" / name / "visual.json"


_USD_FILTER = {"filter": {
    "Version": 2,
    "From": [{"Name": "v", "Entity": "Vendas", "Type": 0}],
    "Where": [{"Condition": {"In": {
        "Expressions": [{"Column": {"Expression": {"SourceRef": {"Source": "v"}}, "Property": "Moeda"}}],
        "Values": [[{"Literal": {"Value": "'USD'"}}]],
    }}}],
}}


def _save_slicer_selection(project_dir: Path, name: str) -> None:
    """Simula o Desktop salvando a seleção atual do slicer."""
    path = _visual_path(project_dir, name)
    data = json.loads(path.read_text(encoding="utf-8"))
    data["visual"].setdefault("objects", {})["general"] = [{"properties": {"filter": _USD_FILTER}}]
    data["visual"]["objects"]["selection"] = [{"properties": {
        "singleSelect": {"expr": {"Literal": {"Value": "true"}}},
        "strictSingleSelect": {"expr": {"Literal": {"Value": "true"}}},
    }}]
    path.write_text(json.dumps(data), encoding="utf-8")


def _read_bookmark(project_dir: Path, name: str) -> dict:
    path = project_dir / "Vendas.Report" / "definition" / "bookmarks" / f"{name}.bookmark.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    validate_bookmark_json(data)
    return data


def test_reset_bookmark_captures_saved_page_state(project_dir: Path):
    currency = _add(project_dir, "advancedSlicerVisual", {"Values": ["Vendas.Moeda"]})
    _save_slicer_selection(project_dir, currency)
    empty_slicer = _add(project_dir, "advancedSlicerVisual", {"Values": ["Vendas.Segmento"]})
    bars = _add(project_dir, "clusteredBarChart", {
        "Category": ["Vendas.Segmento", "Vendas.Produto"], "Y": ["Vendas.Total Vendas"],
    })
    filter_writer.add_visual_filter(
        pbip_path=str(project_dir), page_name="Pagina1", visual_name=bars,
        query_ref="Vendas.Segmento", filter_type="categorical", values=["Government"],
    )
    card = _add(project_dir, "cardVisual", {"Data": ["Vendas.Total Vendas"]})
    visual_writer.set_visual_hidden(pbip_path=str(project_dir), page_name="Pagina1", visual_name=card, hidden=True)

    result = bookmark_writer.create_reset_bookmark(
        pbip_path=str(project_dir), bookmark_name="Padrao", page_name="Pagina1", display_name="Padrão",
    )

    bookmark = _read_bookmark(project_dir, "Padrao")
    assert bookmark["displayName"] == "Padrão"
    # Dados ligado (sem suppressData), não troca de página
    assert bookmark["options"] == {"suppressActiveSection": True}
    state = bookmark["explorationState"]
    assert state["activeSection"] == "Pagina1"
    containers = state["sections"]["Pagina1"]["visualContainers"]
    assert set(containers) == {currency, empty_slicer, bars, card}

    currency_state = containers[currency]["singleVisual"]
    assert currency_state["visualType"] == "advancedSlicerVisual"
    assert currency_state["objects"]["merge"]["general"] == [{"properties": {"filter": _USD_FILTER}}]
    assert currency_state["objects"]["merge"]["selection"][0]["properties"]["strictSingleSelect"] == {
        "expr": {"Literal": {"Value": "true"}}
    }

    assert containers[empty_slicer]["singleVisual"] == {"visualType": "advancedSlicerVisual", "objects": {}}

    bars_state = containers[bars]
    assert bars_state["singleVisual"]["activeProjections"] == {"Category": [
        {"Column": {"Expression": {"SourceRef": {"Entity": "Vendas"}}, "Property": "Segmento"}},
    ]}
    (by_expr,) = bars_state["filters"]["byExpr"]
    assert by_expr["howCreated"] == 1
    assert by_expr["type"] == "Categorical"
    assert by_expr["expression"] == {"Column": {"Expression": {"SourceRef": {"Entity": "Vendas"}}, "Property": "Segmento"}}
    assert "filter" in by_expr and by_expr["name"]

    assert containers[card]["singleVisual"]["display"] == {"mode": "hidden"}
    assert result["visuals_captured"] == 4
    assert result["slicers_with_selection"] == [currency]


def test_reset_bookmark_errors(project_dir: Path):
    _add(project_dir, "advancedSlicerVisual", {"Values": ["Vendas.Moeda"]})
    bookmark_writer.create_reset_bookmark(pbip_path=str(project_dir), bookmark_name="Padrao", page_name="Pagina1")

    with pytest.raises(BookmarkAlreadyExistsError):
        bookmark_writer.create_reset_bookmark(pbip_path=str(project_dir), bookmark_name="Padrao", page_name="Pagina1")
    with pytest.raises(PageNotFoundError):
        bookmark_writer.create_reset_bookmark(pbip_path=str(project_dir), bookmark_name="Outro", page_name="NaoExiste")
