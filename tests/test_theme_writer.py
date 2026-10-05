"""Testes de visuals.theme_writer: apply_report_theme / remove_report_theme.

O conteúdo do arquivo de tema (name, dataColors) é validado contra o
schema oficial do Power BI (Report Theme JSON Schema,
microsoft/powerbi-desktop-samples, vendorizado em tests/schemas/). A
mudança em report.json (resourcePackages + themeCollection.customTheme)
segue a estrutura confirmada em report/3.3.0 -- não inventada.

`reportVersionAtImport` foi confirmado ao vivo: o Power BI Desktop
escreveu exatamente esses valores (page 2.3.1, report 3.4.0, visual
2.12.0) no `baseTheme` do próprio report.json ao salvar, na mesma
sessão em que testamos apply_report_theme.

Também confirmado ao vivo (comparando com um tema aplicado
manualmente): `path`/`name` nas referências ao tema usam o nome do
ARQUIVO (com ".json"), e `path` é só o nome do arquivo -- não o
caminho completo a partir da raiz do .Report. A primeira versão deste
código errava os dois, e o Desktop ignorava o tema em silêncio.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from errors import InvalidResourceNameError, InvalidThemeColorError, ThemeNotFoundError
from tests.schema_validation import validate_report_theme_json
from visuals import page_writer, theme_writer


@pytest.fixture
def project_with_page(tmp_path: Path) -> Path:
    root = tmp_path / "VendasProject"
    root.mkdir()
    (root / "Vendas.pbip").write_text("{}", encoding="utf-8")
    (root / "Vendas.Report").mkdir()
    page_writer.create_report_page(pbip_path=str(root), page_name="Pagina1")
    return root


def _report_json_path(project_root: Path) -> Path:
    return project_root / "Vendas.Report" / "definition" / "report.json"


def _theme_json_path(project_root: Path, theme_name: str) -> Path:
    return project_root / "Vendas.Report" / "StaticResources" / "RegisteredResources" / f"{theme_name}.json"


def test_apply_report_theme_writes_schema_valid_theme_file(project_with_page: Path):
    result = theme_writer.apply_report_theme(
        pbip_path=str(project_with_page), theme_name="MeuTema",
        data_colors=["#2E86AB", "#E6553A", "#F1A208"],
    )

    assert result == {
        "theme_name": "MeuTema", "data_colors": ["#2E86AB", "#E6553A", "#F1A208"],
    }
    theme_path = _theme_json_path(project_with_page, "MeuTema")
    assert theme_path.is_file()
    data = json.loads(theme_path.read_text(encoding="utf-8"))
    validate_report_theme_json(data)
    assert data["name"] == "MeuTema"
    assert data["dataColors"] == ["#2E86AB", "#E6553A", "#F1A208"]


def test_apply_report_theme_wires_report_json(project_with_page: Path):
    theme_writer.apply_report_theme(
        pbip_path=str(project_with_page), theme_name="MeuTema", data_colors=["#2E86AB"],
    )

    report_data = json.loads(_report_json_path(project_with_page).read_text(encoding="utf-8"))
    assert report_data["themeCollection"]["customTheme"]["name"] == "MeuTema.json"
    assert report_data["themeCollection"]["customTheme"]["type"] == "RegisteredResources"

    registered = next(
        p for p in report_data["resourcePackages"] if p["type"] == "RegisteredResources"
    )
    theme_item = next(i for i in registered["items"] if i["type"] == "CustomTheme")
    assert theme_item["name"] == "MeuTema.json"
    assert theme_item["path"] == "MeuTema.json"


def test_apply_report_theme_raises_for_invalid_color(project_with_page: Path):
    with pytest.raises(InvalidThemeColorError):
        theme_writer.apply_report_theme(
            pbip_path=str(project_with_page), theme_name="MeuTema", data_colors=["azul"],
        )
    assert not _theme_json_path(project_with_page, "MeuTema").exists()


def test_apply_report_theme_replaces_previous_theme(project_with_page: Path):
    theme_writer.apply_report_theme(
        pbip_path=str(project_with_page), theme_name="TemaAntigo", data_colors=["#111111"],
    )

    theme_writer.apply_report_theme(
        pbip_path=str(project_with_page), theme_name="TemaNovo", data_colors=["#222222"],
    )

    report_data = json.loads(_report_json_path(project_with_page).read_text(encoding="utf-8"))
    registered = next(
        p for p in report_data["resourcePackages"] if p["type"] == "RegisteredResources"
    )
    custom_themes = [i for i in registered["items"] if i["type"] == "CustomTheme"]
    assert len(custom_themes) == 1
    assert custom_themes[0]["name"] == "TemaNovo.json"
    assert report_data["themeCollection"]["customTheme"]["name"] == "TemaNovo.json"


def test_remove_report_theme_clears_everything(project_with_page: Path):
    theme_writer.apply_report_theme(
        pbip_path=str(project_with_page), theme_name="MeuTema", data_colors=["#2E86AB"],
    )

    result = theme_writer.remove_report_theme(pbip_path=str(project_with_page))

    assert result == {"theme_name": "MeuTema", "removed": True}
    assert not _theme_json_path(project_with_page, "MeuTema").exists()
    report_data = json.loads(_report_json_path(project_with_page).read_text(encoding="utf-8"))
    assert "customTheme" not in report_data.get("themeCollection", {})


def test_remove_report_theme_raises_when_none_applied(project_with_page: Path):
    with pytest.raises(ThemeNotFoundError):
        theme_writer.remove_report_theme(pbip_path=str(project_with_page))


def test_apply_report_theme_raises_for_path_traversal_theme_name(
    project_with_page: Path, tmp_path: Path
):
    """Achado de segurança: sem validar, um theme_name tipo
    '../../../../alvo' escaparia de StaticResources/RegisteredResources/
    (path traversal) antes de escrever o arquivo do tema."""
    outside_target_parent = tmp_path / "fora_do_projeto"
    outside_target_parent.mkdir()

    with pytest.raises(InvalidResourceNameError):
        theme_writer.apply_report_theme(
            pbip_path=str(project_with_page),
            theme_name="../" * 10 + "fora_do_projeto/alvo",
            data_colors=["#2E86AB"],
        )
    assert list(outside_target_parent.iterdir()) == []
