"""Testes de visuals.layout: set_page_layout reposiciona os visuais
existentes de uma página, reescrevendo só `position` em cada
visual.json.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from errors import PageNotFoundError
from visuals import layout


@pytest.fixture
def page_with_visuals(tmp_path: Path):
    """Monta um projeto com uma página e N visuais (cards + 1 gráfico),
    devolvendo (project_root, page_dir, visuals_dir)."""

    def _make(visual_specs: list[tuple[str, str]]):
        # visual_specs: lista de (nome_da_pasta, visualType)
        root = tmp_path / "Proj"
        report_dir = root / "Proj.Report"
        page_dir = report_dir / "definition" / "pages" / "Pagina1"
        visuals_dir = page_dir / "visuals"
        visuals_dir.mkdir(parents=True)
        (page_dir / "page.json").write_text(
            json.dumps({"name": "Pagina1", "displayName": "Pagina1", "width": 1280, "height": 720}),
            encoding="utf-8",
        )
        for name, visual_type in visual_specs:
            vdir = visuals_dir / name
            vdir.mkdir()
            (vdir / "visual.json").write_text(
                json.dumps(
                    {
                        "name": name,
                        "position": {"x": 0, "y": 0, "width": 1, "height": 1, "z": 0, "tabOrder": 0},
                        "visual": {"visualType": visual_type, "query": {"queryState": {}}},
                    }
                ),
                encoding="utf-8",
            )
        return root, page_dir, visuals_dir

    return _make


def _read_positions(visuals_dir: Path) -> dict[str, dict]:
    return {
        d.name: json.loads((d / "visual.json").read_text(encoding="utf-8"))["position"]
        for d in visuals_dir.iterdir()
        if d.is_dir()
    }


def test_raises_when_page_does_not_exist(tmp_path: Path):
    root = tmp_path / "Proj"
    (root / "Proj.Report" / "definition" / "pages").mkdir(parents=True)

    with pytest.raises(PageNotFoundError):
        layout.set_page_layout(pbip_path=str(root), page_name="Fantasma", layout="grid")


def test_grid_layout_keeps_every_visual_within_page_bounds(page_with_visuals):
    root, page_dir, visuals_dir = page_with_visuals(
        [("v1", "card"), ("v2", "clusteredColumnChart"), ("v3", "lineChart"), ("v4", "card")]
    )

    result = layout.set_page_layout(pbip_path=str(root), page_name="Pagina1", layout="grid")

    assert result["visual_count"] == 4
    positions = _read_positions(visuals_dir)
    assert len(positions) == 4
    for pos in positions.values():
        assert pos["x"] >= 0
        assert pos["y"] >= 0
        assert pos["x"] + pos["width"] <= 1280
        assert pos["y"] + pos["height"] <= 720
        assert pos["width"] > 0
        assert pos["height"] > 0


def test_grid_layout_does_not_overlap(page_with_visuals):
    root, page_dir, visuals_dir = page_with_visuals(
        [("v1", "card"), ("v2", "card"), ("v3", "card"), ("v4", "card")]
    )

    layout.set_page_layout(pbip_path=str(root), page_name="Pagina1", layout="grid")

    positions = list(_read_positions(visuals_dir).values())
    for i, a in enumerate(positions):
        for b in positions[i + 1 :]:
            overlap_x = a["x"] < b["x"] + b["width"] and b["x"] < a["x"] + a["width"]
            overlap_y = a["y"] < b["y"] + b["height"] and b["y"] < a["y"] + a["height"]
            assert not (overlap_x and overlap_y)


def test_kpi_row_puts_cards_on_top_row(page_with_visuals):
    root, page_dir, visuals_dir = page_with_visuals(
        [("chart1", "clusteredColumnChart"), ("card1", "card"), ("card2", "card")]
    )

    layout.set_page_layout(pbip_path=str(root), page_name="Pagina1", layout="kpi_row")

    positions = _read_positions(visuals_dir)
    assert positions["card1"]["y"] == positions["card2"]["y"]
    card_bottom = positions["card1"]["y"] + positions["card1"]["height"]
    assert positions["chart1"]["y"] >= card_bottom


def test_kpi_row_with_no_cards_still_lays_out_grid_below(page_with_visuals):
    root, page_dir, visuals_dir = page_with_visuals(
        [("chart1", "clusteredColumnChart"), ("chart2", "lineChart")]
    )

    result = layout.set_page_layout(pbip_path=str(root), page_name="Pagina1", layout="kpi_row")

    assert result["visual_count"] == 2
    positions = _read_positions(visuals_dir)
    assert len(positions) == 2


def test_layout_preserves_visual_type_and_name(page_with_visuals):
    root, page_dir, visuals_dir = page_with_visuals([("v1", "card")])

    layout.set_page_layout(pbip_path=str(root), page_name="Pagina1", layout="grid")

    data = json.loads((visuals_dir / "v1" / "visual.json").read_text(encoding="utf-8"))
    assert data["name"] == "v1"
    assert data["visual"]["visualType"] == "card"


def test_page_with_no_visuals_is_a_noop(page_with_visuals):
    root, page_dir, visuals_dir = page_with_visuals([])

    result = layout.set_page_layout(pbip_path=str(root), page_name="Pagina1", layout="grid")

    assert result["visual_count"] == 0


# --- top / keep_fixed: reservar a faixa do título ----------------------------


def test_top_starts_grid_below_the_reserved_band(page_with_visuals):
    root, _, visuals_dir = page_with_visuals([("v1", "clusteredColumnChart"), ("v2", "lineChart")])

    layout.set_page_layout(pbip_path=str(root), page_name="Pagina1", layout="grid", top=70)

    for pos in _read_positions(visuals_dir).values():
        assert pos["y"] >= 70
        assert pos["y"] + pos["height"] <= 720


def test_keep_fixed_visual_is_not_moved(page_with_visuals):
    root, _, visuals_dir = page_with_visuals(
        [("titulo", "textbox"), ("v1", "card"), ("v2", "lineChart")]
    )

    result = layout.set_page_layout(
        pbip_path=str(root), page_name="Pagina1", layout="kpi_row", top=64, keep_fixed=["titulo"]
    )

    positions = _read_positions(visuals_dir)
    assert positions["titulo"] == {"x": 0, "y": 0, "width": 1, "height": 1, "z": 0, "tabOrder": 0}
    assert positions["v1"]["y"] == 64
    assert positions["v2"]["y"] > positions["v1"]["y"] + positions["v1"]["height"]
    assert positions["v2"]["y"] + positions["v2"]["height"] <= 720
    assert result["visual_count"] == 2


def test_default_top_is_unchanged(page_with_visuals):
    """Sem `top`, o layout continua começando na margem (8) -- mesmo
    comportamento de antes."""
    root, _, visuals_dir = page_with_visuals([("v1", "lineChart")])

    layout.set_page_layout(pbip_path=str(root), page_name="Pagina1", layout="grid")

    assert _read_positions(visuals_dir)["v1"]["y"] == 8


def test_keep_fixed_unknown_visual_is_rejected(page_with_visuals):
    from errors import VisualNotFoundError

    root, _, _ = page_with_visuals([("v1", "lineChart")])

    with pytest.raises(VisualNotFoundError):
        layout.set_page_layout(pbip_path=str(root), page_name="Pagina1", layout="grid", keep_fixed=["nao_existe"])


@pytest.mark.parametrize("top", [-1, 720, 900])
def test_top_outside_page_is_rejected(page_with_visuals, top):
    from errors import InvalidLayoutError

    root, _, _ = page_with_visuals([("v1", "lineChart")])

    with pytest.raises(InvalidLayoutError):
        layout.set_page_layout(pbip_path=str(root), page_name="Pagina1", layout="grid", top=top)


def test_kpi_row_treats_card_visual_as_card(page_with_visuals):
    """cardVisual (cartao atual, recomendado pela doc oficial) vai pra
    faixa de KPI igual ao card legado."""
    root, _, visuals_dir = page_with_visuals([("v1", "cardVisual"), ("v2", "lineChart")])

    layout.set_page_layout(pbip_path=str(root), page_name="Pagina1", layout="kpi_row")

    positions = _read_positions(visuals_dir)
    assert positions["v1"]["y"] == 8
    assert positions["v2"]["y"] > positions["v1"]["y"] + positions["v1"]["height"]
