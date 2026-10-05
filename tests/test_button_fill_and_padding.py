"""Cor de fundo de botão (add_navigation_button fill_color/corner_radius)
e espaçamento interno da moldura (set_visual_container_style padding).

Fontes: doc oficial button.md (microsoft/skills-for-fabric,
plugins/powerbi-authoring/.../authoring/button.md): `fill` em
"dual-entry" (show sem selector + fillColor com selector default) e o
"render contract" (background/border do container desligados,
shape.tileShape 'rectangleRounded' + roundEdge, icon.placement 'left').
Padding: schema oficial de tema 2.157, `commonCards.padding`
{top, bottom, left, right} (number). Achado ao vivo no dashboard
Cristallo (2026-10-03): botão com texto saiu com o azul padrão do tema e
o painel (i) ficou com o texto colado na borda.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from errors import InvalidVisualFormattingError, InvalidVisualRoleError
from modeling import connection
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
    (pages_dir / "Pagina1").mkdir(parents=True)
    (pages_dir / "Pagina1" / "page.json").write_text("{}", encoding="utf-8")
    (pages_dir / "pages.json").write_text("{}", encoding="utf-8")
    (report_dir / "definition" / "version.json").write_text("{}", encoding="utf-8")
    (report_dir / "definition" / "report.json").write_text("{}", encoding="utf-8")
    return root


@pytest.fixture(autouse=True)
def fake_runtime() -> FakeTomRuntime:
    fake = FakeTomRuntime(database_name="Vendas")
    connection.set_active_runtime(fake)
    return fake


def _lit(value: str) -> dict:
    return {"expr": {"Literal": {"Value": value}}}


def _visual(project_dir: Path, name: str) -> dict:
    path = project_dir / "Vendas.Report" / "definition" / "pages" / "Pagina1" / "visuals" / name / "visual.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    validate_visual_json(data)
    return data


def _button(project_dir: Path, **kwargs) -> str:
    return visual_writer.add_navigation_button(
        pbip_path=str(project_dir), page_name="Pagina1", x=0, y=0, width=80, height=30,
        target_type="page", target="Pagina1", text="Ver ›", **kwargs,
    )["visual_name"]


def test_button_fill_color_dual_entry_and_render_contract(project_dir: Path):
    name = _button(project_dir, fill_color="#2A2A2A", corner_radius=10)

    visual = _visual(project_dir, name)["visual"]
    assert visual["objects"]["fill"] == [
        {"properties": {"show": _lit("true")}},
        {"properties": {"fillColor": {"solid": {"color": _lit("'#2A2A2A'")}}}, "selector": {"id": "default"}},
    ]
    assert visual["objects"]["shape"] == [
        {"properties": {"tileShape": _lit("'rectangleRounded'"), "roundEdge": _lit("10L")}},
        {"properties": {"tileShape": _lit("'rectangleRounded'")}, "selector": {"id": "default"}},
    ]
    assert visual["objects"]["outline"] == [{"properties": {"show": _lit("false")}}]
    assert visual["visualContainerObjects"]["background"] == [{"properties": {"show": _lit("false")}}]
    assert visual["visualContainerObjects"]["border"] == [{"properties": {"show": _lit("false")}}]
    assert visual["objects"]["icon"][1] == {"properties": {"placement": _lit("'left'")}, "selector": {"id": "default"}}
    # texto continua lá
    assert visual["objects"]["text"][1]["properties"]["text"] == _lit("'Ver ›'")


def test_button_without_fill_color_keeps_previous_output(project_dir: Path):
    name = _button(project_dir)
    assert "fill" not in _visual(project_dir, name)["visual"]["objects"]


def test_button_fill_color_rejects_bad_hex_and_transparent_combo(project_dir: Path):
    with pytest.raises(InvalidVisualRoleError, match="fill_color"):
        _button(project_dir, fill_color="cinza")
    with pytest.raises(InvalidVisualRoleError, match="transparent"):
        _button(project_dir, fill_color="#2A2A2A", transparent=True)


def test_container_padding_all_sides(project_dir: Path):
    name = visual_writer.add_visual(
        pbip_path=str(project_dir), page_name="Pagina1", visual_type="textbox",
        x=0, y=0, width=300, height=100, text="Info",
    )["visual_name"]

    formatting.set_visual_container_style(
        pbip_path=str(project_dir), page_name="Pagina1", visual_name=name, background_color="#1C1C1C", padding=16,
    )

    vco = _visual(project_dir, name)["visual"]["visualContainerObjects"]
    assert vco["padding"] == [{"properties": {side: _lit("16D") for side in ("top", "bottom", "left", "right")}}]
    with pytest.raises(InvalidVisualFormattingError, match="padding"):
        formatting.set_visual_container_style(
            pbip_path=str(project_dir), page_name="Pagina1", visual_name=name, padding=-1,
        )
