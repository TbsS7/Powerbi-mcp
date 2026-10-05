"""Testes de texto alternativo (set_visual_alt_text), página de tooltip
(create_report_page(tooltip=True)) e ligação visual -> tooltip
(set_visual_tooltip_page).

Fontes:
- Texto alternativo: doc oficial conditional-formatting.md
  (skills-for-fabric) -- `general.altText` "describes the visual and its
  meaningful insights for accessibility"; schema oficial
  visualConfiguration/2.3.0 (`VisualContainerGeneralFormattingObjects`
  tem `altText`).
- Tooltip: schemas oficiais page/1.4.0 (`type: "Tooltip"`) e
  visualConfiguration/2.3.0 (`visualTooltip.section`), e comparação com o
  que o Power BI Desktop gerou pela UI (2026-09-29): a página de tooltip
  tem só `type: "Tooltip"`, `displayOption: "ActualSize"` e 400x300 (sem
  `pageBinding`), e o visual ligado tem só `visualTooltip.section` = nome
  da página (sem `type`/`show`).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from errors import InvalidVisualFormattingError, PageNotFoundError
from modeling import connection
from modeling.metadata import ColumnInfo, TableInfo
from tests.fakes.fake_tom import FakeTomRuntime
from tests.schema_validation import validate_page_json, validate_visual_json
from visuals import formatting, page_writer, visual_writer


@pytest.fixture
def project_dir(tmp_path: Path) -> Path:
    root = tmp_path / "VendasProject"
    root.mkdir()
    (root / "Vendas.pbip").write_text("{}", encoding="utf-8")
    (root / "Vendas.Report").mkdir()
    page_writer.create_report_page(pbip_path=str(root), page_name="Pagina1")
    return root


@pytest.fixture(autouse=True)
def fake_runtime() -> FakeTomRuntime:
    fake = FakeTomRuntime(database_name="Vendas")
    fake.add_table(TableInfo(name="Vendas", columns=(ColumnInfo(name="Regiao", data_type="String"),)))
    fake.create_measure("Vendas", "Total Vendas", "SUM(Vendas[Valor])", "#,##0.00")
    connection.set_active_runtime(fake)
    return fake


def _chart(project_dir: Path, page_name: str = "Pagina1") -> str:
    return visual_writer.add_visual(
        pbip_path=str(project_dir), page_name=page_name, visual_type="clusteredColumnChart",
        x=0, y=0, width=400, height=300,
        fields={"Category": ["Vendas.Regiao"], "Y": ["Vendas.Total Vendas"]},
    )["visual_name"]


def _pages_dir(project_dir: Path) -> Path:
    return project_dir / "Vendas.Report" / "definition" / "pages"


def _visual(project_dir: Path, name: str, page_name: str = "Pagina1") -> dict:
    data = json.loads((_pages_dir(project_dir) / page_name / "visuals" / name / "visual.json").read_text(encoding="utf-8"))
    validate_visual_json(data)
    return data


def _lit(value: str) -> dict:
    return {"expr": {"Literal": {"Value": value}}}


# --- texto alternativo -------------------------------------------------------------


def test_alt_text_is_written_to_general(project_dir: Path):
    name = _chart(project_dir)

    result = formatting.set_visual_alt_text(
        pbip_path=str(project_dir), page_name="Pagina1", visual_name=name,
        text="Vendas por região; a região Sul lidera",
    )

    vco = _visual(project_dir, name)["visual"]["visualContainerObjects"]
    assert vco["general"] == [{"properties": {"altText": _lit("'Vendas por região; a região Sul lidera'")}}]
    assert result["alt_text"] == "Vendas por região; a região Sul lidera"


def test_alt_text_escapes_single_quote_and_preserves_other_vco(project_dir: Path):
    name = _chart(project_dir)
    formatting.set_visual_container_style(
        pbip_path=str(project_dir), page_name="Pagina1", visual_name=name, background_color="#FFFFFF"
    )

    formatting.set_visual_alt_text(pbip_path=str(project_dir), page_name="Pagina1", visual_name=name, text="D'Ávila")

    vco = _visual(project_dir, name)["visual"]["visualContainerObjects"]
    assert vco["general"][0]["properties"]["altText"] == _lit("'D''Ávila'")
    assert "background" in vco


def test_empty_alt_text_removes_it(project_dir: Path):
    name = _chart(project_dir)
    formatting.set_visual_alt_text(pbip_path=str(project_dir), page_name="Pagina1", visual_name=name, text="x")

    formatting.set_visual_alt_text(pbip_path=str(project_dir), page_name="Pagina1", visual_name=name, text="")

    vco = _visual(project_dir, name)["visual"].get("visualContainerObjects", {})
    assert "general" not in vco


# --- página de tooltip -------------------------------------------------------------


def test_create_tooltip_page_matches_desktop_output(project_dir: Path):
    result = page_writer.create_report_page(
        pbip_path=str(project_dir), page_name="DicaVendas", display_name="Dica de vendas", tooltip=True
    )

    page = json.loads((_pages_dir(project_dir) / "DicaVendas" / "page.json").read_text(encoding="utf-8"))
    assert page["type"] == "Tooltip"
    assert page["displayOption"] == "ActualSize"
    assert (page["width"], page["height"]) == (400, 300)
    assert "pageBinding" not in page
    validate_page_json(page)
    assert result["tooltip"] is True


def test_normal_page_has_no_type(project_dir: Path):
    page = json.loads((_pages_dir(project_dir) / "Pagina1" / "page.json").read_text(encoding="utf-8"))
    assert "type" not in page
    assert page["displayOption"] == "FitToPage"


# --- ligar visual -> página de tooltip ---------------------------------------------


def test_link_visual_to_tooltip_page(project_dir: Path):
    page_writer.create_report_page(pbip_path=str(project_dir), page_name="DicaVendas", tooltip=True)
    name = _chart(project_dir)

    result = formatting.set_visual_tooltip_page(
        pbip_path=str(project_dir), page_name="Pagina1", visual_name=name, tooltip_page="DicaVendas"
    )

    vco = _visual(project_dir, name)["visual"]["visualContainerObjects"]
    assert vco["visualTooltip"] == [{"properties": {"section": _lit("'DicaVendas'")}}]
    assert result["tooltip_page"] == "DicaVendas"


def test_unlink_tooltip_page(project_dir: Path):
    page_writer.create_report_page(pbip_path=str(project_dir), page_name="DicaVendas", tooltip=True)
    name = _chart(project_dir)
    formatting.set_visual_tooltip_page(
        pbip_path=str(project_dir), page_name="Pagina1", visual_name=name, tooltip_page="DicaVendas"
    )

    formatting.set_visual_tooltip_page(pbip_path=str(project_dir), page_name="Pagina1", visual_name=name, tooltip_page=None)

    vco = _visual(project_dir, name)["visual"].get("visualContainerObjects", {})
    assert "visualTooltip" not in vco


def test_link_refuses_page_that_is_not_a_tooltip(project_dir: Path):
    page_writer.create_report_page(pbip_path=str(project_dir), page_name="Outra")
    name = _chart(project_dir)

    with pytest.raises(InvalidVisualFormattingError, match="tooltip"):
        formatting.set_visual_tooltip_page(
            pbip_path=str(project_dir), page_name="Pagina1", visual_name=name, tooltip_page="Outra"
        )


def test_link_refuses_missing_page(project_dir: Path):
    name = _chart(project_dir)

    with pytest.raises(PageNotFoundError):
        formatting.set_visual_tooltip_page(
            pbip_path=str(project_dir), page_name="Pagina1", visual_name=name, tooltip_page="NaoExiste"
        )
