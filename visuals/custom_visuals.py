"""Visuais personalizados: importar um .pbiviz (ou um .pbix que já use o
visual) no relatório, listar, remover, e descrever seus roles pro
catálogo de visuais.

Fontes (regra do projeto):
- Doc oficial custom-visuals.md (microsoft/skills-for-fabric): pacote
  descompactado em `<Report>.Report/CustomVisuals/<GUID>/` (package.json
  + resources/<GUID>.pbiviz.json) + registro em report.json
  `resourcePackages` (`{name: <GUID>, type: "CustomVisual", items:
  [{name/path: "<GUID>.pbiviz.json", type: "CustomVisualMetadata"}]}`);
  `visual.visualType` = GUID; roles de `capabilities.dataRoles`
  (Grouping -> coluna, Measure -> medida) e limites de
  `dataViewMappings[].conditions`; GUID sempre do package.json, nunca
  adivinhado. Schema oficial report/3.3.0 confirma os tipos.
- ACHADO AO VIVO (2026-09-30) que corrige a doc: só pasta +
  resourcePackages (a receita "privado" da doc) NÃO renderizou o Tornado
  (visual do AppSource) -- "adicione-o a este relatório primeiro". O
  Desktop grava TAMBÉM o GUID em `publicCustomVisuals` (visto no .pbix de
  exemplo do AppSource e ao adicionar o visual pela UI); com isso o mesmo
  visual.json renderizou. Por isso gravamos as três coisas, igual ao
  .pbix do Desktop. Visual 100% privado (fora do AppSource) não foi
  testado ao vivo.
- Também visto ao vivo: ao SALVAR, o Desktop apaga a pasta
  CustomVisuals/ (baixa o visual do AppSource ele mesmo). Os roles então
  ficam guardados numa anotação do report.json
  (`powerbi-mcp.customVisual.<GUID>`) -- anotações são o lugar que a doc
  do Microsoft Learn reserva pra ferramentas externas ("Power BI Desktop
  ignores these annotations").
- Um .pbix que já use o visual também serve de fonte: o pacote fica em
  `Report/CustomVisuals/<GUID>/` com o MESMO layout do .pbiviz (visto no
  .pbix de exemplo) -- só essa pasta é copiada.

Segurança: o arquivo vem do usuário (este servidor nunca baixa nada);
cada entrada do zip é conferida contra path traversal, o GUID só pode ter
letras/números/_ (vira nome de pasta), e o tamanho descompactado tem teto.
"""

from __future__ import annotations

import json
import re
import shutil
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any

from errors import (
    CustomVisualAlreadyExistsError,
    CustomVisualInUseError,
    CustomVisualNotFoundError,
    InvalidCustomVisualError,
)
from visuals import project

_SAFE_GUID = re.compile(r"^[A-Za-z0-9_]+$")
_MAX_UNPACKED_BYTES = 100 * 1024 * 1024
_KIND_TO_ACCEPTS = {
    "Grouping": ("column",),
    "Measure": ("measure",),
    "GroupingOrMeasure": ("column", "measure"),
}


def import_custom_visual(
    pbip_path: str, pbiviz_path: str, replace: bool = False, visual_guid: str | None = None
) -> dict[str, Any]:
    report_dir = project.resolve_report_dir(pbip_path)
    definition_dir = project.get_definition_dir(report_dir)

    package, capabilities, members = _read_package(Path(pbiviz_path), visual_guid)
    guid = package["visual"]["guid"]
    description = _describe(package, capabilities)

    report_json_path = definition_dir / "report.json"
    report = json.loads(report_json_path.read_text(encoding="utf-8"))
    target = report_dir / "CustomVisuals" / guid
    if (guid in _registered(report) or target.exists()) and not replace:
        raise CustomVisualAlreadyExistsError(
            f"O visual '{description['display_name']}' ({guid}) já está importado neste "
            "relatório. Pra atualizar a versão, chame de novo com replace=True."
        )

    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)
    with zipfile.ZipFile(pbiviz_path) as zf:
        for member, relative in members:
            destination = target.joinpath(*PurePosixPath(relative).parts)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(zf.read(member))

    report["publicCustomVisuals"] = [g for g in report.get("publicCustomVisuals", []) if g != guid] + [guid]
    report["resourcePackages"] = [p for p in report.get("resourcePackages", []) if p.get("name") != guid] + [{
        "name": guid,
        "type": "CustomVisual",
        "items": [{"name": f"{guid}.pbiviz.json", "path": f"{guid}.pbiviz.json", "type": "CustomVisualMetadata"}],
    }]
    annotation = {
        "name": _ANNOTATION_PREFIX + guid,
        "value": json.dumps(
            {"display_name": description["display_name"], "version": description["version"],
             "roles": description["roles"]},
            ensure_ascii=False,
        ),
    }
    report["annotations"] = [a for a in report.get("annotations", []) if a.get("name") != annotation["name"]] + [annotation]
    _write(report_json_path, report)
    return description


def list_custom_visuals(pbip_path: str) -> list[dict[str, Any]]:
    report_dir = project.resolve_report_dir(pbip_path)
    report = json.loads((project.get_definition_dir(report_dir) / "report.json").read_text(encoding="utf-8"))
    result = []
    for guid in _registered(report):
        info = _known_info(report, report_dir, guid)
        if info is None:
            result.append({
                "visual_type": guid, "display_name": guid, "version": None, "roles": None,
                "note": "Adicionado pelo Desktop, sem os campos conhecidos -- pra usar pelo MCP, "
                        "importe o .pbiviz dele com import_custom_visual (replace=True).",
            })
        else:
            result.append(info)
    return result


def remove_custom_visual(pbip_path: str, visual_type: str) -> dict[str, Any]:
    report_dir = project.resolve_report_dir(pbip_path)
    definition_dir = project.get_definition_dir(report_dir)
    report_json_path = definition_dir / "report.json"
    report = json.loads(report_json_path.read_text(encoding="utf-8"))
    if visual_type not in _registered(report):
        raise CustomVisualNotFoundError(f"O visual personalizado '{visual_type}' não está importado neste relatório.")

    users = []
    for visual_json in sorted((definition_dir / "pages").glob("*/visuals/*/visual.json")):
        data = json.loads(visual_json.read_text(encoding="utf-8"))
        if data.get("visual", {}).get("visualType") == visual_type:
            users.append(f"{visual_json.parents[2].name}/{visual_json.parent.name}")
    if users:
        raise CustomVisualInUseError(
            f"O visual personalizado '{visual_type}' ainda é usado por: {', '.join(users)} "
            "(página/visual). Remova esses visuais antes."
        )

    for key, keep in (
        ("publicCustomVisuals", lambda g: g != visual_type),
        ("resourcePackages", lambda p: p.get("name") != visual_type),
        ("annotations", lambda a: a.get("name") != _ANNOTATION_PREFIX + visual_type),
    ):
        if key in report:
            report[key] = [item for item in report[key] if keep(item)]
            if not report[key]:
                report.pop(key)
    _write(report_json_path, report)
    if _SAFE_GUID.match(visual_type):
        shutil.rmtree(report_dir / "CustomVisuals" / visual_type, ignore_errors=True)
    return {"visual_type": visual_type, "removed": True}


def custom_visual_roles(report_dir: Path, visual_type: str) -> list[dict[str, Any]] | None:
    """Roles de um visual personalizado registrado no relatório (pela
    anotação ou, se ela não existir, pelo pacote na pasta), ou None."""
    if not _SAFE_GUID.match(visual_type):
        return None
    report_json = report_dir / "definition" / "report.json"
    if not report_json.is_file():
        return None
    report = json.loads(report_json.read_text(encoding="utf-8"))
    if visual_type not in _registered(report):
        return None
    info = _known_info(report, report_dir, visual_type)
    return None if info is None else info["roles"]


_ANNOTATION_PREFIX = "powerbi-mcp.customVisual."


def _registered(report: dict[str, Any]) -> list[str]:
    """GUIDs registrados: em publicCustomVisuals e/ou como pacote
    CustomVisual em resourcePackages (sem repetir, na ordem)."""
    guids = list(report.get("publicCustomVisuals", []))
    guids += [p["name"] for p in report.get("resourcePackages", []) if p.get("type") == "CustomVisual"]
    return list(dict.fromkeys(g for g in guids if isinstance(g, str)))


def _known_info(report: dict[str, Any], report_dir: Path, guid: str) -> dict[str, Any] | None:
    for annotation in report.get("annotations", []):
        if annotation.get("name") == _ANNOTATION_PREFIX + guid:
            data = json.loads(annotation["value"])
            return {"visual_type": guid, "display_name": data.get("display_name", guid),
                    "version": data.get("version"), "roles": data.get("roles", [])}
    loaded = _load_installed(report_dir, guid)
    return None if loaded is None else _describe(*loaded)


def _write(path: Path, data: dict[str, Any]) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


# --- internos ---------------------------------------------------------------


def _read_package(
    pbiviz: Path, visual_guid: str | None = None
) -> tuple[dict[str, Any], dict[str, Any], list[tuple[str, str]]]:
    """(package.json, capabilities, [(entrada no zip, caminho relativo
    dentro de CustomVisuals/<GUID>/)]) de um .pbiviz ou de um .pbix que
    contém o visual."""
    if not pbiviz.is_file():
        raise InvalidCustomVisualError(f"Arquivo '{pbiviz}' não encontrado.")
    try:
        with zipfile.ZipFile(pbiviz) as zf:
            infos = [i for i in zf.infolist() if not i.is_dir()]
            names = [i.filename for i in infos]
            for name in names:
                parts = PurePosixPath(name.replace("\\", "/")).parts
                if name.startswith(("/", "\\")) or ".." in parts or (parts and ":" in parts[0]):
                    raise InvalidCustomVisualError(f"O pacote tem um caminho inseguro: '{name}'.")

            prefix = _package_prefix(names, visual_guid)
            members = [(n, n[len(prefix):]) for n in names if n.startswith(prefix)]
            if sum(i.file_size for i in infos if i.filename.startswith(prefix)) > _MAX_UNPACKED_BYTES:
                raise InvalidCustomVisualError("O pacote descompactado passa de 100 MB -- não parece um .pbiviz.")

            package = json.loads(zf.read(prefix + "package.json").decode("utf-8-sig"))
            guid = package.get("visual", {}).get("guid", "")
            if not isinstance(guid, str) or not _SAFE_GUID.match(guid):
                raise InvalidCustomVisualError(f"GUID do visual inválido no package.json: {guid!r}.")
            resource = f"resources/{guid}.pbiviz.json"
            if prefix + resource not in names:
                raise InvalidCustomVisualError(f"O pacote não tem '{resource}' (o conteúdo do visual).")
            capabilities = json.loads(zf.read(prefix + resource).decode("utf-8-sig")).get("capabilities", {})
    except zipfile.BadZipFile as exc:
        raise InvalidCustomVisualError(f"'{pbiviz}' não é um .pbiviz nem .pbix válido (não é um arquivo zip).") from exc
    return package, capabilities, members


def _package_prefix(names: list[str], visual_guid: str | None) -> str:
    """"" num .pbiviz (package.json na raiz); "Report/CustomVisuals/<GUID>/"
    num .pbix."""
    if "package.json" in names:
        return ""
    embedded = sorted({
        n.split("/")[2] for n in names
        if n.startswith("Report/CustomVisuals/") and n.endswith("/package.json")
        and n.count("/") == 3
    })
    if not embedded:
        raise InvalidCustomVisualError(
            "O arquivo não tem package.json nem visual personalizado dentro (Report/CustomVisuals/) -- "
            "use o .pbiviz do visual, ou um .pbix que já use o visual."
        )
    if visual_guid is None:
        if len(embedded) > 1:
            raise InvalidCustomVisualError(
                f"Este .pbix tem {len(embedded)} visuais personalizados: {', '.join(embedded)}. "
                "Diga qual importar em `visual_guid`."
            )
        visual_guid = embedded[0]
    if visual_guid not in embedded:
        raise InvalidCustomVisualError(
            f"O visual '{visual_guid}' não está neste arquivo. Disponíveis: {', '.join(embedded)}."
        )
    return f"Report/CustomVisuals/{visual_guid}/"


def _load_installed(report_dir: Path, guid: str) -> tuple[dict[str, Any], dict[str, Any]] | None:
    if not _SAFE_GUID.match(guid):
        return None
    folder = report_dir / "CustomVisuals" / guid
    package_json = folder / "package.json"
    resource = folder / "resources" / f"{guid}.pbiviz.json"
    if not package_json.is_file() or not resource.is_file():
        return None
    package = json.loads(package_json.read_text(encoding="utf-8-sig"))
    capabilities = json.loads(resource.read_text(encoding="utf-8-sig")).get("capabilities", {})
    return package, capabilities


def _roles(capabilities: dict[str, Any]) -> list[dict[str, Any]]:
    conditions = [
        condition
        for mapping in capabilities.get("dataViewMappings", [])
        for condition in mapping.get("conditions", [])
    ]
    roles = []
    for role in capabilities.get("dataRoles", []):
        name = role["name"]
        limits = [c.get(name, {}) for c in conditions]
        if limits:
            min_fields = min(int(limit.get("min", 0)) for limit in limits)
            maxes = [limit.get("max") for limit in limits]
            max_fields = None if any(m is None for m in maxes) else max(int(m) for m in maxes)
        else:
            min_fields, max_fields = 0, None
        roles.append({
            "name": name,
            "display_name": role.get("displayName", name),
            "accepts": list(_KIND_TO_ACCEPTS.get(role.get("kind"), ("column", "measure"))),
            "min_fields": min_fields,
            "max_fields": max_fields,
        })
    return roles


def _describe(package: dict[str, Any], capabilities: dict[str, Any]) -> dict[str, Any]:
    visual = package["visual"]
    return {
        "visual_type": visual["guid"],
        "display_name": visual.get("displayName", visual["guid"]),
        "version": visual.get("version"),
        "roles": _roles(capabilities),
    }
