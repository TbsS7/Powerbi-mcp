"""Testes de set_card_style (visuals.formatting) -- os dois tipos de
cartão, cada um com os nomes certos:

- `cardVisual` (cartão atual): doc oficial card.md / card-part-03.md
  (microsoft/skills-for-fabric) -- objetos `value` e `label`, SEMPRE com
  `selector: {"id": "default"}` (sem ele, a doc avisa que a formatação
  é ignorada em silêncio); `label.text` troca o texto de baixo.
  Propriedades conferidas no schema oficial de tema
  (`visual-cardVisual`: `fontColor`, não `color`).
- `card` (legado, obsoleto segundo a doc): schema oficial de tema
  (`visual-card`) -- `labels` (valor) e `categoryLabels` (texto de baixo),
  entrada base sem selector (mesmo padrão de set_visual_data_labels).

Todo visual.json escrito é validado contra o schema oficial
visualContainer/2.7.0.
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


def _add(project_dir: Path, visual_type: str) -> str:
    role = {"card": "Values", "cardVisual": "Data", "clusteredColumnChart": "Y"}[visual_type]
    fields = {role: ["Vendas.Total Vendas"]}
    if visual_type == "clusteredColumnChart":
        fields["Category"] = ["Vendas.Valor"]
    return visual_writer.add_visual(
        pbip_path=str(project_dir), page_name="Pagina1", visual_type=visual_type,
        x=0, y=0, width=300, height=120, fields=fields,
    )["visual_name"]


def _visual(project_dir: Path, name: str) -> dict:
    path = project_dir / "Vendas.Report" / "definition" / "pages" / "Pagina1" / "visuals" / name / "visual.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    validate_visual_json(data)
    return data


def _lit(value: str) -> dict:
    return {"expr": {"Literal": {"Value": value}}}


def _color(hex_color: str) -> dict:
    return {"solid": {"color": _lit(f"'{hex_color}'")}}


_DEFAULT = {"id": "default"}


def test_card_visual_value_and_label_use_default_selector(project_dir: Path):
    name = _add(project_dir, "cardVisual")

    result = formatting.set_card_style(
        pbip_path=str(project_dir), page_name="Pagina1", visual_name=name,
        value_font_size=28, value_color="#1F3864", value_bold=True,
        label_font_size=11, label_color="#605E5C", label_text="Vendas totais",
    )

    objects = _visual(project_dir, name)["visual"]["objects"]
    assert objects["value"] == [{
        "properties": {"fontSize": _lit("28D"), "fontColor": _color("#1F3864"), "bold": _lit("true")},
        "selector": _DEFAULT,
    }]
    assert objects["label"] == [{
        "properties": {"fontSize": _lit("11D"), "fontColor": _color("#605E5C"), "text": _lit("'Vendas totais'")},
        "selector": _DEFAULT,
    }]
    assert result["visual_type"] == "cardVisual"


def test_card_visual_updates_existing_default_entry(project_dir: Path):
    name = _add(project_dir, "cardVisual")
    formatting.set_card_style(pbip_path=str(project_dir), page_name="Pagina1", visual_name=name, value_font_size=20)
    formatting.set_card_style(pbip_path=str(project_dir), page_name="Pagina1", visual_name=name, value_bold=True)

    value = _visual(project_dir, name)["visual"]["objects"]["value"]
    assert len(value) == 1
    assert value[0]["properties"] == {"fontSize": _lit("20D"), "bold": _lit("true")}


def test_legacy_card_uses_labels_and_category_labels(project_dir: Path):
    name = _add(project_dir, "card")

    formatting.set_card_style(
        pbip_path=str(project_dir), page_name="Pagina1", visual_name=name,
        value_font_size=28, value_color="#1F3864", value_bold=True, value_display_units="millions",
        value_precision=1, label_show=True, label_font_size=11, label_color="#605E5C",
    )

    objects = _visual(project_dir, name)["visual"]["objects"]
    assert objects["labels"] == [{"properties": {
        "fontSize": _lit("28D"), "color": _color("#1F3864"), "bold": _lit("true"),
        "labelDisplayUnits": _lit("1000000D"), "labelPrecision": _lit("1L"),
    }}]
    assert objects["categoryLabels"] == [{"properties": {
        "show": _lit("true"), "fontSize": _lit("11D"), "color": _color("#605E5C"),
    }}]


def test_legacy_card_rejects_label_text(project_dir: Path):
    name = _add(project_dir, "card")
    before = _visual(project_dir, name)

    with pytest.raises(InvalidVisualFormattingError, match="cardVisual"):
        formatting.set_card_style(
            pbip_path=str(project_dir), page_name="Pagina1", visual_name=name,
            value_font_size=20, label_text="Vendas",
        )
    assert _visual(project_dir, name) == before


def test_non_card_visual_is_rejected(project_dir: Path):
    name = _add(project_dir, "clusteredColumnChart")

    with pytest.raises(InvalidVisualFormattingError, match="cartão"):
        formatting.set_card_style(pbip_path=str(project_dir), page_name="Pagina1", visual_name=name, value_font_size=20)


@pytest.mark.parametrize("visual_type", ["card", "cardVisual"])
@pytest.mark.parametrize("kwargs", [
    {"value_font_size": 7},
    {"value_font_size": 61},
    {"label_font_size": 100},
    {"value_color": "azul"},
    {"label_color": "#12345"},
    {"value_display_units": "dezenas"},
])
def test_invalid_values_are_rejected_without_writing(project_dir: Path, visual_type: str, kwargs: dict):
    name = _add(project_dir, visual_type)
    before = _visual(project_dir, name)

    with pytest.raises(InvalidVisualFormattingError):
        formatting.set_card_style(
            pbip_path=str(project_dir), page_name="Pagina1", visual_name=name, value_bold=True, **kwargs
        )
    assert _visual(project_dir, name) == before


def test_no_parameter_is_rejected(project_dir: Path):
    name = _add(project_dir, "cardVisual")
    with pytest.raises(InvalidVisualFormattingError):
        formatting.set_card_style(pbip_path=str(project_dir), page_name="Pagina1", visual_name=name)


# --- preenchimento interno e borda interna do cardVisual --------------------------
#
# Achado na réplica de dashboard (2026-09-30): com o fundo da moldura
# desligado, o cardVisual ainda mostra uma caixa branca atrás do número.
# Schema oficial de tema (visual-cardVisual): `fillCustom` (show, fillColor,
# transparency) e `outline` (show) -- doc card-part-03.md: ambos exigem
# selector {"id": "default"}, e recomenda desligar o `outline`.


def test_card_visual_inner_fill_and_outline(project_dir: Path):
    name = _add(project_dir, "cardVisual")

    result = formatting.set_card_style(
        pbip_path=str(project_dir), page_name="Pagina1", visual_name=name,
        card_background_show=False, outline_show=False,
    )

    objects = _visual(project_dir, name)["visual"]["objects"]
    assert objects["fillCustom"] == [{"properties": {"show": _lit("false")}, "selector": _DEFAULT}]
    assert objects["outline"] == [{"properties": {"show": _lit("false")}, "selector": _DEFAULT}]
    assert "fillCustom.show" in result["changed"] and "outline.show" in result["changed"]


def test_card_visual_inner_fill_color(project_dir: Path):
    name = _add(project_dir, "cardVisual")

    formatting.set_card_style(
        pbip_path=str(project_dir), page_name="Pagina1", visual_name=name,
        card_background_color="#F2E3D5", card_background_transparency=20,
    )

    props = _visual(project_dir, name)["visual"]["objects"]["fillCustom"][0]["properties"]
    assert props["fillColor"] == _color("#F2E3D5")
    assert props["transparency"] == _lit("20D")
    assert props["show"] == _lit("true")


def test_inner_fill_is_only_for_card_visual(project_dir: Path):
    name = _add(project_dir, "card")
    with pytest.raises(InvalidVisualFormattingError, match="set_visual_container_style"):
        formatting.set_card_style(
            pbip_path=str(project_dir), page_name="Pagina1", visual_name=name, card_background_show=False,
        )


# --- imagem (ícone) dentro do cardVisual -----------------------------------------
#
# Comparação com o Desktop (2026-09-30, imagem posta num cardVisual pela UI):
# objeto `cardImage` (não `image`), selector {"id": "default"}, com `show` e
# `image.image.{name, url (ResourcePackageItem RegisteredResources), scaling
# 'Fit'}` NA MESMA entrada -- mesma estrutura aninhada da imagem de fundo da
# página. Arquivo registrado em RegisteredResources como item "Image".


def test_card_visual_image_like_the_desktop(project_dir: Path, tmp_path: Path):
    icon = tmp_path / "dinheiro.svg"
    icon.write_bytes(b'<svg xmlns="http://www.w3.org/2000/svg"/>')
    name = _add(project_dir, "cardVisual")

    result = formatting.set_card_style(
        pbip_path=str(project_dir), page_name="Pagina1", visual_name=name, image_path=str(icon),
    )

    [entry] = _visual(project_dir, name)["visual"]["objects"]["cardImage"]
    item = entry["properties"]["image"]["image"]["url"]["expr"]["ResourcePackageItem"]["ItemName"]
    assert entry == {"properties": {
        "show": _lit("true"),
        "image": {"image": {
            "name": _lit("'dinheiro.svg'"),
            "url": {"expr": {"ResourcePackageItem": {
                "PackageName": "RegisteredResources", "PackageType": 1, "ItemName": item,
            }}},
            "scaling": _lit("'Fit'"),
        }},
    }, "selector": _DEFAULT}
    assert (project_dir / "Vendas.Report" / "StaticResources" / "RegisteredResources" / item).is_file()
    assert "cardImage.image" in result["changed"]


def test_card_visual_image_can_be_hidden(project_dir: Path, tmp_path: Path):
    icon = tmp_path / "dinheiro.svg"
    icon.write_bytes(b'<svg xmlns="http://www.w3.org/2000/svg"/>')
    name = _add(project_dir, "cardVisual")
    formatting.set_card_style(pbip_path=str(project_dir), page_name="Pagina1", visual_name=name, image_path=str(icon))

    formatting.set_card_style(pbip_path=str(project_dir), page_name="Pagina1", visual_name=name, image_show=False)

    [entry] = _visual(project_dir, name)["visual"]["objects"]["cardImage"]
    assert entry["properties"]["show"] == _lit("false")
    assert "image" in entry["properties"]


def test_card_image_only_for_card_visual(project_dir: Path, tmp_path: Path):
    icon = tmp_path / "dinheiro.svg"
    icon.write_bytes(b'<svg xmlns="http://www.w3.org/2000/svg"/>')
    name = _add(project_dir, "card")
    with pytest.raises(InvalidVisualFormattingError, match="cardVisual"):
        formatting.set_card_style(pbip_path=str(project_dir), page_name="Pagina1", visual_name=name, image_path=str(icon))
