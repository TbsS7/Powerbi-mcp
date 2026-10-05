"""Aplicação de um tema de cores customizado ao relatório inteiro.

Diferente de visual_writer.set_visual_color (que muda uma série num
visual específico), isto muda a paleta padrão do relatório inteiro --
qualquer visual que ainda não tenha uma cor explícita própria usa essa
paleta.

Dois arquivos, confirmados contra referências oficiais distintas:

- O CONTEÚDO do tema (`name`, `dataColors`) segue o Report Theme JSON
  Schema público da Microsoft (microsoft/powerbi-desktop-samples,
  vendorizado em tests/schemas/) -- um repositório diferente do resto
  dos schemas PBIR usados neste projeto (fabric/item/report/definition),
  porque tema de relatório não é um conceito exclusivo do PBIR: o mesmo
  formato de arquivo já existia antes, como tema exportável/importável
  pela UI do Desktop.
- A LIGAÇÃO em report.json (`resourcePackages` + `themeCollection.
  customTheme`) é confirmada contra o schema oficial report/3.3.0, já
  vendorizado (`ResourcePackageItemType` inclui "CustomTheme").

`reportVersionAtImport` foi confirmado ao vivo (ver
_REPORT_VERSION_AT_IMPORT abaixo): testado contra o Power BI Desktop
real, sobreviveu a um ciclo de salvar/reabrir com o conteúdo intacto,
e o próprio Desktop revelou os valores reais ao escrever um `baseTheme`
ao lado do nosso `customTheme` no mesmo report.json.

ACHADO E CONFIRMADO AO VIVO (achismo inicial estava errado): comparando
com um tema aplicado manualmente pela UI do Desktop e salvo por ele --

- `path` do item em `resourcePackages` é só o NOME DO ARQUIVO
  (`"TemaX.json"`), não o caminho completo a partir da raiz do
  `.Report` -- é relativo à própria pasta do pacote de recursos
  (`StaticResources/RegisteredResources/` para `type:
  "RegisteredResources"`). O caminho completo que a primeira versão
  deste código escrevia fazia o Desktop ignorar o tema silenciosamente
  (sem erro, só não aplicava a cor).
- `name` nas REFERÊNCIAS ao tema (`resourcePackages[].items[].name` e
  `themeCollection.customTheme.name`) é o nome do ARQUIVO, com `.json`
  incluído -- diferente do `name` de dentro do próprio arquivo do tema
  (esse sim, sem extensão, é o nome "limpo" que o usuário escolheu).

Corrigido e reconfirmado ao vivo: o tema passou a aparecer como "Tema
atual" na galeria do Desktop e as cores dos visuais mudaram sozinhas,
sem precisar selecionar nada manualmente.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from errors import InvalidResourceNameError, InvalidThemeColorError, ThemeNotFoundError
from visuals import project
from visuals.names import is_valid_object_name
from visuals.schema_urls import REPORT_THEME_SCHEMA

_REGISTERED_RESOURCES_PACKAGE_NAME = "RegisteredResources"

# Confirmado ao vivo (não é mais melhor esforço): o Power BI Desktop
# escreveu exatamente esses valores no `baseTheme.reportVersionAtImport`
# do próprio report.json ao salvar, na mesma sessão em que testamos
# apply_report_theme (Desktop versão "Fluent2-CY26SU08"). Pode ficar
# desatualizado numa versão futura do Desktop -- se um teste ao vivo
# mostrar um valor diferente, atualize aqui.
_REPORT_VERSION_AT_IMPORT = {"page": "2.3.1", "report": "3.4.0", "visual": "2.12.0"}


def apply_report_theme(pbip_path: str, theme_name: str, data_colors: list[str]) -> dict[str, Any]:
    """Cria (ou substitui) o tema customizado do relatório.

    Raises:
        ReportProjectNotFoundError: o relatório ainda não tem nenhuma
            página criada (chame create_report_page primeiro).
        InvalidResourceNameError: `theme_name` não é seguro para usar
            como nome de arquivo (evita path traversal).
        InvalidThemeColorError: alguma cor de `data_colors` não começa
            com "#".
    """
    if not is_valid_object_name(theme_name):
        raise InvalidResourceNameError("theme_name", theme_name)
    for color in data_colors:
        if not color.startswith("#"):
            raise InvalidThemeColorError(color)

    report_dir = project.resolve_report_dir(pbip_path)
    definition_dir = project.get_definition_dir(report_dir)

    filename = f"{theme_name}.json"

    resources_dir = report_dir / "StaticResources" / "RegisteredResources"
    resources_dir.mkdir(parents=True, exist_ok=True)
    theme_path = resources_dir / filename
    if not theme_path.resolve().is_relative_to(resources_dir.resolve()):
        raise InvalidResourceNameError("theme_name", theme_name)
    _write_json(
        theme_path,
        {"$schema": REPORT_THEME_SCHEMA, "name": theme_name, "dataColors": data_colors},
    )

    report_json_path = definition_dir / "report.json"
    report_data = json.loads(report_json_path.read_text(encoding="utf-8"))

    resource_packages = report_data.get("resourcePackages", [])
    registered = next((p for p in resource_packages if p.get("type") == "RegisteredResources"), None)
    if registered is None:
        registered = {
            "name": _REGISTERED_RESOURCES_PACKAGE_NAME,
            "type": "RegisteredResources",
            "items": [],
        }
        resource_packages.append(registered)

    registered["items"] = [i for i in registered.get("items", []) if i.get("type") != "CustomTheme"]
    registered["items"].append({"name": filename, "path": filename, "type": "CustomTheme"})
    report_data["resourcePackages"] = resource_packages

    report_data["themeCollection"] = report_data.get("themeCollection", {})
    report_data["themeCollection"]["customTheme"] = {
        "name": filename,
        "type": "RegisteredResources",
        "reportVersionAtImport": dict(_REPORT_VERSION_AT_IMPORT),
    }

    _write_json(report_json_path, report_data)

    return {"theme_name": theme_name, "data_colors": data_colors}


def remove_report_theme(pbip_path: str) -> dict[str, Any]:
    """Remove o tema customizado do relatório (volta ao tema padrão do
    Power BI).

    Raises:
        ThemeNotFoundError: não há tema customizado aplicado.
    """
    report_dir = project.resolve_report_dir(pbip_path)
    definition_dir = project.get_definition_dir(report_dir)
    report_json_path = definition_dir / "report.json"
    report_data = json.loads(report_json_path.read_text(encoding="utf-8"))

    custom_theme = report_data.get("themeCollection", {}).get("customTheme")
    if custom_theme is None:
        raise ThemeNotFoundError()
    # custom_theme["name"] é o nome do ARQUIVO (com ".json"), não o nome
    # "limpo" que apply_report_theme recebeu -- ver docstring do módulo.
    # Veio de dentro de report.json, não de um parâmetro direto desta
    # chamada -- revalidar o miolo (sem ".json") antes de usar em Path
    # evita que um report.json adulterado vire um delete arbitrário de
    # arquivo.
    filename = custom_theme["name"]
    theme_name = filename[: -len(".json")] if filename.endswith(".json") else filename
    if not is_valid_object_name(theme_name):
        raise InvalidResourceNameError("theme_name", theme_name)

    for package in report_data.get("resourcePackages", []):
        if package.get("type") == "RegisteredResources":
            package["items"] = [i for i in package.get("items", []) if i.get("type") != "CustomTheme"]
    report_data["resourcePackages"] = [
        p for p in report_data.get("resourcePackages", []) if p.get("items")
    ]
    report_data["themeCollection"].pop("customTheme", None)

    _write_json(report_json_path, report_data)

    resources_dir = report_dir / "StaticResources" / "RegisteredResources"
    theme_path = resources_dir / filename
    if theme_path.resolve().is_relative_to(resources_dir.resolve()) and theme_path.is_file():
        theme_path.unlink()

    return {"theme_name": theme_name, "removed": True}


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
