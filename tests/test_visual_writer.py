"""Testes de visuals.visual_writer: montagem e escrita de visual.json.

build_visual_json é testado isoladamente (função pura). add_visual é
testado de ponta a ponta: escreve em disco (tmp_path) e o resultado é
validado contra o schema oficial visualContainer/2.7.0 (vendorizado em
tests/schemas/, ver tests/schema_validation.py) -- não um formato
inventado por este projeto.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from errors import (
    InvalidResourceNameError,
    InvalidVisualRoleError,
    PageNotFoundError,
    UnknownFieldError,
    VisualNotFoundError,
)
from modeling import connection
from modeling.metadata import ColumnInfo, TableInfo
from tests.fakes.fake_tom import FakeTomRuntime
from tests.schema_validation import validate_visual_json
from visuals import visual_writer
from visuals.validator import ResolvedField


# --- build_visual_json (função pura) ---------------------------------------


def test_build_visual_json_card_is_schema_valid():
    resolved = {
        "Values": [
            ResolvedField(
                entity="Vendas",
                property="Total Vendas",
                kind="measure",
                query_ref="Vendas.Total Vendas",
                native_query_ref="Total Vendas",
            )
        ]
    }

    instance = visual_writer.build_visual_json(
        visual_name="abc123", visual_type="card", x=10, y=20, width=200, height=100, resolved_fields=resolved
    )

    validate_visual_json(instance)
    assert instance["name"] == "abc123"
    assert instance["position"] == {"x": 10, "y": 20, "width": 200, "height": 100, "z": 0, "tabOrder": 0}
    assert instance["visual"]["visualType"] == "card"


def test_build_visual_json_projection_shape_for_column_and_measure():
    resolved = {
        "Category": [
            ResolvedField(
                entity="Regiao", property="Nome", kind="column",
                query_ref="Regiao.Nome", native_query_ref="Nome",
            )
        ],
        "Y": [
            ResolvedField(
                entity="Vendas", property="Total Vendas", kind="measure",
                query_ref="Vendas.Total Vendas", native_query_ref="Total Vendas",
            )
        ],
    }

    instance = visual_writer.build_visual_json(
        visual_name="chart1", visual_type="clusteredColumnChart",
        x=0, y=0, width=400, height=300, resolved_fields=resolved,
    )

    validate_visual_json(instance)
    query_state = instance["visual"]["query"]["queryState"]

    category_projection = query_state["Category"]["projections"][0]
    assert category_projection["queryRef"] == "Regiao.Nome"
    assert category_projection["nativeQueryRef"] == "Nome"
    assert category_projection["field"]["Column"] == {
        "Expression": {"SourceRef": {"Entity": "Regiao"}},
        "Property": "Nome",
    }

    y_projection = query_state["Y"]["projections"][0]
    assert y_projection["field"]["Measure"] == {
        "Expression": {"SourceRef": {"Entity": "Vendas"}},
        "Property": "Total Vendas",
    }


def test_build_visual_json_multiple_projections_in_one_role():
    resolved = {
        "Values": [
            ResolvedField("Vendas", "Total Vendas", "measure", "Vendas.Total Vendas", "Total Vendas"),
            ResolvedField("Regiao", "Nome", "column", "Regiao.Nome", "Nome"),
        ]
    }

    instance = visual_writer.build_visual_json(
        visual_name="t1", visual_type="tableEx", x=0, y=0, width=1, height=1, resolved_fields=resolved
    )

    validate_visual_json(instance)
    projections = instance["visual"]["query"]["queryState"]["Values"]["projections"]
    assert len(projections) == 2


# --- build_textbox_json (função pura) --------------------------------------


def test_build_textbox_json_single_line_is_schema_valid():
    instance = visual_writer.build_textbox_json(
        visual_name="txt1", x=20, y=20, width=520, height=60, text="Dashboard de Vendas"
    )

    validate_visual_json(instance)
    assert instance["visual"]["visualType"] == "textbox"
    paragraphs = instance["visual"]["objects"]["general"][0]["properties"]["paragraphs"]
    assert len(paragraphs) == 1
    assert paragraphs[0]["textRuns"][0]["value"] == "Dashboard de Vendas"


def test_build_textbox_json_multiple_lines_become_multiple_paragraphs():
    instance = visual_writer.build_textbox_json(
        visual_name="txt2",
        x=0,
        y=0,
        width=1,
        height=1,
        text="Primeira observação.\nSegunda observação.\nTerceira observação.",
    )

    validate_visual_json(instance)
    paragraphs = instance["visual"]["objects"]["general"][0]["properties"]["paragraphs"]
    assert [p["textRuns"][0]["value"] for p in paragraphs] == [
        "Primeira observação.",
        "Segunda observação.",
        "Terceira observação.",
    ]


def test_build_textbox_json_has_no_query_unlike_data_bound_visuals():
    """textbox não usa query/queryState -- diferente de todos os outros
    tipos de visual deste catálogo."""
    instance = visual_writer.build_textbox_json(
        visual_name="txt3", x=0, y=0, width=1, height=1, text="x"
    )
    assert "query" not in instance["visual"]


# --- add_visual (integração, escreve em disco) -----------------------------


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


@pytest.fixture
def fake_runtime() -> FakeTomRuntime:
    fake = FakeTomRuntime(database_name="Vendas")
    fake.add_table(
        TableInfo(
            name="Vendas",
            columns=(ColumnInfo(name="Valor", data_type="Double"), ColumnInfo(name="RegiaoId", data_type="Int64")),
        )
    )
    fake.add_table(
        TableInfo(
            name="Regiao",
            columns=(ColumnInfo(name="RegiaoId", data_type="Int64"), ColumnInfo(name="Nome", data_type="String")),
        )
    )
    fake.create_measure("Vendas", "Total Vendas", "SUM(Vendas[Valor])", "#,##0.00")
    connection.set_active_runtime(fake)
    return fake


def _visuals_dir(project_dir: Path, page_name: str = "Pagina1") -> Path:
    return project_dir / "Vendas.Report" / "definition" / "pages" / page_name / "visuals"


def test_add_visual_writes_schema_valid_card(project_dir: Path, fake_runtime: FakeTomRuntime):
    result = visual_writer.add_visual(
        pbip_path=str(project_dir),
        page_name="Pagina1",
        visual_type="card",
        x=0, y=0, width=200, height=100,
        fields={"Values": ["Vendas.Total Vendas"]},
    )

    visual_dirs = list(_visuals_dir(project_dir).iterdir())
    assert len(visual_dirs) == 1
    visual_json_path = visual_dirs[0] / "visual.json"
    assert visual_json_path.is_file()

    data = json.loads(visual_json_path.read_text(encoding="utf-8"))
    validate_visual_json(data)
    assert data["visual"]["visualType"] == "card"
    assert result["visual_name"] == visual_dirs[0].name
    assert result["visual_type"] == "card"


def test_add_visual_generates_unique_names_for_multiple_visuals(
    project_dir: Path, fake_runtime: FakeTomRuntime
):
    r1 = visual_writer.add_visual(
        pbip_path=str(project_dir), page_name="Pagina1", visual_type="card",
        x=0, y=0, width=1, height=1, fields={"Values": ["Vendas.Total Vendas"]},
    )
    r2 = visual_writer.add_visual(
        pbip_path=str(project_dir), page_name="Pagina1", visual_type="card",
        x=0, y=0, width=1, height=1, fields={"Values": ["Vendas.Total Vendas"]},
    )

    assert r1["visual_name"] != r2["visual_name"]
    assert len(list(_visuals_dir(project_dir).iterdir())) == 2


def test_add_visual_raises_and_writes_nothing_for_unknown_field(
    project_dir: Path, fake_runtime: FakeTomRuntime
):
    with pytest.raises(UnknownFieldError):
        visual_writer.add_visual(
            pbip_path=str(project_dir), page_name="Pagina1", visual_type="card",
            x=0, y=0, width=1, height=1, fields={"Values": ["Vendas.NaoExiste"]},
        )

    visuals_dir = _visuals_dir(project_dir)
    assert not visuals_dir.exists() or list(visuals_dir.iterdir()) == []


def test_add_visual_raises_and_writes_nothing_for_invalid_role(
    project_dir: Path, fake_runtime: FakeTomRuntime
):
    with pytest.raises(InvalidVisualRoleError):
        visual_writer.add_visual(
            pbip_path=str(project_dir), page_name="Pagina1", visual_type="slicer",
            x=0, y=0, width=1, height=1, fields={"Values": ["Vendas.Total Vendas"]},
        )

    visuals_dir = _visuals_dir(project_dir)
    assert not visuals_dir.exists() or list(visuals_dir.iterdir()) == []


def test_add_visual_raises_when_page_does_not_exist(project_dir: Path, fake_runtime: FakeTomRuntime):
    with pytest.raises(PageNotFoundError):
        visual_writer.add_visual(
            pbip_path=str(project_dir), page_name="PaginaFantasma", visual_type="card",
            x=0, y=0, width=1, height=1, fields={"Values": ["Vendas.Total Vendas"]},
        )


# --- add_visual com pivotTable, waterfallChart, scatterChart ---------------


def test_add_visual_writes_schema_valid_pivot_table(project_dir: Path, fake_runtime: FakeTomRuntime):
    result = visual_writer.add_visual(
        pbip_path=str(project_dir), page_name="Pagina1", visual_type="pivotTable",
        x=0, y=0, width=400, height=300,
        fields={"Rows": ["Regiao.Nome"], "Values": ["Vendas.Total Vendas"]},
    )

    visual_dirs = list(_visuals_dir(project_dir).iterdir())
    data = json.loads((visual_dirs[0] / "visual.json").read_text(encoding="utf-8"))
    validate_visual_json(data)
    assert data["visual"]["visualType"] == "pivotTable"
    assert result["fields"]["Rows"] == ["Regiao.Nome"]
    assert result["fields"]["Values"] == ["Vendas.Total Vendas"]


def test_add_visual_writes_schema_valid_waterfall_chart(project_dir: Path, fake_runtime: FakeTomRuntime):
    result = visual_writer.add_visual(
        pbip_path=str(project_dir), page_name="Pagina1", visual_type="waterfallChart",
        x=0, y=0, width=400, height=300,
        fields={"Category": ["Regiao.Nome"], "Y": ["Vendas.Total Vendas"]},
    )

    visual_dirs = list(_visuals_dir(project_dir).iterdir())
    data = json.loads((visual_dirs[0] / "visual.json").read_text(encoding="utf-8"))
    validate_visual_json(data)
    assert data["visual"]["visualType"] == "waterfallChart"
    assert result["fields"]["Category"] == ["Regiao.Nome"]


def test_add_visual_writes_schema_valid_scatter_chart(project_dir: Path, fake_runtime: FakeTomRuntime):
    result = visual_writer.add_visual(
        pbip_path=str(project_dir), page_name="Pagina1", visual_type="scatterChart",
        x=0, y=0, width=400, height=300,
        fields={
            "Category": ["Regiao.Nome"],
            "X": ["Vendas.Total Vendas"],
            "Y": ["Vendas.Total Vendas"],
        },
    )

    visual_dirs = list(_visuals_dir(project_dir).iterdir())
    data = json.loads((visual_dirs[0] / "visual.json").read_text(encoding="utf-8"))
    validate_visual_json(data)
    assert data["visual"]["visualType"] == "scatterChart"
    assert result["fields"]["X"] == ["Vendas.Total Vendas"]
    assert result["fields"]["Y"] == ["Vendas.Total Vendas"]


def test_add_visual_scatter_chart_raises_when_required_role_missing(
    project_dir: Path, fake_runtime: FakeTomRuntime
):
    with pytest.raises(InvalidVisualRoleError):
        visual_writer.add_visual(
            pbip_path=str(project_dir), page_name="Pagina1", visual_type="scatterChart",
            x=0, y=0, width=1, height=1,
            fields={"X": ["Vendas.Total Vendas"], "Y": ["Vendas.Total Vendas"]},  # falta Category
        )
    assert not _visuals_dir(project_dir).exists() or list(_visuals_dir(project_dir).iterdir()) == []


# --- add_visual com a 2a rodada de tipos novos ------------------------------


@pytest.mark.parametrize(
    "visual_type,fields",
    [
        ("columnChart", {"Category": ["Regiao.Nome"], "Y": ["Vendas.Total Vendas"]}),
        ("barChart", {"Category": ["Regiao.Nome"], "Y": ["Vendas.Total Vendas"]}),
        ("areaChart", {"Category": ["Regiao.Nome"], "Y": ["Vendas.Total Vendas"]}),
        ("stackedAreaChart", {"Category": ["Regiao.Nome"], "Y": ["Vendas.Total Vendas"]}),
        (
            "hundredPercentStackedColumnChart",
            {"Category": ["Regiao.Nome"], "Y": ["Vendas.Total Vendas"]},
        ),
        (
            "hundredPercentStackedBarChart",
            {"Category": ["Regiao.Nome"], "Y": ["Vendas.Total Vendas"]},
        ),
        ("pieChart", {"Category": ["Regiao.Nome"], "Y": ["Vendas.Total Vendas"]}),
        (
            "treemap",
            {"Group": ["Regiao.Nome"], "Values": ["Vendas.Total Vendas"]},
        ),
        ("funnel", {"Category": ["Regiao.Nome"], "Y": ["Vendas.Total Vendas"]}),
        ("gauge", {"Y": ["Vendas.Total Vendas"]}),
        ("kpi", {"Indicator": ["Vendas.Total Vendas"], "TrendLine": ["Vendas.Valor"]}),
        ("cardVisual", {"Data": ["Vendas.Total Vendas"]}),
        ("azureMap", {"Category": ["Regiao.Nome"]}),
    ],
)
def test_add_visual_writes_schema_valid_second_round_types(
    project_dir: Path, fake_runtime: FakeTomRuntime, visual_type: str, fields: dict
):
    visual_writer.add_visual(
        pbip_path=str(project_dir), page_name="Pagina1", visual_type=visual_type,
        x=0, y=0, width=400, height=300, fields=fields,
    )

    visual_dirs = list(_visuals_dir(project_dir).iterdir())
    assert len(visual_dirs) == 1
    data = json.loads((visual_dirs[0] / "visual.json").read_text(encoding="utf-8"))
    validate_visual_json(data)
    assert data["visual"]["visualType"] == visual_type


def test_add_visual_gauge_raises_when_required_y_missing(
    project_dir: Path, fake_runtime: FakeTomRuntime
):
    with pytest.raises(InvalidVisualRoleError):
        visual_writer.add_visual(
            pbip_path=str(project_dir), page_name="Pagina1", visual_type="gauge",
            x=0, y=0, width=1, height=1,
            fields={"MinValue": ["Vendas.Total Vendas"]},  # falta Y
        )
    assert not _visuals_dir(project_dir).exists() or list(_visuals_dir(project_dir).iterdir()) == []


def test_add_visual_kpi_raises_when_trendline_missing(
    project_dir: Path, fake_runtime: FakeTomRuntime
):
    """Achado ao vivo: sem TrendLine, o KPI nativo renderiza em branco
    -- por isso o role é obrigatório, não opcional."""
    with pytest.raises(InvalidVisualRoleError):
        visual_writer.add_visual(
            pbip_path=str(project_dir), page_name="Pagina1", visual_type="kpi",
            x=0, y=0, width=1, height=1,
            fields={"Indicator": ["Vendas.Total Vendas"]},  # falta TrendLine
        )
    assert not _visuals_dir(project_dir).exists() or list(_visuals_dir(project_dir).iterdir()) == []


# --- add_visual com textbox -------------------------------------------------


def test_add_visual_writes_schema_valid_textbox(project_dir: Path, fake_runtime: FakeTomRuntime):
    result = visual_writer.add_visual(
        pbip_path=str(project_dir), page_name="Pagina1", visual_type="textbox",
        x=0, y=0, width=400, height=60, text="Observações do dashboard",
    )

    visual_dirs = list(_visuals_dir(project_dir).iterdir())
    assert len(visual_dirs) == 1
    data = json.loads((visual_dirs[0] / "visual.json").read_text(encoding="utf-8"))
    validate_visual_json(data)
    assert data["visual"]["visualType"] == "textbox"
    assert result["visual_type"] == "textbox"
    assert result["text"] == "Observações do dashboard"


def test_add_visual_textbox_does_not_require_a_model_connection(project_dir: Path):
    """textbox não referencia nenhum campo -- não deveria precisar
    consultar o modelo (nem via XMLA, nem via TMDL) para ser escrito."""
    connection.clear_active_runtime()  # garante que não há conexão ativa

    result = visual_writer.add_visual(
        pbip_path=str(project_dir), page_name="Pagina1", visual_type="textbox",
        x=0, y=0, width=400, height=60, text="Sem conexão nenhuma",
    )

    assert result["visual_type"] == "textbox"


def test_add_visual_textbox_raises_when_text_is_missing(
    project_dir: Path, fake_runtime: FakeTomRuntime
):
    with pytest.raises(InvalidVisualRoleError):
        visual_writer.add_visual(
            pbip_path=str(project_dir), page_name="Pagina1", visual_type="textbox",
            x=0, y=0, width=1, height=1, fields={}, text=None,
        )
    assert not _visuals_dir(project_dir).exists() or list(_visuals_dir(project_dir).iterdir()) == []


def test_add_visual_textbox_raises_when_fields_also_given(
    project_dir: Path, fake_runtime: FakeTomRuntime
):
    with pytest.raises(InvalidVisualRoleError):
        visual_writer.add_visual(
            pbip_path=str(project_dir), page_name="Pagina1", visual_type="textbox",
            x=0, y=0, width=1, height=1, fields={"Values": ["Vendas.Total Vendas"]}, text="oi",
        )
    assert not _visuals_dir(project_dir).exists() or list(_visuals_dir(project_dir).iterdir()) == []


def test_add_visual_data_bound_raises_when_text_given_instead_of_fields(
    project_dir: Path, fake_runtime: FakeTomRuntime
):
    with pytest.raises(InvalidVisualRoleError):
        visual_writer.add_visual(
            pbip_path=str(project_dir), page_name="Pagina1", visual_type="card",
            x=0, y=0, width=1, height=1, fields={}, text="não sou textbox",
        )
    assert not _visuals_dir(project_dir).exists() or list(_visuals_dir(project_dir).iterdir()) == []


# --- list_visuals -------------------------------------------------------


def test_list_visuals_empty_page_returns_empty_list(project_dir: Path, fake_runtime: FakeTomRuntime):
    assert visual_writer.list_visuals(pbip_path=str(project_dir), page_name="Pagina1") == []


def test_list_visuals_describes_position_and_fields(project_dir: Path, fake_runtime: FakeTomRuntime):
    created = visual_writer.add_visual(
        pbip_path=str(project_dir), page_name="Pagina1", visual_type="card",
        x=10, y=20, width=200, height=100, fields={"Values": ["Vendas.Total Vendas"]},
    )

    listed = visual_writer.list_visuals(pbip_path=str(project_dir), page_name="Pagina1")

    assert len(listed) == 1
    entry = listed[0]
    assert entry["visual_name"] == created["visual_name"]
    assert entry["visual_type"] == "card"
    assert entry["page_name"] == "Pagina1"
    assert entry["position"] == {"x": 10, "y": 20, "width": 200, "height": 100}
    assert entry["fields"] == {"Values": ["Vendas.Total Vendas"]}
    assert "text" not in entry


def test_list_visuals_describes_textbox_text(project_dir: Path, fake_runtime: FakeTomRuntime):
    visual_writer.add_visual(
        pbip_path=str(project_dir), page_name="Pagina1", visual_type="textbox",
        x=0, y=0, width=100, height=50, text="Título\nSubtítulo",
    )

    listed = visual_writer.list_visuals(pbip_path=str(project_dir), page_name="Pagina1")

    assert listed[0]["text"] == "Título\nSubtítulo"
    assert "fields" not in listed[0]


def test_list_visuals_describes_action_button_without_fields_or_text(
    project_dir: Path, fake_runtime: FakeTomRuntime
):
    visual_writer.add_navigation_button(
        pbip_path=str(project_dir), page_name="Pagina1",
        x=0, y=0, width=100, height=40, target_type="page", target="Pagina1",
    )

    listed = visual_writer.list_visuals(pbip_path=str(project_dir), page_name="Pagina1")

    assert listed[0]["visual_type"] == "actionButton"
    assert "fields" not in listed[0]
    assert "text" not in listed[0]


def test_list_visuals_orders_multiple_visuals_and_raises_for_missing_page(
    project_dir: Path, fake_runtime: FakeTomRuntime
):
    visual_writer.add_visual(
        pbip_path=str(project_dir), page_name="Pagina1", visual_type="card",
        x=0, y=0, width=1, height=1, fields={"Values": ["Vendas.Total Vendas"]},
    )
    visual_writer.add_visual(
        pbip_path=str(project_dir), page_name="Pagina1", visual_type="card",
        x=1, y=1, width=1, height=1, fields={"Values": ["Vendas.Total Vendas"]},
    )

    listed = visual_writer.list_visuals(pbip_path=str(project_dir), page_name="Pagina1")
    assert len(listed) == 2

    with pytest.raises(PageNotFoundError):
        visual_writer.list_visuals(pbip_path=str(project_dir), page_name="PaginaFantasma")


# --- delete_visual -----------------------------------------------------


def test_delete_visual_removes_the_folder(project_dir: Path, fake_runtime: FakeTomRuntime):
    result = visual_writer.add_visual(
        pbip_path=str(project_dir), page_name="Pagina1", visual_type="card",
        x=0, y=0, width=1, height=1, fields={"Values": ["Vendas.Total Vendas"]},
    )
    visual_name = result["visual_name"]

    delete_result = visual_writer.delete_visual(
        pbip_path=str(project_dir), page_name="Pagina1", visual_name=visual_name
    )

    assert delete_result == {"visual_name": visual_name, "page_name": "Pagina1", "deleted": True}
    assert list(_visuals_dir(project_dir).iterdir()) == []


def test_delete_visual_raises_when_visual_does_not_exist(
    project_dir: Path, fake_runtime: FakeTomRuntime
):
    with pytest.raises(VisualNotFoundError):
        visual_writer.delete_visual(
            pbip_path=str(project_dir), page_name="Pagina1", visual_name="fantasma"
        )


def test_delete_visual_raises_for_path_traversal_visual_name(
    project_dir: Path, fake_runtime: FakeTomRuntime, tmp_path: Path
):
    """Achado de segurança: visual_name chega como parâmetro comum de
    tool, sem passar pelo uuid.uuid4() que add_visual usa -- sem
    validar, "../../../../alvo" escaparia de visuals/ (path traversal)
    antes de shutil.rmtree apagar o alvo errado."""
    outside_target = tmp_path / "alvo_fora_do_projeto"
    outside_target.mkdir()
    traversal_name = "../" * 10 + outside_target.name

    with pytest.raises(InvalidResourceNameError):
        visual_writer.delete_visual(
            pbip_path=str(project_dir), page_name="Pagina1", visual_name=traversal_name,
        )
    assert outside_target.is_dir()  # nunca deveria ter sido tocado


def test_delete_visual_raises_when_page_does_not_exist(
    project_dir: Path, fake_runtime: FakeTomRuntime
):
    with pytest.raises(PageNotFoundError):
        visual_writer.delete_visual(
            pbip_path=str(project_dir), page_name="PaginaFantasma", visual_name="qualquer"
        )


# --- update_visual -------------------------------------------------------


def test_update_visual_repositions_without_touching_fields(
    project_dir: Path, fake_runtime: FakeTomRuntime
):
    added = visual_writer.add_visual(
        pbip_path=str(project_dir), page_name="Pagina1", visual_type="card",
        x=0, y=0, width=100, height=50, fields={"Values": ["Vendas.Total Vendas"]},
    )
    visual_name = added["visual_name"]

    result = visual_writer.update_visual(
        pbip_path=str(project_dir), page_name="Pagina1", visual_name=visual_name,
        x=200, y=300, width=150, height=75,
    )

    assert result["visual_name"] == visual_name
    data = json.loads(
        (_visuals_dir(project_dir) / visual_name / "visual.json").read_text(encoding="utf-8")
    )
    validate_visual_json(data)
    assert data["position"] == {
        "x": 200, "y": 300, "width": 150, "height": 75, "z": 1000, "tabOrder": 1000,
    }
    # query original preservado -- não passamos `fields`
    assert data["visual"]["query"]["queryState"]["Values"]["projections"][0]["queryRef"] == (
        "Vendas.Total Vendas"
    )


def test_update_visual_replaces_fields_when_given(project_dir: Path, fake_runtime: FakeTomRuntime):
    added = visual_writer.add_visual(
        pbip_path=str(project_dir), page_name="Pagina1", visual_type="card",
        x=0, y=0, width=100, height=50, fields={"Values": ["Vendas.Total Vendas"]},
    )
    visual_name = added["visual_name"]

    result = visual_writer.update_visual(
        pbip_path=str(project_dir), page_name="Pagina1", visual_name=visual_name,
        fields={"Values": ["Regiao.Nome"]},
    )

    assert result["fields"]["Values"] == ["Regiao.Nome"]
    data = json.loads(
        (_visuals_dir(project_dir) / visual_name / "visual.json").read_text(encoding="utf-8")
    )
    validate_visual_json(data)
    assert data["visual"]["query"]["queryState"]["Values"]["projections"][0]["queryRef"] == (
        "Regiao.Nome"
    )
    # posição original preservada -- não passamos x/y/width/height
    assert data["position"]["width"] == 100


def test_update_visual_replaces_textbox_text(project_dir: Path, fake_runtime: FakeTomRuntime):
    added = visual_writer.add_visual(
        pbip_path=str(project_dir), page_name="Pagina1", visual_type="textbox",
        x=0, y=0, width=100, height=50, text="Texto original",
    )
    visual_name = added["visual_name"]

    result = visual_writer.update_visual(
        pbip_path=str(project_dir), page_name="Pagina1", visual_name=visual_name,
        text="Texto novo",
    )

    assert result["text"] == "Texto novo"
    data = json.loads(
        (_visuals_dir(project_dir) / visual_name / "visual.json").read_text(encoding="utf-8")
    )
    validate_visual_json(data)
    paragraphs = data["visual"]["objects"]["general"][0]["properties"]["paragraphs"]
    assert paragraphs[0]["textRuns"][0]["value"] == "Texto novo"


def test_update_visual_keeps_textbox_text_when_only_repositioning(
    project_dir: Path, fake_runtime: FakeTomRuntime
):
    added = visual_writer.add_visual(
        pbip_path=str(project_dir), page_name="Pagina1", visual_type="textbox",
        x=0, y=0, width=100, height=50, text="Mantém isso",
    )
    visual_name = added["visual_name"]

    visual_writer.update_visual(
        pbip_path=str(project_dir), page_name="Pagina1", visual_name=visual_name, x=10, y=10,
    )

    data = json.loads(
        (_visuals_dir(project_dir) / visual_name / "visual.json").read_text(encoding="utf-8")
    )
    paragraphs = data["visual"]["objects"]["general"][0]["properties"]["paragraphs"]
    assert paragraphs[0]["textRuns"][0]["value"] == "Mantém isso"
    assert data["position"]["x"] == 10


def test_update_visual_raises_when_visual_does_not_exist(
    project_dir: Path, fake_runtime: FakeTomRuntime
):
    with pytest.raises(VisualNotFoundError):
        visual_writer.update_visual(
            pbip_path=str(project_dir), page_name="Pagina1", visual_name="fantasma", x=0,
        )


# --- set_slicer_sync / remove_slicer_sync --------------------------------


def test_set_slicer_sync_writes_schema_valid_sync_group(
    project_dir: Path, fake_runtime: FakeTomRuntime
):
    added = visual_writer.add_visual(
        pbip_path=str(project_dir), page_name="Pagina1", visual_type="slicer",
        x=0, y=0, width=100, height=50, fields={"Values": ["Regiao.Nome"]},
    )
    visual_name = added["visual_name"]

    result = visual_writer.set_slicer_sync(
        pbip_path=str(project_dir), page_name="Pagina1", visual_name=visual_name,
        group_name="GrupoRegiao",
    )

    assert result["sync_group"] == {
        "groupName": "GrupoRegiao", "fieldChanges": True, "filterChanges": True,
    }
    data = json.loads(
        (_visuals_dir(project_dir) / visual_name / "visual.json").read_text(encoding="utf-8")
    )
    validate_visual_json(data)
    assert data["visual"]["syncGroup"] == {
        "groupName": "GrupoRegiao", "fieldChanges": True, "filterChanges": True,
    }


def test_set_slicer_sync_accepts_button_slicer(project_dir: Path, fake_runtime: FakeTomRuntime):
    added = visual_writer.add_visual(
        pbip_path=str(project_dir), page_name="Pagina1", visual_type="advancedSlicerVisual",
        x=0, y=0, width=100, height=50, fields={"Values": ["Regiao.Nome"]},
    )

    visual_writer.set_slicer_sync(
        pbip_path=str(project_dir), page_name="Pagina1", visual_name=added["visual_name"], group_name="GrupoRegiao",
    )

    data = json.loads((_visuals_dir(project_dir) / added["visual_name"] / "visual.json").read_text(encoding="utf-8"))
    validate_visual_json(data)
    assert data["visual"]["syncGroup"]["groupName"] == "GrupoRegiao"


def test_set_slicer_sync_raises_for_non_slicer_visual(
    project_dir: Path, fake_runtime: FakeTomRuntime
):
    added = visual_writer.add_visual(
        pbip_path=str(project_dir), page_name="Pagina1", visual_type="card",
        x=0, y=0, width=100, height=50, fields={"Values": ["Vendas.Total Vendas"]},
    )

    with pytest.raises(InvalidVisualRoleError):
        visual_writer.set_slicer_sync(
            pbip_path=str(project_dir), page_name="Pagina1", visual_name=added["visual_name"],
            group_name="GrupoRegiao",
        )


def test_remove_slicer_sync_clears_the_sync_group(project_dir: Path, fake_runtime: FakeTomRuntime):
    added = visual_writer.add_visual(
        pbip_path=str(project_dir), page_name="Pagina1", visual_type="slicer",
        x=0, y=0, width=100, height=50, fields={"Values": ["Regiao.Nome"]},
    )
    visual_name = added["visual_name"]
    visual_writer.set_slicer_sync(
        pbip_path=str(project_dir), page_name="Pagina1", visual_name=visual_name,
        group_name="GrupoRegiao",
    )

    result = visual_writer.remove_slicer_sync(
        pbip_path=str(project_dir), page_name="Pagina1", visual_name=visual_name,
    )

    assert result["sync_group"] is None
    data = json.loads(
        (_visuals_dir(project_dir) / visual_name / "visual.json").read_text(encoding="utf-8")
    )
    validate_visual_json(data)
    assert "syncGroup" not in data["visual"]


# --- set_slicer_config -----------------------------------------------------


def test_set_slicer_config_writes_schema_valid_mode(project_dir: Path, fake_runtime: FakeTomRuntime):
    added = visual_writer.add_visual(
        pbip_path=str(project_dir), page_name="Pagina1", visual_type="slicer",
        x=0, y=0, width=100, height=50, fields={"Values": ["Regiao.Nome"]},
    )
    visual_name = added["visual_name"]

    result = visual_writer.set_slicer_config(
        pbip_path=str(project_dir), page_name="Pagina1", visual_name=visual_name, style="Basic",
    )

    assert result == {
        "visual_name": visual_name, "page_name": "Pagina1", "style": "Basic",
        "selection_mode": None, "show_select_all": None, "show_search": None,
    }
    data = json.loads(
        (_visuals_dir(project_dir) / visual_name / "visual.json").read_text(encoding="utf-8")
    )
    validate_visual_json(data)
    assert data["visual"]["objects"]["data"][0]["properties"]["mode"] == {
        "expr": {"Literal": {"Value": "'Basic'"}}
    }


def _slicer(project_dir: Path) -> str:
    return visual_writer.add_visual(
        pbip_path=str(project_dir), page_name="Pagina1", visual_type="slicer",
        x=0, y=0, width=100, height=200, fields={"Values": ["Regiao.Nome"]},
    )["visual_name"]


def _slicer_objects(project_dir: Path, visual_name: str) -> dict:
    data = json.loads((_visuals_dir(project_dir) / visual_name / "visual.json").read_text(encoding="utf-8"))
    validate_visual_json(data)
    return data["visual"]["objects"]


_TRUE = {"expr": {"Literal": {"Value": "true"}}}
_FALSE = {"expr": {"Literal": {"Value": "false"}}}


def test_set_slicer_config_select_all_and_search_match_desktop(
    project_dir: Path, fake_runtime: FakeTomRuntime
):
    """Reproduz exatamente o que o PRÓPRIO Desktop escreveu ao ligar
    "Mostrar a opção 'Selecionar tudo'" e "Pesquisar" num slicer pela UI
    (capturado ao vivo em 2026-09-25): selection.selectAllCheckboxEnabled
    e general.selfFilterEnabled -- não searchBox.show, como a doc de
    autoria sugeria."""
    name = _slicer(project_dir)

    visual_writer.set_slicer_config(
        pbip_path=str(project_dir), page_name="Pagina1", visual_name=name,
        show_select_all=True, show_search=True,
    )

    objects = _slicer_objects(project_dir, name)
    assert objects["selection"] == [{"properties": {"selectAllCheckboxEnabled": _TRUE}}]
    assert objects["general"] == [{"properties": {"selfFilterEnabled": _TRUE}}]


@pytest.mark.parametrize(
    ("mode", "expected"),
    [
        ("single", {"strictSingleSelect": _TRUE}),
        ("multi_ctrl", {"strictSingleSelect": _FALSE, "singleSelect": _TRUE}),
        ("multi", {"strictSingleSelect": _FALSE, "singleSelect": _FALSE}),
    ],
)
def test_set_slicer_config_selection_mode(project_dir: Path, fake_runtime: FakeTomRuntime, mode, expected):
    name = _slicer(project_dir)
    visual_writer.set_slicer_config(
        pbip_path=str(project_dir), page_name="Pagina1", visual_name=name, selection_mode=mode,
    )
    assert _slicer_objects(project_dir, name)["selection"][0]["properties"] == expected


def test_set_slicer_config_keeps_other_selection_properties(project_dir: Path, fake_runtime: FakeTomRuntime):
    name = _slicer(project_dir)
    visual_writer.set_slicer_config(
        pbip_path=str(project_dir), page_name="Pagina1", visual_name=name, show_select_all=True,
    )
    visual_writer.set_slicer_config(
        pbip_path=str(project_dir), page_name="Pagina1", visual_name=name, selection_mode="multi",
    )
    props = _slicer_objects(project_dir, name)["selection"][0]["properties"]
    assert props["selectAllCheckboxEnabled"] == _TRUE
    assert props["singleSelect"] == _FALSE


def test_set_slicer_config_rejects_unknown_selection_mode(project_dir: Path, fake_runtime: FakeTomRuntime):
    name = _slicer(project_dir)
    with pytest.raises(InvalidVisualRoleError, match="single"):
        visual_writer.set_slicer_config(
            pbip_path=str(project_dir), page_name="Pagina1", visual_name=name, selection_mode="varios",
        )


def test_set_slicer_config_overwrites_existing_mode(project_dir: Path, fake_runtime: FakeTomRuntime):
    added = visual_writer.add_visual(
        pbip_path=str(project_dir), page_name="Pagina1", visual_type="slicer",
        x=0, y=0, width=100, height=50, fields={"Values": ["Regiao.Nome"]},
    )
    visual_name = added["visual_name"]
    visual_writer.set_slicer_config(
        pbip_path=str(project_dir), page_name="Pagina1", visual_name=visual_name, style="Dropdown",
    )

    visual_writer.set_slicer_config(
        pbip_path=str(project_dir), page_name="Pagina1", visual_name=visual_name, style="Between",
    )

    data = json.loads(
        (_visuals_dir(project_dir) / visual_name / "visual.json").read_text(encoding="utf-8")
    )
    assert data["visual"]["objects"]["data"][0]["properties"]["mode"] == {
        "expr": {"Literal": {"Value": "'Between'"}}
    }


def test_set_slicer_config_raises_for_unknown_style(project_dir: Path, fake_runtime: FakeTomRuntime):
    added = visual_writer.add_visual(
        pbip_path=str(project_dir), page_name="Pagina1", visual_type="slicer",
        x=0, y=0, width=100, height=50, fields={"Values": ["Regiao.Nome"]},
    )

    with pytest.raises(InvalidVisualRoleError):
        visual_writer.set_slicer_config(
            pbip_path=str(project_dir), page_name="Pagina1", visual_name=added["visual_name"],
            style="Fantasma",
        )


def test_set_slicer_config_raises_for_non_slicer_visual(
    project_dir: Path, fake_runtime: FakeTomRuntime
):
    added = visual_writer.add_visual(
        pbip_path=str(project_dir), page_name="Pagina1", visual_type="card",
        x=0, y=0, width=100, height=50, fields={"Values": ["Vendas.Total Vendas"]},
    )

    with pytest.raises(InvalidVisualRoleError):
        visual_writer.set_slicer_config(
            pbip_path=str(project_dir), page_name="Pagina1", visual_name=added["visual_name"],
            style="Basic",
        )


# --- add_navigation_button -----------------------------------------------


def test_add_navigation_button_writes_schema_valid_page_target(
    project_dir: Path, fake_runtime: FakeTomRuntime
):
    result = visual_writer.add_navigation_button(
        pbip_path=str(project_dir), page_name="Pagina1",
        x=0, y=0, width=100, height=40, target_type="page", target="Pagina1",
    )

    visual_dirs = list(_visuals_dir(project_dir).iterdir())
    assert len(visual_dirs) == 1
    data = json.loads((visual_dirs[0] / "visual.json").read_text(encoding="utf-8"))
    validate_visual_json(data)
    assert data["visual"]["visualType"] == "actionButton"
    link = data["visual"]["visualContainerObjects"]["visualLink"][0]["properties"]
    assert link["type"] == {"expr": {"Literal": {"Value": "'PageNavigation'"}}}
    assert link["navigationSection"] == {"expr": {"Literal": {"Value": "'Pagina1'"}}}
    assert result["target_type"] == "page"
    assert result["target"] == "Pagina1"


def test_add_navigation_button_writes_schema_valid_bookmark_target(
    project_dir: Path, fake_runtime: FakeTomRuntime
):
    result = visual_writer.add_navigation_button(
        pbip_path=str(project_dir), page_name="Pagina1",
        x=0, y=0, width=100, height=40, target_type="bookmark", target="bk1",
    )

    data = json.loads(
        (list(_visuals_dir(project_dir).iterdir())[0] / "visual.json").read_text(encoding="utf-8")
    )
    validate_visual_json(data)
    link = data["visual"]["visualContainerObjects"]["visualLink"][0]["properties"]
    assert link["type"] == {"expr": {"Literal": {"Value": "'Bookmark'"}}}
    assert link["bookmark"] == {"expr": {"Literal": {"Value": "'bk1'"}}}
    assert result["target_type"] == "bookmark"


def test_add_navigation_button_raises_for_unknown_target_type(
    project_dir: Path, fake_runtime: FakeTomRuntime
):
    with pytest.raises(InvalidVisualRoleError):
        visual_writer.add_navigation_button(
            pbip_path=str(project_dir), page_name="Pagina1",
            x=0, y=0, width=100, height=40, target_type="nada", target="X",
        )
    assert not _visuals_dir(project_dir).exists() or list(_visuals_dir(project_dir).iterdir()) == []


def test_add_navigation_button_raises_when_page_does_not_exist(
    project_dir: Path, fake_runtime: FakeTomRuntime
):
    with pytest.raises(PageNotFoundError):
        visual_writer.add_navigation_button(
            pbip_path=str(project_dir), page_name="PaginaFantasma",
            x=0, y=0, width=100, height=40, target_type="page", target="Pagina1",
        )


# --- set_visual_color -----------------------------------------------------


def test_set_visual_color_adds_new_data_point_entry(project_dir: Path, fake_runtime: FakeTomRuntime):
    added = visual_writer.add_visual(
        pbip_path=str(project_dir), page_name="Pagina1", visual_type="clusteredColumnChart",
        x=0, y=0, width=400, height=300,
        fields={"Category": ["Regiao.Nome"], "Y": ["Vendas.Total Vendas"]},
    )
    visual_name = added["visual_name"]

    result = visual_writer.set_visual_color(
        pbip_path=str(project_dir), page_name="Pagina1", visual_name=visual_name,
        query_ref="Vendas.Total Vendas", hex_color="#2E86AB",
    )

    assert result == {
        "visual_name": visual_name, "page_name": "Pagina1",
        "query_ref": "Vendas.Total Vendas", "color": "#2E86AB",
    }
    data = json.loads(
        (_visuals_dir(project_dir) / visual_name / "visual.json").read_text(encoding="utf-8")
    )
    validate_visual_json(data)
    data_point = data["visual"]["objects"]["dataPoint"][0]
    assert data_point["selector"] == {"metadata": "Vendas.Total Vendas"}
    assert data_point["properties"]["fill"] == {
        "solid": {"color": {"expr": {"Literal": {"Value": "'#2E86AB'"}}}}
    }


def test_set_visual_color_updates_existing_entry_for_same_query_ref(
    project_dir: Path, fake_runtime: FakeTomRuntime
):
    added = visual_writer.add_visual(
        pbip_path=str(project_dir), page_name="Pagina1", visual_type="clusteredColumnChart",
        x=0, y=0, width=400, height=300,
        fields={"Category": ["Regiao.Nome"], "Y": ["Vendas.Total Vendas"]},
    )
    visual_name = added["visual_name"]
    visual_writer.set_visual_color(
        pbip_path=str(project_dir), page_name="Pagina1", visual_name=visual_name,
        query_ref="Vendas.Total Vendas", hex_color="#2E86AB",
    )

    visual_writer.set_visual_color(
        pbip_path=str(project_dir), page_name="Pagina1", visual_name=visual_name,
        query_ref="Vendas.Total Vendas", hex_color="#E6553A",
    )

    data = json.loads(
        (_visuals_dir(project_dir) / visual_name / "visual.json").read_text(encoding="utf-8")
    )
    data_points = data["visual"]["objects"]["dataPoint"]
    assert len(data_points) == 1
    assert data_points[0]["properties"]["fill"]["solid"]["color"]["expr"]["Literal"]["Value"] == "'#E6553A'"


def test_set_visual_color_raises_for_invalid_hex(project_dir: Path, fake_runtime: FakeTomRuntime):
    added = visual_writer.add_visual(
        pbip_path=str(project_dir), page_name="Pagina1", visual_type="card",
        x=0, y=0, width=1, height=1, fields={"Values": ["Vendas.Total Vendas"]},
    )

    with pytest.raises(InvalidVisualRoleError):
        visual_writer.set_visual_color(
            pbip_path=str(project_dir), page_name="Pagina1", visual_name=added["visual_name"],
            query_ref="Vendas.Total Vendas", hex_color="azul",
        )


def test_set_visual_color_raises_when_visual_does_not_exist(
    project_dir: Path, fake_runtime: FakeTomRuntime
):
    with pytest.raises(VisualNotFoundError):
        visual_writer.set_visual_color(
            pbip_path=str(project_dir), page_name="Pagina1", visual_name="fantasma",
            query_ref="Vendas.Total Vendas", hex_color="#2E86AB",
        )


# --- set_visual_title ------------------------------------------------------


def test_set_visual_title_writes_all_given_properties(project_dir: Path, fake_runtime: FakeTomRuntime):
    added = visual_writer.add_visual(
        pbip_path=str(project_dir), page_name="Pagina1", visual_type="card",
        x=0, y=0, width=100, height=50, fields={"Values": ["Vendas.Total Vendas"]},
    )
    visual_name = added["visual_name"]

    result = visual_writer.set_visual_title(
        pbip_path=str(project_dir), page_name="Pagina1", visual_name=visual_name,
        text="Receita por Categoria", font_size=14, font_color="#333333",
    )

    assert result == {
        "visual_name": visual_name, "page_name": "Pagina1",
        "text": "Receita por Categoria", "font_size": 14, "font_color": "#333333", "show": None,
    }
    data = json.loads(
        (_visuals_dir(project_dir) / visual_name / "visual.json").read_text(encoding="utf-8")
    )
    validate_visual_json(data)
    title_properties = data["visual"]["visualContainerObjects"]["title"][0]["properties"]
    assert title_properties["text"] == {"expr": {"Literal": {"Value": "'Receita por Categoria'"}}}
    assert title_properties["fontSize"] == {"expr": {"Literal": {"Value": "14D"}}}
    assert title_properties["fontColor"] == {
        "solid": {"color": {"expr": {"Literal": {"Value": "'#333333'"}}}}
    }


def test_set_visual_title_can_hide_the_title(project_dir: Path, fake_runtime: FakeTomRuntime):
    added = visual_writer.add_visual(
        pbip_path=str(project_dir), page_name="Pagina1", visual_type="card",
        x=0, y=0, width=100, height=50, fields={"Values": ["Vendas.Total Vendas"]},
    )
    visual_name = added["visual_name"]

    visual_writer.set_visual_title(
        pbip_path=str(project_dir), page_name="Pagina1", visual_name=visual_name, show=False,
    )

    data = json.loads(
        (_visuals_dir(project_dir) / visual_name / "visual.json").read_text(encoding="utf-8")
    )
    validate_visual_json(data)
    assert data["visual"]["visualContainerObjects"]["title"][0]["properties"]["show"] == {
        "expr": {"Literal": {"Value": "false"}}
    }


def test_set_visual_title_only_changes_given_properties(
    project_dir: Path, fake_runtime: FakeTomRuntime
):
    added = visual_writer.add_visual(
        pbip_path=str(project_dir), page_name="Pagina1", visual_type="card",
        x=0, y=0, width=100, height=50, fields={"Values": ["Vendas.Total Vendas"]},
    )
    visual_name = added["visual_name"]
    visual_writer.set_visual_title(
        pbip_path=str(project_dir), page_name="Pagina1", visual_name=visual_name, text="Primeiro",
    )

    visual_writer.set_visual_title(
        pbip_path=str(project_dir), page_name="Pagina1", visual_name=visual_name, font_size=20,
    )

    data = json.loads(
        (_visuals_dir(project_dir) / visual_name / "visual.json").read_text(encoding="utf-8")
    )
    title_properties = data["visual"]["visualContainerObjects"]["title"][0]["properties"]
    assert title_properties["text"] == {"expr": {"Literal": {"Value": "'Primeiro'"}}}
    assert title_properties["fontSize"] == {"expr": {"Literal": {"Value": "20D"}}}


def test_set_visual_title_raises_for_invalid_font_color(
    project_dir: Path, fake_runtime: FakeTomRuntime
):
    added = visual_writer.add_visual(
        pbip_path=str(project_dir), page_name="Pagina1", visual_type="card",
        x=0, y=0, width=100, height=50, fields={"Values": ["Vendas.Total Vendas"]},
    )

    with pytest.raises(InvalidVisualRoleError):
        visual_writer.set_visual_title(
            pbip_path=str(project_dir), page_name="Pagina1", visual_name=added["visual_name"],
            font_color="azul",
        )


def test_set_visual_title_raises_when_visual_does_not_exist(
    project_dir: Path, fake_runtime: FakeTomRuntime
):
    with pytest.raises(VisualNotFoundError):
        visual_writer.set_visual_title(
            pbip_path=str(project_dir), page_name="Pagina1", visual_name="fantasma", text="X",
        )


# --- set_visual_color_gradient (formatação condicional) --------------------


def test_set_visual_color_gradient_two_stop_on_chart(project_dir: Path, fake_runtime: FakeTomRuntime):
    added = visual_writer.add_visual(
        pbip_path=str(project_dir), page_name="Pagina1", visual_type="clusteredColumnChart",
        x=0, y=0, width=400, height=300,
        fields={"Category": ["Regiao.Nome"], "Y": ["Vendas.Total Vendas"]},
    )
    visual_name = added["visual_name"]

    result = visual_writer.set_visual_color_gradient(
        pbip_path=str(project_dir), page_name="Pagina1", visual_name=visual_name,
        query_ref="Vendas.Total Vendas", min_color="#D0E8F5", max_color="#56B4E9",
    )

    assert result == {
        "visual_name": visual_name, "page_name": "Pagina1",
        "query_ref": "Vendas.Total Vendas", "gradient": "linearGradient2",
    }
    data = json.loads(
        (_visuals_dir(project_dir) / visual_name / "visual.json").read_text(encoding="utf-8")
    )
    validate_visual_json(data)
    entry = data["visual"]["objects"]["dataPoint"][0]
    assert "metadata" not in entry["selector"]
    assert entry["selector"] == {"data": [{"dataViewWildcard": {"matchingOption": 0}}]}
    fill_rule = entry["properties"]["fill"]["expr"]["FillRule"]["FillRule"]["linearGradient2"]
    assert fill_rule["min"]["color"] == {"Literal": {"Value": "'#D0E8F5'"}}
    assert fill_rule["max"]["color"] == {"Literal": {"Value": "'#56B4E9'"}}
    input_node = entry["properties"]["fill"]["expr"]["FillRule"]["Input"]
    assert input_node == {
        "Measure": {"Expression": {"SourceRef": {"Entity": "Vendas"}}, "Property": "Total Vendas"}
    }


def test_set_visual_color_gradient_three_stop_requires_all_values(
    project_dir: Path, fake_runtime: FakeTomRuntime
):
    added = visual_writer.add_visual(
        pbip_path=str(project_dir), page_name="Pagina1", visual_type="card",
        x=0, y=0, width=1, height=1, fields={"Values": ["Vendas.Total Vendas"]},
    )

    with pytest.raises(InvalidVisualRoleError):
        visual_writer.set_visual_color_gradient(
            pbip_path=str(project_dir), page_name="Pagina1", visual_name=added["visual_name"],
            query_ref="Vendas.Total Vendas", min_color="#FF0000", max_color="#00FF00",
            mid_color="#FFFFFF",  # falta min_value/mid_value/max_value
        )


def test_set_visual_color_gradient_three_stop_writes_all_stops(
    project_dir: Path, fake_runtime: FakeTomRuntime
):
    added = visual_writer.add_visual(
        pbip_path=str(project_dir), page_name="Pagina1", visual_type="card",
        x=0, y=0, width=1, height=1, fields={"Values": ["Vendas.Total Vendas"]},
    )
    visual_name = added["visual_name"]

    result = visual_writer.set_visual_color_gradient(
        pbip_path=str(project_dir), page_name="Pagina1", visual_name=visual_name,
        query_ref="Vendas.Total Vendas", min_color="#FF0000", max_color="#00FF00",
        mid_color="#FFFFFF", min_value=-5000000, mid_value=0, max_value=5000000,
    )

    assert result["gradient"] == "linearGradient3"
    data = json.loads(
        (_visuals_dir(project_dir) / visual_name / "visual.json").read_text(encoding="utf-8")
    )
    validate_visual_json(data)
    fill_rule = data["visual"]["objects"]["dataPoint"][0]["properties"]["fill"]["expr"]["FillRule"]["FillRule"]
    gradient = fill_rule["linearGradient3"]
    assert gradient["min"] == {"color": {"Literal": {"Value": "'#FF0000'"}}, "value": {"Literal": {"Value": "-5000000D"}}}
    assert gradient["mid"] == {"color": {"Literal": {"Value": "'#FFFFFF'"}}, "value": {"Literal": {"Value": "0D"}}}
    assert gradient["max"] == {"color": {"Literal": {"Value": "'#00FF00'"}}, "value": {"Literal": {"Value": "5000000D"}}}


def test_set_visual_color_gradient_on_table_visual_uses_data_and_metadata_selector(
    project_dir: Path, fake_runtime: FakeTomRuntime
):
    added = visual_writer.add_visual(
        pbip_path=str(project_dir), page_name="Pagina1", visual_type="tableEx",
        x=0, y=0, width=400, height=300, fields={"Values": ["Vendas.Total Vendas"]},
    )
    visual_name = added["visual_name"]

    visual_writer.set_visual_color_gradient(
        pbip_path=str(project_dir), page_name="Pagina1", visual_name=visual_name,
        query_ref="Vendas.Total Vendas", min_color="#DEEFFF", max_color="#118DFF",
    )

    data = json.loads(
        (_visuals_dir(project_dir) / visual_name / "visual.json").read_text(encoding="utf-8")
    )
    validate_visual_json(data)
    entry = data["visual"]["objects"]["values"][0]
    assert entry["selector"] == {
        "data": [{"dataViewWildcard": {"matchingOption": 1}}],
        "metadata": "Vendas.Total Vendas",
    }
    assert "backColor" in entry["properties"]
    assert "fill" not in entry["properties"]


def test_set_visual_color_gradient_raises_for_invalid_hex(
    project_dir: Path, fake_runtime: FakeTomRuntime
):
    added = visual_writer.add_visual(
        pbip_path=str(project_dir), page_name="Pagina1", visual_type="card",
        x=0, y=0, width=1, height=1, fields={"Values": ["Vendas.Total Vendas"]},
    )

    with pytest.raises(InvalidVisualRoleError):
        visual_writer.set_visual_color_gradient(
            pbip_path=str(project_dir), page_name="Pagina1", visual_name=added["visual_name"],
            query_ref="Vendas.Total Vendas", min_color="azul", max_color="#00FF00",
        )


def test_set_visual_color_gradient_raises_for_unknown_query_ref(
    project_dir: Path, fake_runtime: FakeTomRuntime
):
    added = visual_writer.add_visual(
        pbip_path=str(project_dir), page_name="Pagina1", visual_type="card",
        x=0, y=0, width=1, height=1, fields={"Values": ["Vendas.Total Vendas"]},
    )

    with pytest.raises(UnknownFieldError):
        visual_writer.set_visual_color_gradient(
            pbip_path=str(project_dir), page_name="Pagina1", visual_name=added["visual_name"],
            query_ref="Vendas.NadaAqui", min_color="#FF0000", max_color="#00FF00",
        )


# --- set_visual_conditional_color -----------------------------------------


def test_set_visual_conditional_color_writes_rules_and_default(
    project_dir: Path, fake_runtime: FakeTomRuntime
):
    added = visual_writer.add_visual(
        pbip_path=str(project_dir), page_name="Pagina1", visual_type="tableEx",
        x=0, y=0, width=400, height=300, fields={"Values": ["Vendas.Total Vendas"]},
    )
    visual_name = added["visual_name"]

    result = visual_writer.set_visual_conditional_color(
        pbip_path=str(project_dir), page_name="Pagina1", visual_name=visual_name,
        query_ref="Vendas.Total Vendas",
        rules=[
            {"operator": ">=", "value": 500, "color": "#1AAB40"},
            {"operator": "<", "value": 0, "color": "#D64554"},
        ],
        default_color="#FFFFFF",
    )

    assert result == {
        "visual_name": visual_name, "page_name": "Pagina1",
        "query_ref": "Vendas.Total Vendas", "rules_count": 2,
    }
    data = json.loads(
        (_visuals_dir(project_dir) / visual_name / "visual.json").read_text(encoding="utf-8")
    )
    validate_visual_json(data)
    conditional = data["visual"]["objects"]["values"][0]["properties"]["backColor"]["expr"]["Conditional"]
    assert len(conditional["Cases"]) == 2
    assert conditional["Cases"][0]["Condition"]["Comparison"]["ComparisonKind"] == 2
    assert conditional["Cases"][0]["Value"] == {"Literal": {"Value": "'#1AAB40'"}}
    assert conditional["Cases"][1]["Condition"]["Comparison"]["ComparisonKind"] == 3
    assert conditional["DefaultValue"] == {"Literal": {"Value": "'#FFFFFF'"}}


def test_set_visual_conditional_color_raises_for_invalid_operator(
    project_dir: Path, fake_runtime: FakeTomRuntime
):
    added = visual_writer.add_visual(
        pbip_path=str(project_dir), page_name="Pagina1", visual_type="card",
        x=0, y=0, width=1, height=1, fields={"Values": ["Vendas.Total Vendas"]},
    )

    with pytest.raises(InvalidVisualRoleError):
        visual_writer.set_visual_conditional_color(
            pbip_path=str(project_dir), page_name="Pagina1", visual_name=added["visual_name"],
            query_ref="Vendas.Total Vendas",
            rules=[{"operator": "!=", "value": 0, "color": "#FF0000"}],
            default_color="#FFFFFF",
        )


# --- set_visual_field_parameter --------------------------------------------


def test_set_visual_field_parameter_writes_projection_and_field_parameters_block(
    project_dir: Path, fake_runtime: FakeTomRuntime
):
    added = visual_writer.add_visual(
        pbip_path=str(project_dir), page_name="Pagina1", visual_type="card",
        x=0, y=0, width=200, height=150, fields={"Values": ["Vendas.Total Vendas"]},
    )
    visual_name = added["visual_name"]

    result = visual_writer.set_visual_field_parameter(
        pbip_path=str(project_dir), page_name="Pagina1", visual_name=visual_name,
        role="Values", field_parameter_table="Metrica", display_column="Value1",
        default_field="Vendas.Total Vendas",
    )

    assert result == {
        "visual_name": visual_name, "page_name": "Pagina1", "role": "Values",
        "field_parameter_table": "Metrica", "default_field": "Vendas.Total Vendas",
    }

    data = json.loads(
        (_visuals_dir(project_dir) / visual_name / "visual.json").read_text(encoding="utf-8")
    )
    validate_visual_json(data)

    values = data["visual"]["query"]["queryState"]["Values"]
    assert values["projections"] == [
        {
            "queryRef": "Vendas.Total Vendas",
            "nativeQueryRef": "Total Vendas",
            "displayName": "Total Vendas",
            "field": {
                "Measure": {
                    "Expression": {"SourceRef": {"Entity": "Vendas"}},
                    "Property": "Total Vendas",
                }
            },
        }
    ]

    field_parameters = values["fieldParameters"]
    assert field_parameters == [
        {
            "parameterExpr": {
                "Column": {
                    "Expression": {"SourceRef": {"Entity": "Metrica"}},
                    "Property": "Value1",
                }
            },
            "index": 0,
            "length": 1,
        }
    ]


def test_set_visual_field_parameter_replaces_only_the_targeted_role(
    project_dir: Path, fake_runtime: FakeTomRuntime
):
    added = visual_writer.add_visual(
        pbip_path=str(project_dir), page_name="Pagina1", visual_type="clusteredColumnChart",
        x=0, y=0, width=400, height=300,
        fields={"Category": ["Regiao.Nome"], "Y": ["Vendas.Total Vendas"]},
    )
    visual_name = added["visual_name"]

    visual_writer.set_visual_field_parameter(
        pbip_path=str(project_dir), page_name="Pagina1", visual_name=visual_name,
        role="Y", field_parameter_table="Metrica", display_column="Value1",
        default_field="Vendas.Total Vendas",
    )

    data = json.loads(
        (_visuals_dir(project_dir) / visual_name / "visual.json").read_text(encoding="utf-8")
    )
    validate_visual_json(data)
    query_state = data["visual"]["query"]["queryState"]
    assert query_state["Category"]["projections"][0]["queryRef"] == "Regiao.Nome"
    assert query_state["Y"]["projections"][0]["queryRef"] == "Vendas.Total Vendas"


def test_set_visual_field_parameter_raises_for_unknown_field(
    project_dir: Path, fake_runtime: FakeTomRuntime
):
    added = visual_writer.add_visual(
        pbip_path=str(project_dir), page_name="Pagina1", visual_type="card",
        x=0, y=0, width=200, height=150, fields={"Values": ["Vendas.Total Vendas"]},
    )

    with pytest.raises(UnknownFieldError):
        visual_writer.set_visual_field_parameter(
            pbip_path=str(project_dir), page_name="Pagina1", visual_name=added["visual_name"],
            role="Values", field_parameter_table="Metrica", display_column="Value1",
            default_field="Vendas.Fantasma",
        )


def test_set_visual_title_hides_or_changes_the_subtitle(project_dir: Path, fake_runtime: FakeTomRuntime):
    """Subtítulo automático ("X e Y por Z") embaixo do título: objeto VCO
    `subTitle` (show/text) -- schema oficial de tema, doc formatting.md
    (lista de VCOs). Achado na réplica de dashboard: o original não tem."""
    added = visual_writer.add_visual(
        pbip_path=str(project_dir), page_name="Pagina1", visual_type="card",
        x=0, y=0, width=100, height=50, fields={"Values": ["Vendas.Total Vendas"]},
    )
    visual_name = added["visual_name"]

    result = visual_writer.set_visual_title(
        pbip_path=str(project_dir), page_name="Pagina1", visual_name=visual_name,
        subtitle_show=False,
    )
    data = json.loads((_visuals_dir(project_dir) / visual_name / "visual.json").read_text(encoding="utf-8"))
    validate_visual_json(data)
    assert data["visual"]["visualContainerObjects"]["subTitle"] == [
        {"properties": {"show": {"expr": {"Literal": {"Value": "false"}}}}}
    ]
    assert result["subtitle_show"] is False

    visual_writer.set_visual_title(
        pbip_path=str(project_dir), page_name="Pagina1", visual_name=visual_name,
        subtitle_show=True, subtitle_text="Ano de 2014",
    )
    data = json.loads((_visuals_dir(project_dir) / visual_name / "visual.json").read_text(encoding="utf-8"))
    props = data["visual"]["visualContainerObjects"]["subTitle"][0]["properties"]
    assert props["show"] == {"expr": {"Literal": {"Value": "true"}}}
    assert props["text"] == {"expr": {"Literal": {"Value": "'Ano de 2014'"}}}
    validate_visual_json(data)


def test_set_visual_title_escapes_apostrophe(project_dir: Path, fake_runtime: FakeTomRuntime):
    added = visual_writer.add_visual(
        pbip_path=str(project_dir), page_name="Pagina1", visual_type="card",
        x=0, y=0, width=100, height=50, fields={"Values": ["Vendas.Total Vendas"]},
    )
    visual_writer.set_visual_title(
        pbip_path=str(project_dir), page_name="Pagina1", visual_name=added["visual_name"], text="D'Ávila",
    )
    data = json.loads((_visuals_dir(project_dir) / added["visual_name"] / "visual.json").read_text(encoding="utf-8"))
    assert data["visual"]["visualContainerObjects"]["title"][0]["properties"]["text"] == {
        "expr": {"Literal": {"Value": "'D''Ávila'"}}
    }


# --- botão: "limpar segmentações", transparente e com texto -----------------------
#
# Doc oficial button-part-02.md (Action Types): 'ClearAllSlicers' sem
# destino; button.md (Template): objetos `text`/`icon`/`fill`/`outline`
# com o padrão "dual-entry" (show sem selector, estilo com selector
# default) e VCO background/border show false.


def _only_visual(project_dir: Path) -> dict:
    data = json.loads((list(_visuals_dir(project_dir).iterdir())[0] / "visual.json").read_text(encoding="utf-8"))
    validate_visual_json(data)
    return data


def test_clear_slicers_button_needs_no_target(project_dir: Path, fake_runtime: FakeTomRuntime):
    result = visual_writer.add_navigation_button(
        pbip_path=str(project_dir), page_name="Pagina1",
        x=0, y=0, width=40, height=40, target_type="clear_slicers",
    )

    link = _only_visual(project_dir)["visual"]["visualContainerObjects"]["visualLink"][0]["properties"]
    assert link == {"show": {"expr": {"Literal": {"Value": "true"}}}, "type": {"expr": {"Literal": {"Value": "'ClearAllSlicers'"}}}}
    assert result["target_type"] == "clear_slicers"


def test_page_or_bookmark_button_still_needs_target(project_dir: Path, fake_runtime: FakeTomRuntime):
    with pytest.raises(InvalidVisualRoleError):
        visual_writer.add_navigation_button(
            pbip_path=str(project_dir), page_name="Pagina1", x=0, y=0, width=40, height=40, target_type="page",
        )


def test_transparent_button_hides_every_layer(project_dir: Path, fake_runtime: FakeTomRuntime):
    """Botão invisível por cima de algo desenhado no fundo (ex: um círculo
    de navegação numa imagem de fundo)."""
    visual_writer.add_navigation_button(
        pbip_path=str(project_dir), page_name="Pagina1",
        x=0, y=0, width=80, height=80, target_type="page", target="Pagina1", transparent=True,
    )

    visual = _only_visual(project_dir)["visual"]
    off = [{"properties": {"show": {"expr": {"Literal": {"Value": "false"}}}}}]
    for obj in ("fill", "outline", "text", "icon"):
        assert visual["objects"][obj] == off
    assert visual["visualContainerObjects"]["background"] == off
    assert visual["visualContainerObjects"]["border"] == off


def test_button_with_text_uses_dual_entry(project_dir: Path, fake_runtime: FakeTomRuntime):
    visual_writer.add_navigation_button(
        pbip_path=str(project_dir), page_name="Pagina1",
        x=0, y=0, width=120, height=40, target_type="page", target="Pagina1",
        text="Visão Geral", text_color="#FFFFFF", text_size=10,
    )

    text = _only_visual(project_dir)["visual"]["objects"]["text"]
    assert text == [
        {"properties": {"show": {"expr": {"Literal": {"Value": "true"}}}}},
        {"properties": {
            "text": {"expr": {"Literal": {"Value": "'Visão Geral'"}}},
            "fontColor": {"solid": {"color": {"expr": {"Literal": {"Value": "'#FFFFFF'"}}}}},
            "fontSize": {"expr": {"Literal": {"Value": "10D"}}},
        }, "selector": {"id": "default"}},
    ]


# --- ordem de camadas (z) ------------------------------------------------------------
#
# Achado na réplica de dashboard (2026-09-30): todo visual saía com z=0 e a
# ordem de empilhamento ficava indefinida (painel por cima dos gráficos,
# slicer invisível por cima dos cartões). Visual novo vai POR CIMA dos que
# já existem, como no Desktop -- passos de 1000 (template oficial usa
# z/tabOrder 1000).


def _z_of(project_dir: Path, name: str) -> tuple:
    pos = json.loads((_visuals_dir(project_dir) / name / "visual.json").read_text(encoding="utf-8"))["position"]
    return pos["z"], pos["tabOrder"]


def test_new_visuals_stack_on_top(project_dir: Path, fake_runtime: FakeTomRuntime):
    first = visual_writer.add_visual(
        pbip_path=str(project_dir), page_name="Pagina1", visual_type="card",
        x=0, y=0, width=100, height=50, fields={"Values": ["Vendas.Total Vendas"]},
    )["visual_name"]
    second = visual_writer.add_visual(
        pbip_path=str(project_dir), page_name="Pagina1", visual_type="textbox",
        x=0, y=0, width=100, height=50, text="x",
    )["visual_name"]
    button = visual_writer.add_navigation_button(
        pbip_path=str(project_dir), page_name="Pagina1", x=0, y=0, width=10, height=10,
        target_type="clear_slicers",
    )["visual_name"]

    assert _z_of(project_dir, first) == (1000, 1000)
    assert _z_of(project_dir, second) == (2000, 2000)
    assert _z_of(project_dir, button) == (3000, 3000)


def test_update_visual_can_change_z(project_dir: Path, fake_runtime: FakeTomRuntime):
    name = visual_writer.add_visual(
        pbip_path=str(project_dir), page_name="Pagina1", visual_type="textbox",
        x=0, y=0, width=100, height=50, text="x",
    )["visual_name"]

    visual_writer.update_visual(pbip_path=str(project_dir), page_name="Pagina1", visual_name=name, z=9000)

    assert _z_of(project_dir, name)[0] == 9000
    data = json.loads((_visuals_dir(project_dir) / name / "visual.json").read_text(encoding="utf-8"))
    validate_visual_json(data)


def test_update_visual_moves_a_button_without_catalog(project_dir: Path, fake_runtime: FakeTomRuntime):
    """Achado na réplica: mover/reordenar um botão (actionButton, fora do
    catálogo de visuais ligados a dado) falhava com UnknownVisualTypeError.
    Só posição/camada não depende do tipo."""
    name = visual_writer.add_navigation_button(
        pbip_path=str(project_dir), page_name="Pagina1", x=0, y=0, width=10, height=10,
        target_type="clear_slicers", transparent=True,
    )["visual_name"]

    visual_writer.update_visual(pbip_path=str(project_dir), page_name="Pagina1", visual_name=name, x=50, z=7000)

    data = json.loads((_visuals_dir(project_dir) / name / "visual.json").read_text(encoding="utf-8"))
    validate_visual_json(data)
    assert data["position"]["x"] == 50 and data["position"]["z"] == 7000
    assert data["visual"]["objects"]["fill"]  # formatação preservada


# --- cor por ITEM de legenda/categoria (scopeId) -----------------------------------
#
# Doc oficial formatting.md ("data" selector / scope identity): dataPoint com
# selector {"data": [{"scopeId": {"Comparison": {"ComparisonKind": 0, "Left":
# {"Column": ...}, "Right": {"Literal": ...}}}}]} -- "Only ComparisonKind: 0
# (Equal) is honored". Achado na réplica: a legenda vinda de um calculation
# group ("Atual"/"PY") ficava com as cores do tema.


def test_set_visual_color_by_legend_value(project_dir: Path, fake_runtime: FakeTomRuntime):
    fake_runtime.add_table(TableInfo(name="Calc", columns=(ColumnInfo(name="Item", data_type="String"),)))
    name = visual_writer.add_visual(
        pbip_path=str(project_dir), page_name="Pagina1", visual_type="clusteredColumnChart",
        x=0, y=0, width=300, height=200,
        fields={"Category": ["Vendas.Valor"], "Y": ["Vendas.Total Vendas"], "Series": ["Calc.Item"]},
    )["visual_name"]

    result = visual_writer.set_visual_color(
        pbip_path=str(project_dir), page_name="Pagina1", visual_name=name,
        query_ref="Calc.Item", value="PY", hex_color="#8F8F8F",
    )
    visual_writer.set_visual_color(
        pbip_path=str(project_dir), page_name="Pagina1", visual_name=name,
        query_ref="Calc.Item", value="PY", hex_color="#999999",
    )

    data = json.loads((_visuals_dir(project_dir) / name / "visual.json").read_text(encoding="utf-8"))
    validate_visual_json(data)
    [entry] = data["visual"]["objects"]["dataPoint"]
    assert entry == {
        "properties": {"fill": {"solid": {"color": {"expr": {"Literal": {"Value": "'#999999'"}}}}}},
        "selector": {"data": [{"scopeId": {"Comparison": {
            "ComparisonKind": 0,
            "Left": {"Column": {"Expression": {"SourceRef": {"Entity": "Calc"}}, "Property": "Item"}},
            "Right": {"Literal": {"Value": "'PY'"}},
        }}}]},
    }
    assert result["value"] == "PY"


def test_color_by_value_requires_a_column(project_dir: Path, fake_runtime: FakeTomRuntime):
    name = visual_writer.add_visual(
        pbip_path=str(project_dir), page_name="Pagina1", visual_type="card",
        x=0, y=0, width=100, height=50, fields={"Values": ["Vendas.Total Vendas"]},
    )["visual_name"]
    with pytest.raises(InvalidVisualRoleError, match="coluna"):
        visual_writer.set_visual_color(
            pbip_path=str(project_dir), page_name="Pagina1", visual_name=name,
            query_ref="Vendas.Total Vendas", value="x", hex_color="#999999",
        )


# --- ícone personalizado no botão ---------------------------------------------------
#
# Comparação com o Desktop (2026-09-30, ícone "Personalizado" posto num botão
# pela UI): `icon` com UMA entrada (selector default) -- shapeType 'custom' +
# image.image.{name, url (ResourcePackageItem RegisteredResources), scaling
# 'Normal'} -- sem entrada separada de `show`.


def test_button_with_custom_icon_like_the_desktop(project_dir: Path, fake_runtime: FakeTomRuntime, tmp_path: Path):
    icon = tmp_path / "info.svg"
    icon.write_bytes(b'<svg xmlns="http://www.w3.org/2000/svg"/>')

    result = visual_writer.add_navigation_button(
        pbip_path=str(project_dir), page_name="Pagina1", x=0, y=0, width=32, height=32,
        target_type="clear_slicers", transparent=True, icon_path=str(icon),
    )

    visual = _only_visual(project_dir)["visual"]
    [entry] = visual["objects"]["icon"]
    item = entry["properties"]["image"]["image"]["url"]["expr"]["ResourcePackageItem"]["ItemName"]
    assert entry == {"properties": {
        "shapeType": {"expr": {"Literal": {"Value": "'custom'"}}},
        "image": {"image": {
            "name": {"expr": {"Literal": {"Value": "'info.svg'"}}},
            "url": {"expr": {"ResourcePackageItem": {
                "PackageName": "RegisteredResources", "PackageType": 1, "ItemName": item,
            }}},
            "scaling": {"expr": {"Literal": {"Value": "'Normal'"}}},
        }},
    }, "selector": {"id": "default"}}
    # transparente continua sem preenchimento/contorno/texto -- só o ícone
    off = [{"properties": {"show": {"expr": {"Literal": {"Value": "false"}}}}}]
    assert visual["objects"]["fill"] == off and visual["objects"]["text"] == off
    assert (project_dir / "Vendas.Report" / "StaticResources" / "RegisteredResources" / item).is_file()
    assert result["icon"] == item


def test_button_icon_rejects_non_image(project_dir: Path, fake_runtime: FakeTomRuntime, tmp_path: Path):
    from errors import InvalidVisualFormattingError

    bad = tmp_path / "planilha.xlsx"
    bad.write_bytes(b"x")
    with pytest.raises(InvalidVisualFormattingError):
        visual_writer.add_navigation_button(
            pbip_path=str(project_dir), page_name="Pagina1", x=0, y=0, width=32, height=32,
            target_type="clear_slicers", icon_path=str(bad),
        )
    assert list(_visuals_dir(project_dir).iterdir()) == [] if _visuals_dir(project_dir).is_dir() else True
