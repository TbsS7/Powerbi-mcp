"""Testes de visuals.formatting: rótulos de dado, legenda e eixos.

Onde cada objeto fica no visual.json: doc oficial de autoria de PBIR
(skills-for-fabric, formatting.md / cartesian.md -- `visual.objects.
<objeto>` como array de `{properties, selector?}`). Quais propriedades e
valores valem por tipo de visual: visuals/formatting_spec.json, gerado do
schema oficial de tema. Todo visual.json escrito é validado contra o
schema oficial visualContainer/2.7.0.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from errors import InvalidVisualFormattingError, VisualNotFoundError
from modeling import connection
from modeling.metadata import ColumnInfo, TableInfo
from tests.fakes.fake_tom import FakeTomRuntime
from tests.schema_validation import validate_visual_json
from visuals import formatting, visual_writer


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
    fake.add_table(
        TableInfo(
            name="Vendas",
            columns=(ColumnInfo(name="Valor", data_type="Double"), ColumnInfo(name="Pais", data_type="String")),
        )
    )
    fake.create_measure("Vendas", "Total Vendas", "SUM(Vendas[Valor])", "#,##0.00")
    connection.set_active_runtime(fake)
    return fake


def _add(project_dir: Path, visual_type: str, fields: dict) -> str:
    return visual_writer.add_visual(
        pbip_path=str(project_dir), page_name="Pagina1", visual_type=visual_type,
        x=0, y=0, width=400, height=300, fields=fields,
    )["visual_name"]


def _column_chart(project_dir: Path) -> str:
    return _add(project_dir, "clusteredColumnChart", {"Category": ["Vendas.Pais"], "Y": ["Vendas.Total Vendas"]})


def _visual(project_dir: Path, name: str) -> dict:
    path = project_dir / "Vendas.Report" / "definition" / "pages" / "Pagina1" / "visuals" / name / "visual.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _props(project_dir: Path, name: str, object_name: str) -> dict:
    entries = _visual(project_dir, name)["visual"]["objects"][object_name]
    [base] = [e for e in entries if "selector" not in e]
    return base["properties"]


def _lit(value: str) -> dict:
    return {"expr": {"Literal": {"Value": value}}}


# --- rótulos de dado ------------------------------------------------------------


def test_data_labels_writes_properties_and_is_schema_valid(project_dir: Path):
    name = _column_chart(project_dir)

    result = formatting.set_visual_data_labels(
        pbip_path=str(project_dir), page_name="Pagina1", visual_name=name,
        show=True, position="OutsideEnd", display_units="millions", precision=1,
        font_size=11, color="#333333",
    )

    validate_visual_json(_visual(project_dir, name))
    props = _props(project_dir, name, "labels")
    assert props["show"] == _lit("true")
    assert props["labelPosition"] == _lit("'OutsideEnd'")
    assert props["labelDisplayUnits"] == _lit("1000000D")
    assert props["labelPrecision"] == _lit("1L")
    assert props["fontSize"] == _lit("11D")
    assert props["color"] == {"solid": {"color": _lit("'#333333'")}}
    assert result["object"] == "labels"


def test_only_given_properties_change(project_dir: Path):
    name = _column_chart(project_dir)
    formatting.set_visual_data_labels(
        pbip_path=str(project_dir), page_name="Pagina1", visual_name=name, show=True, font_size=11,
    )
    formatting.set_visual_data_labels(
        pbip_path=str(project_dir), page_name="Pagina1", visual_name=name, font_size=14,
    )
    props = _props(project_dir, name, "labels")
    assert props["show"] == _lit("true")
    assert props["fontSize"] == _lit("14D")


def test_preserves_entries_with_selector(project_dir: Path):
    # entrada por série (selector de metadata, doc oficial) não pode sumir
    name = _column_chart(project_dir)
    path = project_dir / "Vendas.Report" / "definition" / "pages" / "Pagina1" / "visuals" / name / "visual.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    per_series = {"properties": {"show": _lit("false")}, "selector": {"metadata": "Vendas.Total Vendas"}}
    data["visual"]["objects"] = {"labels": [per_series]}
    path.write_text(json.dumps(data), encoding="utf-8")

    formatting.set_visual_data_labels(
        pbip_path=str(project_dir), page_name="Pagina1", visual_name=name, show=True,
    )

    entries = _visual(project_dir, name)["visual"]["objects"]["labels"]
    assert per_series in entries
    assert _props(project_dir, name, "labels")["show"] == _lit("true")


def test_card_labels_have_no_show(project_dir: Path):
    # schema oficial: no cartão, labels não tem "show" (o valor sempre aparece)
    name = _add(project_dir, "card", {"Values": ["Vendas.Total Vendas"]})
    with pytest.raises(InvalidVisualFormattingError, match="show"):
        formatting.set_visual_data_labels(
            pbip_path=str(project_dir), page_name="Pagina1", visual_name=name, show=True,
        )
    formatting.set_visual_data_labels(
        pbip_path=str(project_dir), page_name="Pagina1", visual_name=name, font_size=20,
    )
    assert _props(project_dir, name, "labels")["fontSize"] == _lit("20D")


def test_rejects_invalid_label_position(project_dir: Path):
    name = _column_chart(project_dir)
    with pytest.raises(InvalidVisualFormattingError, match="OutsideEnd"):
        formatting.set_visual_data_labels(
            pbip_path=str(project_dir), page_name="Pagina1", visual_name=name, position="Fora",
        )


def test_rejects_unknown_display_units(project_dir: Path):
    name = _column_chart(project_dir)
    with pytest.raises(InvalidVisualFormattingError):
        formatting.set_visual_data_labels(
            pbip_path=str(project_dir), page_name="Pagina1", visual_name=name, display_units="dúzias",
        )


def test_rejects_font_size_out_of_range(project_dir: Path):
    name = _column_chart(project_dir)
    with pytest.raises(InvalidVisualFormattingError, match="8"):
        formatting.set_visual_data_labels(
            pbip_path=str(project_dir), page_name="Pagina1", visual_name=name, font_size=100,
        )


def test_rejects_bad_color(project_dir: Path):
    name = _column_chart(project_dir)
    with pytest.raises(InvalidVisualFormattingError):
        formatting.set_visual_data_labels(
            pbip_path=str(project_dir), page_name="Pagina1", visual_name=name, color="azul",
        )


def test_requires_at_least_one_property(project_dir: Path):
    name = _column_chart(project_dir)
    with pytest.raises(InvalidVisualFormattingError):
        formatting.set_visual_data_labels(pbip_path=str(project_dir), page_name="Pagina1", visual_name=name)


# --- legenda ---------------------------------------------------------------------


def test_legend_writes_properties(project_dir: Path):
    name = _column_chart(project_dir)
    formatting.set_visual_legend(
        pbip_path=str(project_dir), page_name="Pagina1", visual_name=name,
        show=True, position="TopCenter", show_title=True, title="Vendas por país", font_size=10,
    )
    validate_visual_json(_visual(project_dir, name))
    props = _props(project_dir, name, "legend")
    assert props["position"] == _lit("'TopCenter'")
    assert props["titleText"] == _lit("'Vendas por país'")
    assert props["showTitle"] == _lit("true")


def test_legend_escapes_single_quote_in_title(project_dir: Path):
    name = _column_chart(project_dir)
    formatting.set_visual_legend(
        pbip_path=str(project_dir), page_name="Pagina1", visual_name=name, title="D'Ávila",
    )
    assert _props(project_dir, name, "legend")["titleText"] == _lit("'D''Ávila'")


def test_legend_not_supported_on_card(project_dir: Path):
    name = _add(project_dir, "card", {"Values": ["Vendas.Total Vendas"]})
    with pytest.raises(InvalidVisualFormattingError, match="card"):
        formatting.set_visual_legend(
            pbip_path=str(project_dir), page_name="Pagina1", visual_name=name, show=False,
        )


def test_formatting_not_supported_on_table(project_dir: Path):
    name = _add(project_dir, "tableEx", {"Values": ["Vendas.Pais", "Vendas.Total Vendas"]})
    with pytest.raises(InvalidVisualFormattingError, match="tableEx"):
        formatting.set_visual_data_labels(
            pbip_path=str(project_dir), page_name="Pagina1", visual_name=name, font_size=10,
        )


# --- eixos -----------------------------------------------------------------------


def test_value_axis_writes_properties(project_dir: Path):
    name = _column_chart(project_dir)
    formatting.set_visual_axis(
        pbip_path=str(project_dir), page_name="Pagina1", visual_name=name, axis="value",
        show=True, show_title=True, title="Vendas (R$)", start=0, end=150000000,
        display_units="millions", gridlines=False, font_size=9,
    )
    validate_visual_json(_visual(project_dir, name))
    props = _props(project_dir, name, "valueAxis")
    assert props["start"] == _lit("0D")
    assert props["end"] == _lit("150000000D")
    assert props["labelDisplayUnits"] == _lit("1000000D")
    assert props["gridlineShow"] == _lit("false")
    assert props["titleText"] == _lit("'Vendas (R$)'")


def test_category_axis_writes_properties(project_dir: Path):
    name = _column_chart(project_dir)
    formatting.set_visual_axis(
        pbip_path=str(project_dir), page_name="Pagina1", visual_name=name, axis="category",
        show_title=False, invert=True,
    )
    props = _props(project_dir, name, "categoryAxis")
    assert props["showAxisTitle"] == _lit("false")
    assert props["invertAxis"] == _lit("true")


def test_axis_rejects_unknown_axis(project_dir: Path):
    name = _column_chart(project_dir)
    with pytest.raises(InvalidVisualFormattingError):
        formatting.set_visual_axis(
            pbip_path=str(project_dir), page_name="Pagina1", visual_name=name, axis="z", show=True,
        )


def test_axis_not_supported_on_donut(project_dir: Path):
    name = _add(project_dir, "donutChart", {"Category": ["Vendas.Pais"], "Y": ["Vendas.Total Vendas"]})
    with pytest.raises(InvalidVisualFormattingError, match="donutChart"):
        formatting.set_visual_axis(
            pbip_path=str(project_dir), page_name="Pagina1", visual_name=name, axis="value", show=False,
        )


def test_unknown_visual_raises(project_dir: Path):
    with pytest.raises(VisualNotFoundError):
        formatting.set_visual_legend(
            pbip_path=str(project_dir), page_name="Pagina1", visual_name="naoexiste", show=False,
        )
