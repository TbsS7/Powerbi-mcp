"""Testes de set_page_background (visuals.formatting).

Fonte: doc oficial de autoria PBIR, page-formatting.md
(microsoft/skills-for-fabric) -- `page.json -> objects.background`
(tela) e `objects.outspace` (papel de parede), cada um um array com uma
entrada `{"properties": {"color": {"solid": {"color": {"expr":
{"Literal": {"Value": "'#hex'"}}}}}, "transparency": {"expr":
{"Literal": {"Value": "0D"}}}}}` -- SEM `show` (o schema recusa). Todo
page.json escrito é validado contra o schema oficial page/1.4.0.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from errors import InvalidVisualFormattingError, PageNotFoundError
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


def _page_json(project_dir: Path) -> dict:
    path = project_dir / "Vendas.Report" / "definition" / "pages" / "Pagina1" / "page.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _color(hex_color: str) -> dict:
    return {"solid": {"color": {"expr": {"Literal": {"Value": f"'{hex_color}'"}}}}}


def test_color_writes_background_with_zero_transparency(project_dir: Path):
    """Transparência padrão da tela no Desktop é 100% -- só a cor não
    apareceria; por isso passar a cor grava transparência 0."""
    result = formatting.set_page_background(
        pbip_path=str(project_dir), page_name="Pagina1", color="#F3F2F1"
    )

    page = _page_json(project_dir)
    assert page["objects"]["background"] == [
        {"properties": {
            "color": _color("#F3F2F1"),
            "transparency": {"expr": {"Literal": {"Value": "0D"}}},
        }}
    ]
    assert "outspace" not in page["objects"]
    validate_page_json(page)
    assert result["page_name"] == "Pagina1"
    assert result["changed"] == ["background.color", "background.transparency"]


def test_explicit_transparency_is_kept(project_dir: Path):
    formatting.set_page_background(
        pbip_path=str(project_dir), page_name="Pagina1", color="#FFFFFF", transparency=30
    )

    props = _page_json(project_dir)["objects"]["background"][0]["properties"]
    assert props["transparency"] == {"expr": {"Literal": {"Value": "30D"}}}


def test_wallpaper_writes_outspace(project_dir: Path):
    formatting.set_page_background(
        pbip_path=str(project_dir), page_name="Pagina1",
        wallpaper_color="#0D1117", wallpaper_transparency=10,
    )

    page = _page_json(project_dir)
    assert page["objects"]["outspace"] == [
        {"properties": {
            "color": _color("#0D1117"),
            "transparency": {"expr": {"Literal": {"Value": "10D"}}},
        }}
    ]
    assert "background" not in page["objects"]
    validate_page_json(page)


def test_updates_existing_entry_and_preserves_rest_of_page(project_dir: Path):
    path = project_dir / "Vendas.Report" / "definition" / "pages" / "Pagina1" / "page.json"
    page = _page_json(project_dir)
    page["filterConfig"] = {"filters": []}
    page["objects"] = {"outspacePane": [{"properties": {"width": {"expr": {"Literal": {"Value": "200L"}}}}}]}
    path.write_text(json.dumps(page), encoding="utf-8")

    formatting.set_page_background(pbip_path=str(project_dir), page_name="Pagina1", color="#FFFFFF")
    formatting.set_page_background(pbip_path=str(project_dir), page_name="Pagina1", color="#EEEEEE")

    page = _page_json(project_dir)
    assert page["filterConfig"] == {"filters": []}
    assert "outspacePane" in page["objects"]
    assert len(page["objects"]["background"]) == 1
    assert page["objects"]["background"][0]["properties"]["color"] == _color("#EEEEEE")
    assert page["displayName"] == "Pagina1"
    validate_page_json(page)


def test_transparency_alone_does_not_touch_color(project_dir: Path):
    formatting.set_page_background(pbip_path=str(project_dir), page_name="Pagina1", color="#FFFFFF")
    formatting.set_page_background(pbip_path=str(project_dir), page_name="Pagina1", transparency=50)

    props = _page_json(project_dir)["objects"]["background"][0]["properties"]
    assert props["color"] == _color("#FFFFFF")
    assert props["transparency"] == {"expr": {"Literal": {"Value": "50D"}}}


@pytest.mark.parametrize("kwargs", [
    {"color": "F3F2F1"},
    {"color": "#GGGGGG"},
    {"wallpaper_color": "azul"},
    {"transparency": -1},
    {"transparency": 101},
    {"wallpaper_transparency": 150},
])
def test_invalid_values_are_rejected_without_writing(project_dir: Path, kwargs: dict):
    before = _page_json(project_dir)

    with pytest.raises(InvalidVisualFormattingError):
        formatting.set_page_background(pbip_path=str(project_dir), page_name="Pagina1", **kwargs)

    assert _page_json(project_dir) == before


def test_no_parameter_is_rejected(project_dir: Path):
    with pytest.raises(InvalidVisualFormattingError):
        formatting.set_page_background(pbip_path=str(project_dir), page_name="Pagina1")


def test_unknown_page_is_rejected(project_dir: Path):
    with pytest.raises(PageNotFoundError):
        formatting.set_page_background(pbip_path=str(project_dir), page_name="NaoExiste", color="#FFFFFF")
