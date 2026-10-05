"""Testes de set_textbox_style e set_visual_container_style
(visuals.formatting).

Fontes: doc oficial de autoria PBIR, textbox.md (microsoft/
skills-for-fabric) -- exemplo de título com `textStyle` {fontFamily,
fontSize "24px"/"20pt", fontWeight "bold", color "#hex"} e
`horizontalTextAlignment` por parágrafo, e `visualContainerObjects`
background/border no mesmo exemplo; formatting.md (tabela VCO:
background = show/color/transparency, border = show/color/radius/width);
schema oficial de tema (fontStyle italic, textDecoration underline,
fontSize 8-60). Todo visual.json escrito é validado contra o schema
oficial visualContainer/2.7.0.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from errors import InvalidVisualFormattingError
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
    fake.add_table(TableInfo(name="Vendas", columns=(ColumnInfo(name="Valor", data_type="Double"),)))
    fake.create_measure("Vendas", "Total Vendas", "SUM(Vendas[Valor])", "#,##0.00")
    connection.set_active_runtime(fake)
    return fake


def _textbox(project_dir: Path, text: str = "Dashboard de Vendas\nAtualizado mensalmente") -> str:
    return visual_writer.add_visual(
        pbip_path=str(project_dir), page_name="Pagina1", visual_type="textbox",
        x=0, y=0, width=800, height=80, text=text,
    )["visual_name"]


def _visual(project_dir: Path, name: str) -> dict:
    path = project_dir / "Vendas.Report" / "definition" / "pages" / "Pagina1" / "visuals" / name / "visual.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    validate_visual_json(data)
    return data


def _paragraphs(project_dir: Path, name: str) -> list[dict]:
    return _visual(project_dir, name)["visual"]["objects"]["general"][0]["properties"]["paragraphs"]


def _lit(value: str) -> dict:
    return {"expr": {"Literal": {"Value": value}}}


# --- set_textbox_style ---------------------------------------------------------------


def test_textbox_style_applies_to_all_lines(project_dir: Path):
    name = _textbox(project_dir)

    result = formatting.set_textbox_style(
        pbip_path=str(project_dir), page_name="Pagina1", visual_name=name,
        font_size=24, bold=True, color="#1F3864", alignment="center", font_family="Segoe UI Semibold",
    )

    for paragraph in _paragraphs(project_dir, name):
        assert paragraph["horizontalTextAlignment"] == "center"
        style = paragraph["textRuns"][0]["textStyle"]
        assert style["fontSize"] == "24pt"
        assert style["fontWeight"] == "bold"
        assert style["color"] == "#1F3864"
        assert style["fontFamily"] == "Segoe UI Semibold"
    assert result["lines"] == [1, 2]


def test_textbox_style_only_one_line(project_dir: Path):
    name = _textbox(project_dir)
    formatting.set_textbox_style(
        pbip_path=str(project_dir), page_name="Pagina1", visual_name=name, font_size=28, bold=True, line=1,
    )
    formatting.set_textbox_style(
        pbip_path=str(project_dir), page_name="Pagina1", visual_name=name, font_size=12, italic=True, line=2,
    )

    title, subtitle = _paragraphs(project_dir, name)
    assert title["textRuns"][0]["textStyle"]["fontSize"] == "28pt"
    assert title["textRuns"][0]["textStyle"]["fontWeight"] == "bold"
    assert "fontStyle" not in title["textRuns"][0]["textStyle"]
    assert subtitle["textRuns"][0]["textStyle"]["fontSize"] == "12pt"
    assert subtitle["textRuns"][0]["textStyle"]["fontStyle"] == "italic"
    # o texto em si não muda
    assert title["textRuns"][0]["value"] == "Dashboard de Vendas"
    assert subtitle["textRuns"][0]["value"] == "Atualizado mensalmente"


def test_textbox_style_can_turn_bold_and_underline_off(project_dir: Path):
    name = _textbox(project_dir, "Título")
    formatting.set_textbox_style(
        pbip_path=str(project_dir), page_name="Pagina1", visual_name=name, bold=True, underline=True,
    )
    formatting.set_textbox_style(
        pbip_path=str(project_dir), page_name="Pagina1", visual_name=name, bold=False, underline=False,
    )
    style = _paragraphs(project_dir, name)[0]["textRuns"][0]["textStyle"]
    assert style["fontWeight"] == "normal"
    assert "textDecoration" not in style


def test_textbox_style_keeps_other_properties(project_dir: Path):
    name = _textbox(project_dir, "Título")
    formatting.set_textbox_style(pbip_path=str(project_dir), page_name="Pagina1", visual_name=name, color="#FF0000")
    style = _paragraphs(project_dir, name)[0]["textRuns"][0]["textStyle"]
    assert style["fontSize"] == "12pt"  # o padrão de add_visual continua
    assert style["color"] == "#FF0000"


@pytest.mark.parametrize(
    "kwargs",
    [
        {"font_size": 100},
        {"font_size": 4},
        {"color": "azul"},
        {"alignment": "justify"},
        {"line": 3},
        {},
    ],
)
def test_textbox_style_rejects_invalid_input(project_dir: Path, kwargs):
    name = _textbox(project_dir)
    with pytest.raises(InvalidVisualFormattingError):
        formatting.set_textbox_style(pbip_path=str(project_dir), page_name="Pagina1", visual_name=name, **kwargs)


def test_textbox_style_rejects_non_textbox(project_dir: Path):
    card = visual_writer.add_visual(
        pbip_path=str(project_dir), page_name="Pagina1", visual_type="card",
        x=0, y=0, width=100, height=50, fields={"Values": ["Vendas.Total Vendas"]},
    )["visual_name"]
    with pytest.raises(InvalidVisualFormattingError, match="textbox"):
        formatting.set_textbox_style(pbip_path=str(project_dir), page_name="Pagina1", visual_name=card, bold=True)


# --- set_visual_container_style -----------------------------------------------------


def test_container_style_writes_background_and_border(project_dir: Path):
    name = _textbox(project_dir, "Título")

    formatting.set_visual_container_style(
        pbip_path=str(project_dir), page_name="Pagina1", visual_name=name,
        background_color="#1F3864", background_transparency=0,
        border_show=True, border_color="#0B1F3A", border_width=2, border_radius=8,
    )

    vco = _visual(project_dir, name)["visual"]["visualContainerObjects"]
    background = vco["background"][0]["properties"]
    assert background["show"] == _lit("true")  # cor de fundo liga o fundo
    assert background["color"] == {"solid": {"color": _lit("'#1F3864'")}}
    assert background["transparency"] == _lit("0D")
    border = vco["border"][0]["properties"]
    assert border["show"] == _lit("true")
    assert border["color"] == {"solid": {"color": _lit("'#0B1F3A'")}}
    assert border["width"] == _lit("2D")
    assert border["radius"] == _lit("8D")


def test_container_style_works_on_any_visual(project_dir: Path):
    card = visual_writer.add_visual(
        pbip_path=str(project_dir), page_name="Pagina1", visual_type="card",
        x=0, y=0, width=100, height=50, fields={"Values": ["Vendas.Total Vendas"]},
    )["visual_name"]
    formatting.set_visual_container_style(
        pbip_path=str(project_dir), page_name="Pagina1", visual_name=card, border_show=False, background_show=False,
    )
    vco = _visual(project_dir, card)["visual"]["visualContainerObjects"]
    assert vco["border"][0]["properties"]["show"] == _lit("false")
    assert vco["background"][0]["properties"]["show"] == _lit("false")


def test_container_style_preserves_title(project_dir: Path):
    card = visual_writer.add_visual(
        pbip_path=str(project_dir), page_name="Pagina1", visual_type="card",
        x=0, y=0, width=100, height=50, fields={"Values": ["Vendas.Total Vendas"]},
    )["visual_name"]
    visual_writer.set_visual_title(pbip_path=str(project_dir), page_name="Pagina1", visual_name=card, text="Vendas")
    formatting.set_visual_container_style(
        pbip_path=str(project_dir), page_name="Pagina1", visual_name=card, background_color="#FFFFFF",
    )
    vco = _visual(project_dir, card)["visual"]["visualContainerObjects"]
    assert vco["title"][0]["properties"]["text"] == _lit("'Vendas'")


@pytest.mark.parametrize(
    "kwargs",
    [
        {"background_transparency": 150},
        {"background_color": "#12"},
        {"border_width": -1},
        {},
    ],
)
def test_container_style_rejects_invalid_input(project_dir: Path, kwargs):
    name = _textbox(project_dir, "Título")
    with pytest.raises(InvalidVisualFormattingError):
        formatting.set_visual_container_style(
            pbip_path=str(project_dir), page_name="Pagina1", visual_name=name, **kwargs,
        )
