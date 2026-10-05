"""Montagem e escrita de visual.json.

Dois tipos de visual, dois caminhos de montagem:

- **Visuais ligados a dado** (card, clusteredColumnChart, ...): só
  aceitam chegar a escrever um arquivo depois de
  `visuals.validator.validate_visual_fields` confirmar cada campo
  contra o modelo -- essa ordem (validar tudo primeiro, escrever
  depois) garante que uma falha de validação nunca deixa um visual pela
  metade no disco. `build_visual_json` monta o JSON deles.
- **textbox** (`visuals.catalog.VisualSpec.is_text_visual`): não tem
  campo nenhum pra validar contra o modelo -- é texto direto. Não passa
  por `validate_visual_fields` nem precisa de conexão com o modelo.
  `build_textbox_json` monta o JSON dele.

Os dois formatos são confirmados contra os schemas públicos do PBIR
(visualContainer/2.7.0 + visualConfiguration/2.3.0 + semanticQuery/1.4.0
para visuais de dado; visualContainer/2.7.0 + formattingObjectDefinitions/
1.5.0 para textbox, formato confirmado contra referência oficial da
Microsoft para autoria de PBIR) -- não inventados. Ver
tests/schema_validation.py para a validação automatizada.
"""

from __future__ import annotations

import json
import re
import shutil
import uuid
from pathlib import Path
from typing import Any

from errors import (
    InvalidResourceNameError,
    InvalidVisualRoleError,
    PageNotFoundError,
    VisualNotFoundError,
)
from modeling import metadata as modeling_metadata
from visuals import project
from visuals.catalog import get_visual_spec
from visuals.names import is_valid_object_name, resolve_page_dir
from visuals.schema_urls import VISUAL_CONTAINER_SCHEMA
from visuals.validator import ResolvedField, resolve_field, validate_visual_fields

_DEFAULT_TEXT_STYLE = {"fontFamily": "Segoe UI", "fontSize": "12pt"}


def add_visual(
    pbip_path: str,
    page_name: str,
    visual_type: str,
    x: float,
    y: float,
    width: float,
    height: float,
    fields: dict[str, list[str]] | None = None,
    text: str | None = None,
) -> dict[str, Any]:
    report_dir = project.resolve_report_dir(pbip_path)
    definition_dir = project.get_definition_dir(report_dir)
    page_dir = resolve_page_dir(definition_dir / "pages", page_name)
    if not page_dir.is_dir():
        raise PageNotFoundError(
            f"Página '{page_name}' não existe em '{report_dir}'. Chame "
            "create_report_page primeiro."
        )

    # levanta UnknownVisualTypeError se não existir (nem como visual
    # personalizado importado no relatório)
    spec = get_visual_spec(visual_type, report_dir)

    if spec.is_text_visual:
        if fields:
            raise InvalidVisualRoleError(
                f"Visual de texto '{visual_type}' não usa `fields` -- use `text`."
            )
        if not text:
            raise InvalidVisualRoleError(
                f"Visual de texto '{visual_type}' precisa de `text` (não pode ser vazio)."
            )
        visual_name = uuid.uuid4().hex[:20]
        instance = build_textbox_json(visual_name=visual_name, x=x, y=y, width=width, height=height, text=text)
        result_extra: dict[str, Any] = {"text": text}
    else:
        if text:
            raise InvalidVisualRoleError(
                f"Visual '{visual_type}' não é de texto -- use `fields`, não `text`."
            )
        model_metadata = modeling_metadata.get_model_metadata(pbip_path=pbip_path)
        resolved_fields = validate_visual_fields(visual_type, fields or {}, model_metadata, report_dir)
        visual_name = uuid.uuid4().hex[:20]
        instance = build_visual_json(
            visual_name=visual_name,
            visual_type=visual_type,
            x=x,
            y=y,
            width=width,
            height=height,
            resolved_fields=resolved_fields,
        )
        result_extra = {
            "fields": {
                role: [f.query_ref for f in role_fields]
                for role, role_fields in resolved_fields.items()
            }
        }

    layer = _next_layer(page_dir)
    instance["position"].update(z=layer, tabOrder=layer)
    visual_dir = page_dir / "visuals" / visual_name
    visual_dir.mkdir(parents=True)
    (visual_dir / "visual.json").write_text(
        json.dumps(instance, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    return {
        "visual_name": visual_name,
        "visual_type": visual_type,
        "page_name": page_name,
        **result_extra,
    }


def list_visuals(pbip_path: str, page_name: str) -> list[dict[str, Any]]:
    """Lista os visuais de uma página com posição e conteúdo básico
    (fields ou text, conforme o tipo) -- pra não precisar guardar o
    `visual_name` de quando cada visual foi criado.

    Raises:
        PageNotFoundError: `page_name` não existe no relatório.
    """
    report_dir = project.resolve_report_dir(pbip_path)
    definition_dir = project.get_definition_dir(report_dir)
    page_dir = resolve_page_dir(definition_dir / "pages", page_name)
    if not page_dir.is_dir():
        raise PageNotFoundError(f"Página '{page_name}' não existe em '{report_dir}'.")

    visuals_dir = page_dir / "visuals"
    if not visuals_dir.is_dir():
        return []

    result = []
    for visual_dir in sorted(visuals_dir.iterdir()):
        visual_json_path = visual_dir / "visual.json"
        if not visual_json_path.is_file():
            continue
        instance = json.loads(visual_json_path.read_text(encoding="utf-8"))
        result.append(_describe_visual(instance, page_name))
    return result


def _describe_visual(instance: dict[str, Any], page_name: str) -> dict[str, Any]:
    visual = instance["visual"]
    position = instance["position"]
    entry: dict[str, Any] = {
        "visual_name": instance["name"],
        "visual_type": visual["visualType"],
        "page_name": page_name,
        "position": {
            "x": position["x"],
            "y": position["y"],
            "width": position["width"],
            "height": position["height"],
        },
    }
    if visual["visualType"] == "textbox":
        entry["text"] = _extract_textbox_text(instance)
    elif "query" in visual:
        entry["fields"] = {
            role: [p["queryRef"] for p in role_data.get("projections", [])]
            for role, role_data in visual["query"]["queryState"].items()
        }
    return entry


def delete_visual(pbip_path: str, page_name: str, visual_name: str) -> dict[str, Any]:
    """Remove um visual de uma página.

    Raises:
        PageNotFoundError: `page_name` não existe no relatório.
        VisualNotFoundError: `visual_name` não existe em `page_name`.
    """
    visual_dir = _resolve_visual_dir(pbip_path, page_name, visual_name)
    shutil.rmtree(visual_dir)
    return {"visual_name": visual_name, "page_name": page_name, "deleted": True}


def update_visual(
    pbip_path: str,
    page_name: str,
    visual_name: str,
    x: float | None = None,
    y: float | None = None,
    width: float | None = None,
    height: float | None = None,
    fields: dict[str, list[str]] | None = None,
    text: str | None = None,
    z: float | None = None,
) -> dict[str, Any]:
    """Atualiza um visual já existente, no lugar (mesma pasta/nome).
    `z` muda a camada (maior = mais por cima); omitido, a camada atual é
    mantida -- inclusive quando `fields`/`text` reconstroem o visual.

    Cada parâmetro omitido mantém o valor atual do visual -- passar só
    `x`/`y` reposiciona sem tocar no conteúdo; passar `fields` (visual
    ligado a dado) ou `text` (textbox) substitui o conteúdo por
    completo, revalidado exatamente como em add_visual. Com `fields`, só
    `visual.query` (e a posição) é trocado -- formatação, filtros e
    visibilidade ficam.

    Raises:
        PageNotFoundError: `page_name` não existe no relatório.
        VisualNotFoundError: `visual_name` não existe em `page_name`.
        InvalidVisualRoleError: `fields` passado num textbox, `text`
            passado num visual ligado a dado, ou role/arity inválidos.
        UnknownFieldError: alguma referência em `fields` não existe no
            modelo.
    """
    visual_dir = _resolve_visual_dir(pbip_path, page_name, visual_name)
    visual_json_path = visual_dir / "visual.json"
    existing = json.loads(visual_json_path.read_text(encoding="utf-8"))

    existing_position = existing["position"]
    resolved_x = existing_position["x"] if x is None else x
    resolved_y = existing_position["y"] if y is None else y
    resolved_width = existing_position["width"] if width is None else width
    resolved_height = existing_position["height"] if height is None else height

    visual_type = existing["visual"]["visualType"]
    if fields is None and text is None:
        # só posição/camada: não depende do tipo -- vale até pra botão
        # (actionButton), que não está no catálogo (achado na réplica)
        existing["position"] = {
            **existing_position,
            "x": resolved_x, "y": resolved_y, "width": resolved_width, "height": resolved_height,
        }
        if z is not None:
            existing["position"]["z"] = z
        visual_json_path.write_text(json.dumps(existing, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        return {"visual_name": visual_name, "visual_type": visual_type, "page_name": page_name}

    report_dir = project.resolve_report_dir(pbip_path)
    spec = get_visual_spec(visual_type, report_dir)

    if spec.is_text_visual:
        if fields:
            raise InvalidVisualRoleError(
                f"Visual de texto '{visual_type}' não usa `fields` -- use `text`."
            )
        resolved_text = text if text is not None else _extract_textbox_text(existing)
        instance = build_textbox_json(
            visual_name=visual_name, x=resolved_x, y=resolved_y,
            width=resolved_width, height=resolved_height, text=resolved_text,
        )
        result_extra: dict[str, Any] = {"text": resolved_text}
    else:
        if text:
            raise InvalidVisualRoleError(
                f"Visual '{visual_type}' não é de texto -- use `fields`, não `text`."
            )
        if fields is not None:
            model_metadata = modeling_metadata.get_model_metadata(pbip_path=pbip_path)
            resolved_fields = validate_visual_fields(visual_type, fields, model_metadata, report_dir)
            rebuilt = build_visual_json(
                visual_name=visual_name, visual_type=visual_type, x=resolved_x, y=resolved_y,
                width=resolved_width, height=resolved_height, resolved_fields=resolved_fields,
            )
            # Troca SÓ a consulta (campos): formatação (objects, títulos,
            # fundo), filtros do visual e visibilidade continuam -- antes
            # o visual era reconstruído do zero e perdia tudo (achado na
            # réplica, página 2).
            instance = existing
            instance["position"] = rebuilt["position"]
            instance["visual"]["query"] = rebuilt["visual"]["query"]
            result_extra = {
                "fields": {
                    role: [f.query_ref for f in role_fields]
                    for role, role_fields in resolved_fields.items()
                }
            }
        else:
            # só reposiciona/redimensiona -- mantém query/objects como estavam
            instance = existing
            instance["position"] = {
                **existing_position,
                "x": resolved_x, "y": resolved_y, "width": resolved_width, "height": resolved_height,
            }
            result_extra = {}

    instance["position"]["z"] = existing_position.get("z", 0) if z is None else z
    instance["position"]["tabOrder"] = existing_position.get("tabOrder", 0)

    visual_json_path.write_text(
        json.dumps(instance, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    return {
        "visual_name": visual_name,
        "visual_type": visual_type,
        "page_name": page_name,
        **result_extra,
    }


def _next_layer(page_dir: Path) -> int:
    """Camada (z/tabOrder) de um visual novo: por cima de todos os que já
    existem na página, em passos de 1000 (template oficial usa 1000).
    Achado na réplica de dashboard: com tudo em z=0 a ordem de
    empilhamento ficava indefinida."""
    top = 0
    for visual_json in (page_dir / "visuals").glob("*/visual.json"):
        try:
            top = max(top, int(json.loads(visual_json.read_text(encoding="utf-8"))["position"].get("z", 0)))
        except (ValueError, KeyError, TypeError):
            continue
    return (top // 1000 + 1) * 1000


def set_slicer_sync(
    pbip_path: str,
    page_name: str,
    visual_name: str,
    group_name: str,
    field_changes: bool = True,
    filter_changes: bool = True,
) -> dict[str, Any]:
    """Sincroniza um slicer com outros que tenham o mesmo `group_name`
    (em qualquer página) -- selecionar um valor num propaga pros
    demais. Funciona no slicer clássico (`slicer`) e no slicer de botões
    (`advancedSlicerVisual`).

    Confirmado contra o schema oficial (visualConfiguration/2.3.0,
    `syncGroup`), não suposto. O slicer de botões é MELHOR ESFORÇO: a doc
    oficial (slicers-part-02.md, "Slicer Sync Groups") fala de slicers em
    geral ("mesmo visualType e mesma coluna"), mas o exemplo é só do
    `slicer` -- pendente de confirmação ao vivo (réplica, página 2).

    Raises:
        PageNotFoundError: `page_name` não existe no relatório.
        VisualNotFoundError: `visual_name` não existe em `page_name`.
        InvalidVisualRoleError: o visual não é um `slicer`.
    """
    visual_dir = _resolve_visual_dir(pbip_path, page_name, visual_name)
    visual_json_path = visual_dir / "visual.json"
    instance = json.loads(visual_json_path.read_text(encoding="utf-8"))

    visual_type = instance["visual"]["visualType"]
    if visual_type not in ("slicer", "advancedSlicerVisual"):
        raise InvalidVisualRoleError(
            f"set_slicer_sync só funciona em slicer ('slicer' ou 'advancedSlicerVisual'; esse é '{visual_type}')."
        )

    sync_group = {
        "groupName": group_name, "fieldChanges": field_changes, "filterChanges": filter_changes,
    }
    instance["visual"]["syncGroup"] = sync_group
    visual_json_path.write_text(
        json.dumps(instance, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    return {"visual_name": visual_name, "page_name": page_name, "sync_group": sync_group}


def remove_slicer_sync(pbip_path: str, page_name: str, visual_name: str) -> dict[str, Any]:
    """Reverte set_slicer_sync -- volta o slicer a não estar
    sincronizado com nenhum grupo."""
    visual_dir = _resolve_visual_dir(pbip_path, page_name, visual_name)
    visual_json_path = visual_dir / "visual.json"
    instance = json.loads(visual_json_path.read_text(encoding="utf-8"))

    instance["visual"].pop("syncGroup", None)
    visual_json_path.write_text(
        json.dumps(instance, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    return {"visual_name": visual_name, "page_name": page_name, "sync_group": None}


_SLICER_STYLE_VALUES = (
    "Dropdown", "Basic", "Between", "Single", "Before", "After", "Relative", "RelativeTime",
)


# selection_mode -> propriedades de `selection` (nomes do schema oficial
# de tema; títulos na UI: strictSingleSelect = "Seleção única",
# singleSelect = "Seleção múltipla com CTRL").
_SLICER_SELECTION_MODES: dict[str, dict[str, bool]] = {
    "single": {"strictSingleSelect": True},
    "multi_ctrl": {"strictSingleSelect": False, "singleSelect": True},
    "multi": {"strictSingleSelect": False, "singleSelect": False},
}


def set_slicer_config(
    pbip_path: str,
    page_name: str,
    visual_name: str,
    style: str | None = None,
    selection_mode: str | None = None,
    show_select_all: bool | None = None,
    show_search: bool | None = None,
) -> dict[str, Any]:
    """Configura o estilo de seleção de um slicer (`visual_type="slicer"`
    só -- não `listSlicer`/`advancedSlicerVisual`, tipos diferentes que
    este projeto não cria).

    CONFIRMADO AO VIVO (além de contra a referência oficial de autoria
    de PBIR, skills-for-fabric/.../slicers.md, seção "Slicer types"):
    `style` vira `objects.data[0].properties.mode`, um dos literais
    `'Dropdown'` (caixa suspensa), `'Basic'` (lista), `'Between'`
    (intervalo de datas/números), `'Single'` (seleção única), `'Before'`/
    `'After'` (limite superior/inferior), `'Relative'` (data relativa,
    ex: "últimos 30 dias" -- exige campo de data) ou `'RelativeTime'`
    (tempo relativo, ex: "últimas 2 horas" -- exige campo de
    data/hora). Testado ao vivo com `style="Basic"`: o slicer virou
    lista com checkboxes visíveis, sem precisar abrir a caixa suspensa.

    Seleção e busca (2026-09-25) -- nomes do schema oficial de tema,
    CONFIRMADOS comparando com um slicer configurado à mão pela UI do
    Desktop e salvo (técnica de comparação com o Desktop):
    - `show_select_all` -> `objects.selection[0].properties.
      selectAllCheckboxEnabled` (o Desktop escreveu exatamente isso).
    - `show_search` -> `objects.general[0].properties.selfFilterEnabled`
      (o Desktop escreveu exatamente isso). A doc de autoria sugeria
      `searchBox.show` -- estava errada; o schema de tema tinha razão
      (`searchBox` só tem cor/borda).
    - `selection_mode` -> `selection.strictSingleSelect` ("Seleção
      única") e `selection.singleSelect` ("Seleção múltipla com CTRL").
      Com "Seleção múltipla com CTRL" ligado (o padrão), o Desktop não
      escreve nada; esta tool escreve os dois valores explícitos, que
      dá no mesmo.
    - Botão de limpar seleção: não é configurável -- o ícone de borracha
      aparece sozinho no cabeçalho do slicer (confirmado na UI: não há
      opção pra isso no painel de formatação).

    Raises:
        PageNotFoundError: `page_name` não existe no relatório.
        VisualNotFoundError: `visual_name` não existe em `page_name`.
        InvalidVisualRoleError: o visual não é um `slicer`, ou `style`/
            `selection_mode` não é um dos valores aceitos.
    """
    if style is not None and style not in _SLICER_STYLE_VALUES:
        raise InvalidVisualRoleError(
            f"style '{style}' inválido -- use um de {', '.join(_SLICER_STYLE_VALUES)}."
        )
    if selection_mode is not None and selection_mode not in _SLICER_SELECTION_MODES:
        raise InvalidVisualRoleError(
            f"selection_mode '{selection_mode}' inválido -- use um de "
            f"{', '.join(_SLICER_SELECTION_MODES)}."
        )

    visual_dir = _resolve_visual_dir(pbip_path, page_name, visual_name)
    visual_json_path = visual_dir / "visual.json"
    instance = json.loads(visual_json_path.read_text(encoding="utf-8"))

    visual_type = instance["visual"]["visualType"]
    if visual_type != "slicer":
        raise InvalidVisualRoleError(
            f"set_slicer_config só funciona em visual_type='slicer' (esse é '{visual_type}')."
        )

    if style is not None:
        _slicer_object_properties(instance, "data")["mode"] = _literal(f"'{style}'")

    if selection_mode is not None:
        selection = _slicer_object_properties(instance, "selection")
        for prop, value in _SLICER_SELECTION_MODES[selection_mode].items():
            selection[prop] = _literal(value)
    if show_select_all is not None:
        _slicer_object_properties(instance, "selection")["selectAllCheckboxEnabled"] = _literal(show_select_all)
    if show_search is not None:
        _slicer_object_properties(instance, "general")["selfFilterEnabled"] = _literal(show_search)

    visual_json_path.write_text(
        json.dumps(instance, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    return {
        "visual_name": visual_name, "page_name": page_name, "style": style,
        "selection_mode": selection_mode, "show_select_all": show_select_all,
        "show_search": show_search,
    }


def _slicer_object_properties(instance: dict[str, Any], object_name: str) -> dict[str, Any]:
    """`properties` da entrada base (sem selector) de `objects.<nome>`,
    criando se preciso -- preserva o que já existe."""
    entries = instance["visual"].setdefault("objects", {}).setdefault(object_name, [])
    base = next((e for e in entries if "selector" not in e), None)
    if base is None:
        base = {"properties": {}}
        entries.insert(0, base)
    return base.setdefault("properties", {})


_NAVIGATION_TARGET_KEYS = {"page": "navigationSection", "bookmark": "bookmark", "clear_slicers": None}
# 'ClearAllSlicers': doc oficial button-part-02.md (Action Types) -- sem destino.
_NAVIGATION_ACTION_TYPES = {"page": "PageNavigation", "bookmark": "Bookmark", "clear_slicers": "ClearAllSlicers"}


def add_navigation_button(
    pbip_path: str,
    page_name: str,
    x: float,
    y: float,
    width: float,
    height: float,
    target_type: str,
    target: str | None = None,
    transparent: bool = False,
    text: str | None = None,
    text_color: str | None = None,
    text_size: float | None = None,
    icon_path: str | None = None,
    fill_color: str | None = None,
    corner_radius: int | None = None,
) -> dict[str, Any]:
    """Adiciona um botão que navega pra uma página, aplica um bookmark
    ou limpa as segmentações da página ao ser clicado (só funciona ao
    visualizar o relatório, não no modo de edição do Desktop).

    `transparent=True` esconde todas as camadas (preenchimento, contorno,
    texto, ícone, fundo, borda) -- pra um botão invisível por cima de algo
    desenhado numa imagem de fundo. `text` (+ cor/tamanho) escreve o
    rótulo do botão no padrão "dual-entry" do template oficial
    (button.md). `fill_color` pinta o botão (sem ele, o Desktop usa a cor
    padrão do tema, em geral azul) e aplica o "render contract" da mesma
    doc: fundo/borda do container e contorno desligados, forma
    'rectangleRounded' (`corner_radius` = arredondamento) e ícone à
    esquerda, pra o preenchimento ir de borda a borda.

    CONFIRMADO AO VIVO: criamos um botão de navegação de página
    manualmente pela UI do Desktop (Inserir > Botões > Em branco),
    salvamos, e comparamos o `visual.json` resultante byte a byte com o
    que esta função gerava. Achado: o bloco `visualLink` (com
    `show`/`type`/`navigationSection`/`bookmark`) NÃO fica em
    `objects.visualLink` como o schema visualConfiguration/2.3.0
    sugeria -- fica em `visualContainerObjects.visualLink`, irmão de
    `objects` (mesmo nível de `visualContainerObjects.title`, usado por
    `set_visual_title`). Os nomes de propriedade e o valor
    `"PageNavigation"`/`"Bookmark"` de `type` bateram exatamente com o
    esperado. Depois da correção, um botão criado por esta função foi
    testado ao vivo (clique no modo de visualização) e navegou
    corretamente -- ver README, seção "Validação real". O texto do
    botão não é escrito por esta função; ajuste manualmente no Desktop
    por enquanto.

    Args:
        pbip_path: Caminho para a pasta ou arquivo .pbip do projeto.
        page_name: Página onde o botão será adicionado.
        x: Posição horizontal (esquerda) em pixels.
        y: Posição vertical (topo) em pixels.
        width: Largura em pixels.
        height: Altura em pixels.
        target_type: "page" (navega para uma página, `target` é o
            `page_name` interno) ou "bookmark" (aplica um bookmark,
            `target` é o `bookmark_name`).
        target: Página ou bookmark de destino, conforme `target_type`.

    Returns:
        Dict com o nome do botão criado e o destino configurado.

    Raises:
        PageNotFoundError: `page_name` não existe no relatório.
        InvalidVisualRoleError: `target_type` não é "page" nem "bookmark".
    """
    if target_type not in _NAVIGATION_TARGET_KEYS:
        raise InvalidVisualRoleError(
            f"target_type '{target_type}' inválido -- use 'page', 'bookmark' ou 'clear_slicers'."
        )
    if _NAVIGATION_TARGET_KEYS[target_type] is not None and not target:
        raise InvalidVisualRoleError(f"target_type '{target_type}' precisa de `target` (página ou bookmark).")
    if text_color is not None and not text_color.startswith("#"):
        raise InvalidVisualRoleError(f"text_color precisa começar com '#', recebido '{text_color}'.")
    if fill_color is not None:
        if not re.fullmatch(r"#[0-9A-Fa-f]{6}", fill_color):
            raise InvalidVisualRoleError(f"fill_color precisa ser hex '#RRGGBB', recebido '{fill_color}'.")
        if transparent:
            raise InvalidVisualRoleError("fill_color não combina com transparent=True (botão invisível).")
    if corner_radius is not None and corner_radius < 0:
        raise InvalidVisualRoleError(f"corner_radius não pode ser negativo, recebido {corner_radius}.")
    icon_source = None
    if icon_path is not None:
        from visuals import formatting

        icon_source = formatting._check_image_file(icon_path)

    report_dir = project.resolve_report_dir(pbip_path)
    definition_dir = project.get_definition_dir(report_dir)
    page_dir = resolve_page_dir(definition_dir / "pages", page_name)
    if not page_dir.is_dir():
        raise PageNotFoundError(f"Página '{page_name}' não existe em '{report_dir}'.")

    visual_name = uuid.uuid4().hex[:20]
    instance = build_navigation_button_json(
        visual_name=visual_name, x=x, y=y, width=width, height=height,
        target_type=target_type, target=target,
    )
    off = [{"properties": {"show": _literal(False)}}]
    if transparent:
        instance["visual"]["objects"] = {obj: [dict(e) for e in off] for obj in ("fill", "outline", "text", "icon")}
        instance["visual"]["visualContainerObjects"]["background"] = [dict(e) for e in off]
        instance["visual"]["visualContainerObjects"]["border"] = [dict(e) for e in off]
    if fill_color is not None:
        # button.md: fill dual-entry + render contract (container sem fundo/
        # borda, sem contorno, rectangleRounded, ícone à esquerda)
        objects = instance["visual"].setdefault("objects", {})
        objects["fill"] = [
            {"properties": {"show": _literal(True)}},
            {"properties": {"fillColor": {"solid": {"color": _literal(f"'{fill_color}'")}}}, "selector": {"id": "default"}},
        ]
        objects["outline"] = [dict(e) for e in off]
        shape_base: dict[str, Any] = {"tileShape": _literal("'rectangleRounded'")}
        if corner_radius is not None:
            shape_base["roundEdge"] = _literal(f"{int(corner_radius)}L")
        objects["shape"] = [
            {"properties": shape_base},
            {"properties": {"tileShape": _literal("'rectangleRounded'")}, "selector": {"id": "default"}},
        ]
        if icon_path is None:
            objects["icon"] = [
                {"properties": {"show": _literal(False)}},
                {"properties": {"placement": _literal("'left'")}, "selector": {"id": "default"}},
            ]
        instance["visual"]["visualContainerObjects"]["background"] = [dict(e) for e in off]
        instance["visual"]["visualContainerObjects"]["border"] = [dict(e) for e in off]
    if text is not None:
        style: dict[str, Any] = {"text": _literal("'" + text.replace("'", "''") + "'")}
        if text_color is not None:
            style["fontColor"] = {"solid": {"color": _literal(f"'{text_color}'")}}
        if text_size is not None:
            style["fontSize"] = _literal(f"{text_size}D")
        instance["visual"].setdefault("objects", {})["text"] = [
            {"properties": {"show": _literal(True)}},
            {"properties": style, "selector": {"id": "default"}},
        ]
    icon_item = None
    if icon_source is not None:
        # formato copiado do que o Desktop gravou (comparação de 2026-09-30):
        # uma entrada só, selector default, shapeType 'custom' + image.image
        from visuals import formatting

        icon_item, _ = formatting._register_image(report_dir, definition_dir, icon_source)
        instance["visual"].setdefault("objects", {})["icon"] = [{"properties": {
            "shapeType": _literal("'custom'"),
            "image": {"image": {
                "name": _literal("'" + icon_source.name.replace("'", "''") + "'"),
                "url": {"expr": {"ResourcePackageItem": {
                    "PackageName": "RegisteredResources", "PackageType": 1, "ItemName": icon_item,
                }}},
                "scaling": _literal("'Normal'"),
            }},
        }, "selector": {"id": "default"}}]

    layer = _next_layer(page_dir)
    instance["position"].update(z=layer, tabOrder=layer)
    visual_dir = page_dir / "visuals" / visual_name
    visual_dir.mkdir(parents=True)
    (visual_dir / "visual.json").write_text(
        json.dumps(instance, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    result = {
        "visual_name": visual_name, "page_name": page_name,
        "target_type": target_type, "target": target,
    }
    if icon_item is not None:
        result["icon"] = icon_item
    return result


def build_navigation_button_json(
    visual_name: str,
    x: float,
    y: float,
    width: float,
    height: float,
    target_type: str,
    target: str | None,
) -> dict[str, Any]:
    """Monta o dict de um botão de navegação. Função pura -- não toca
    disco. Ver aviso de melhor-esforço em add_navigation_button."""
    target_key = _NAVIGATION_TARGET_KEYS[target_type]
    action_type = _NAVIGATION_ACTION_TYPES[target_type]
    link: dict[str, Any] = {"show": _literal(True), "type": _literal(f"'{action_type}'")}
    if target_key is not None:
        link[target_key] = _literal(f"'{target}'")

    return {
        "$schema": VISUAL_CONTAINER_SCHEMA,
        "name": visual_name,
        "position": {
            "x": x, "y": y, "width": width, "height": height, "z": 0, "tabOrder": 0,
        },
        "visual": {
            "visualType": "actionButton",
            "visualContainerObjects": {
                "visualLink": [{"properties": link}]
            },
        },
    }


def _literal(value: bool | str) -> dict[str, Any]:
    if isinstance(value, bool):
        return {"expr": {"Literal": {"Value": "true" if value else "false"}}}
    return {"expr": {"Literal": {"Value": value}}}


def set_visual_color(
    pbip_path: str,
    page_name: str,
    visual_name: str,
    query_ref: str,
    hex_color: str,
    value: Any = None,
) -> dict[str, Any]:
    """Define a cor de uma série/categoria específica dentro de um
    visual (ex: "Vendas.Total Vendas" sempre azul), via o objeto
    `dataPoint` com um seletor por `metadata` -- padrão confirmado
    contra a referência oficial da Microsoft para autoria de PBIR
    (skills-for-fabric/.../cartesian.md, seção "dataPoint — Color
    Assignment"): usa `Literal` hex, não `ThemeDataColor`, porque
    `ThemeDataColor` com seletor de metadata pode resolver pra cor
    errada silenciosamente.

    `query_ref` precisa ser exatamente o valor já usado em `fields` ao
    criar o visual (ex: "Vendas.Total Vendas") -- é o mesmo `queryRef`
    que build_visual_json grava em cada projeção; chamar de novo com o
    mesmo `query_ref` substitui a cor anterior em vez de duplicar.

    Com `value`: pinta UM ITEM de uma coluna de legenda/categoria (ex:
    query_ref="Inteligencia de Tempo.Calculo", value="PY") -- selector
    `data` -> `scopeId` -> `Comparison` (ComparisonKind 0), doc oficial
    formatting.md ("Only ComparisonKind: 0 (Equal) is honored"). Achado na
    réplica de dashboard: a legenda de um calculation group ficava com as
    cores do tema.

    Raises:
        PageNotFoundError: `page_name` não existe no relatório.
        VisualNotFoundError: `visual_name` não existe em `page_name`.
        InvalidVisualRoleError: `hex_color` não começa com "#".
    """
    if not hex_color.startswith("#"):
        raise InvalidVisualRoleError(
            f"hex_color precisa começar com '#' (ex: '#2E86AB'), recebido '{hex_color}'."
        )

    visual_dir = _resolve_visual_dir(pbip_path, page_name, visual_name)
    visual_json_path = visual_dir / "visual.json"
    instance = json.loads(visual_json_path.read_text(encoding="utf-8"))

    if value is not None:
        from visuals.filters import format_literal

        resolved = resolve_field(modeling_metadata.get_model_metadata(pbip_path=pbip_path), query_ref)
        if resolved.kind != "column":
            raise InvalidVisualRoleError(
                f"Cor por item (`value`) precisa de uma coluna de legenda/categoria em query_ref; "
                f"'{query_ref}' é uma medida."
            )
        selector: dict[str, Any] = {"data": [{"scopeId": {"Comparison": {
            "ComparisonKind": 0,
            "Left": {"Column": {"Expression": {"SourceRef": {"Entity": resolved.entity}}, "Property": resolved.property}},
            "Right": {"Literal": {"Value": format_literal(value, resolved.data_type)}},
        }}}]}
    else:
        selector = {"metadata": query_ref}

    objects = instance["visual"].setdefault("objects", {})
    data_points = objects.setdefault("dataPoint", [])
    fill = {"solid": {"color": {"expr": {"Literal": {"Value": f"'{hex_color}'"}}}}}

    entry = next((d for d in data_points if d.get("selector") == selector), None)
    if entry is not None:
        entry["properties"]["fill"] = fill
    else:
        data_points.append({"properties": {"fill": fill}, "selector": selector})

    visual_json_path.write_text(
        json.dumps(instance, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    result = {
        "visual_name": visual_name, "page_name": page_name,
        "query_ref": query_ref, "color": hex_color,
    }
    if value is not None:
        result["value"] = value
    return result


def expand_decomposition_tree(
    pbip_path: str, page_name: str, visual_name: str, path: list[Any]
) -> dict[str, Any]:
    """Abre os níveis de uma árvore de decomposição: o 1º nível ("Explicar
    por") sempre abre; cada valor em `path` abre o item daquele nível pro
    próximo (ex: path=["Channel Partners"] abre Segmento e, dentro de
    Channel Partners, País).

    Formato copiado do Desktop (técnica de comparação, 2026-10-01): `active`
    em cada projeção de ExplainBy + `visual.expansionStates` com um nível
    por campo (`isPinned` nos abertos, `identityKeys` nos que têm item
    aberto) e o item em `root.children[].identityValues` (`isToggled`).
    CONFIRMADO com 1 item aberto; mais de 1 (filhos aninhados em
    `children`) é melhor esforço, mesmo padrão dos slicers hierárquicos."""
    from visuals.filters import format_literal

    visual_json_path = _resolve_visual_dir(pbip_path, page_name, visual_name) / "visual.json"
    instance = json.loads(visual_json_path.read_text(encoding="utf-8"))
    if instance["visual"]["visualType"] != "decompositionTreeVisual":
        raise InvalidVisualRoleError(
            f"'{visual_name}' não é uma árvore de decomposição ({instance['visual']['visualType']})."
        )
    projections = instance["visual"]["query"]["queryState"]["ExplainBy"]["projections"]
    if len(path) > len(projections) - 1:
        raise InvalidVisualRoleError(
            f"A árvore tem {len(projections)} níveis em ExplainBy; `path` abre no máximo "
            f"{len(projections) - 1} item(ns) (recebido {len(path)})."
        )

    model_metadata = modeling_metadata.get_model_metadata(pbip_path=pbip_path)
    open_levels = len(path) + 1
    levels = []
    for index, projection in enumerate(projections):
        projection["active"] = index < open_levels
        level: dict[str, Any] = {"queryRefs": [projection["queryRef"]], "isCollapsed": True}
        if index < len(path):
            level["identityKeys"] = [projection["field"]]
        if index < open_levels:
            level["isPinned"] = True
        levels.append(level)

    state: dict[str, Any] = {"roles": ["ExplainBy"], "levels": levels}
    children: list[dict[str, Any]] = []
    node_list = children
    for index, value in enumerate(path):
        resolved = resolve_field(model_metadata, projections[index]["queryRef"])
        node = {"identityValues": [{"Literal": {"Value": format_literal(value, resolved.data_type)}}], "isToggled": True}
        node_list.append(node)
        if index + 1 < len(path):
            node["children"] = []
            node_list = node["children"]
    if children:
        state["root"] = {"children": children}
    instance["visual"]["expansionStates"] = [state]

    visual_json_path.write_text(json.dumps(instance, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return {"visual_name": visual_name, "page_name": page_name,
            "open_levels": [p["queryRef"] for p in projections[:open_levels]], "path": list(path)}


def set_visual_field_name(
    pbip_path: str, page_name: str, visual_name: str, field: str, display_name: str
) -> dict[str, Any]:
    """Renomeia um campo SÓ neste visual (cabeçalho de coluna, legenda,
    eixo) -- o "Renomear para este visual" do Desktop. `display_name=""`
    volta ao nome do modelo. Fonte: schema oficial visualConfiguration
    (RoleProjection.displayName: "An override for display name")."""
    visual_json_path = _resolve_visual_dir(pbip_path, page_name, visual_name) / "visual.json"
    instance = json.loads(visual_json_path.read_text(encoding="utf-8"))
    query_state = instance["visual"].get("query", {}).get("queryState", {})
    matches = [p for role in query_state.values() for p in role.get("projections", []) if p.get("queryRef") == field]
    if not matches:
        refs = [p.get("queryRef") for role in query_state.values() for p in role.get("projections", [])]
        raise InvalidVisualRoleError(
            f"'{field}' não está no visual '{visual_name}'. Campos disponíveis: {', '.join(refs) or '(nenhum)'}."
        )
    for projection in matches:
        if display_name:
            projection["displayName"] = display_name
        else:
            projection.pop("displayName", None)
    visual_json_path.write_text(json.dumps(instance, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return {"visual_name": visual_name, "page_name": page_name, "field": field, "display_name": display_name or None}


def set_visual_hidden(pbip_path: str, page_name: str, visual_name: str, hidden: bool) -> dict[str, Any]:
    """Esconde (ou mostra) um visual na página -- `isHidden` na raiz do
    visual.json (schema oficial visualContainer/2.7.0). Uso típico: um
    painel que começa escondido e aparece por um bookmark de mostrar/
    esconder (create_bookmark com visible_visuals/hidden_visuals)."""
    visual_json_path = _resolve_visual_dir(pbip_path, page_name, visual_name) / "visual.json"
    instance = json.loads(visual_json_path.read_text(encoding="utf-8"))
    if hidden:
        instance["isHidden"] = True
    else:
        instance.pop("isHidden", None)
    visual_json_path.write_text(json.dumps(instance, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return {"visual_name": visual_name, "page_name": page_name, "hidden": hidden}


def set_visual_title(
    pbip_path: str,
    page_name: str,
    visual_name: str,
    text: str | None = None,
    font_size: float | None = None,
    font_color: str | None = None,
    show: bool | None = None,
    subtitle_show: bool | None = None,
    subtitle_text: str | None = None,
) -> dict[str, Any]:
    """Configura o título de um visual (texto, tamanho, cor, ou
    esconder por completo) e o subtítulo (`visualContainerObjects.
    subTitle`: mostrar/esconder, texto -- schema oficial de tema; achado
    na réplica de dashboard: o Desktop mostra um subtítulo automático
    "X e Y por Z"). Só os parâmetros passados mudam.

    Confirmado contra a referência oficial da Microsoft para autoria
    de PBIR (skills-for-fabric/.../cartesian.md, exemplo completo de
    formatação de visualContainerObjects): título fica em
    `visualContainerObjects.title`, não em `objects` -- formata o
    CONTAINER do visual (moldura), diferente de `dataPoint`
    (set_visual_color), que formata o CONTEÚDO.

    Raises:
        PageNotFoundError: `page_name` não existe no relatório.
        VisualNotFoundError: `visual_name` não existe em `page_name`.
        InvalidVisualRoleError: `font_color` não começa com "#".
    """
    if font_color is not None and not font_color.startswith("#"):
        raise InvalidVisualRoleError(
            f"font_color precisa começar com '#' (ex: '#333333'), recebido '{font_color}'."
        )

    visual_dir = _resolve_visual_dir(pbip_path, page_name, visual_name)
    visual_json_path = visual_dir / "visual.json"
    instance = json.loads(visual_json_path.read_text(encoding="utf-8"))

    container_objects = instance["visual"].setdefault("visualContainerObjects", {})
    title_entries = container_objects.setdefault("title", [{"properties": {}}])
    properties = title_entries[0].setdefault("properties", {})

    if show is not None:
        properties["show"] = _literal(show)
    if text is not None:
        properties["text"] = _literal("'" + text.replace("'", "''") + "'")
    if font_size is not None:
        properties["fontSize"] = _literal(f"{font_size}D")
    if font_color is not None:
        properties["fontColor"] = {"solid": {"color": {"expr": {"Literal": {"Value": f"'{font_color}'"}}}}}
    if not properties:
        container_objects.pop("title")

    if subtitle_show is not None or subtitle_text is not None:
        subtitle_entries = container_objects.setdefault("subTitle", [{"properties": {}}])
        subtitle_properties = subtitle_entries[0].setdefault("properties", {})
        if subtitle_show is not None:
            subtitle_properties["show"] = _literal(subtitle_show)
        if subtitle_text is not None:
            subtitle_properties["text"] = _literal("'" + subtitle_text.replace("'", "''") + "'")

    visual_json_path.write_text(
        json.dumps(instance, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    result = {
        "visual_name": visual_name, "page_name": page_name,
        "text": text, "font_size": font_size, "font_color": font_color, "show": show,
    }
    if subtitle_show is not None:
        result["subtitle_show"] = subtitle_show
    if subtitle_text is not None:
        result["subtitle_text"] = subtitle_text
    return result


_CONDITIONAL_FORMATTING_TABLE_VISUAL_TYPES = {"tableEx", "pivotTable"}
_COMPARISON_KIND = {"==": 0, ">": 1, ">=": 2, "<": 3, "<=": 4}


def _conditional_target(visual_type: str, query_ref: str) -> tuple[str, str, dict[str, Any]]:
    """Devolve (nome do objeto, chave da propriedade, seletor) pro tipo
    de visual -- confirmado contra a referência oficial da Microsoft
    para autoria de PBIR (skills-for-fabric/.../conditional-formatting.md):
    gráficos usam `dataPoint`/`fill` com seletor SEM `metadata`
    (incluir `metadata` num gráfico quebra a formatação silenciosamente);
    tabela/matriz usam `values`/`backColor` com seletor COM `data` E
    `metadata` (qualquer um dos dois sozinho falha silenciosamente)."""
    if visual_type in _CONDITIONAL_FORMATTING_TABLE_VISUAL_TYPES:
        return "values", "backColor", {
            "data": [{"dataViewWildcard": {"matchingOption": 1}}],
            "metadata": query_ref,
        }
    return "dataPoint", "fill", {"data": [{"dataViewWildcard": {"matchingOption": 0}}]}


def _resolve_field_node(pbip_path: str, query_ref: str) -> tuple[dict[str, Any], str]:
    """Resolve `query_ref` contra o modelo e devolve o nó `Measure`/
    `Column` (mesma forma de _projection_json) mais o query_ref
    normalizado -- reaproveita a validação já usada por add_visual, não
    reinventa."""
    model_metadata = modeling_metadata.get_model_metadata(pbip_path=pbip_path)
    resolved = resolve_field(model_metadata, query_ref)
    kind_key = "Column" if resolved.kind == "column" else "Measure"
    field_node = {
        kind_key: {"Expression": {"SourceRef": {"Entity": resolved.entity}}, "Property": resolved.property}
    }
    return field_node, resolved.query_ref


def set_visual_color_gradient(
    pbip_path: str,
    page_name: str,
    visual_name: str,
    query_ref: str,
    min_color: str,
    max_color: str,
    mid_color: str | None = None,
    min_value: float | None = None,
    mid_value: float | None = None,
    max_value: float | None = None,
    null_strategy: str = "noColor",
) -> dict[str, Any]:
    """Aplica um gradiente de cor (formatação condicional contínua) a
    um visual, baseado no valor de `query_ref`. Sem `mid_color`: 2
    pontos (mínimo -> máximo), bom pra magnitude simples (ex: vendas).
    Com `mid_color` (e `min_value`/`mid_value`/`max_value`, todos
    obrigatórios juntos): 3 pontos (ruim -> neutro -> bom), bom pra
    variação/desempenho vs meta.

    Confirmado contra a referência oficial da Microsoft para autoria
    de PBIR (skills-for-fabric/.../conditional-formatting.md) --
    inclui os "gotchas" que causam falha silenciosa (seletor errado
    por tipo de visual), não inventado.

    Raises:
        PageNotFoundError: `page_name` não existe no relatório.
        VisualNotFoundError: `visual_name` não existe em `page_name`.
        UnknownFieldError: `query_ref` não existe no modelo.
        InvalidVisualRoleError: alguma cor não começa com "#", ou
            `mid_color` foi dado sem os três valores obrigatórios.
    """
    for color in (min_color, max_color, mid_color):
        if color is not None and not color.startswith("#"):
            raise InvalidVisualRoleError(
                f"Cor precisa começar com '#' (ex: '#2E86AB'), recebido '{color}'."
            )
    if mid_color is not None and (min_value is None or mid_value is None or max_value is None):
        raise InvalidVisualRoleError(
            "Gradiente de 3 pontos (mid_color) exige min_value, mid_value e max_value."
        )

    visual_dir = _resolve_visual_dir(pbip_path, page_name, visual_name)
    visual_json_path = visual_dir / "visual.json"
    instance = json.loads(visual_json_path.read_text(encoding="utf-8"))
    visual_type = instance["visual"]["visualType"]

    input_node, normalized_query_ref = _resolve_field_node(pbip_path, query_ref)

    if mid_color is None:
        fill_rule = {
            "linearGradient2": {
                "min": {"color": {"Literal": {"Value": f"'{min_color}'"}}},
                "max": {"color": {"Literal": {"Value": f"'{max_color}'"}}},
                "nullColoringStrategy": {"strategy": {"Literal": {"Value": f"'{null_strategy}'"}}},
            }
        }
        gradient_name = "linearGradient2"
    else:
        fill_rule = {
            "linearGradient3": {
                "min": {
                    "color": {"Literal": {"Value": f"'{min_color}'"}},
                    "value": {"Literal": {"Value": f"{min_value}D"}},
                },
                "mid": {
                    "color": {"Literal": {"Value": f"'{mid_color}'"}},
                    "value": {"Literal": {"Value": f"{mid_value}D"}},
                },
                "max": {
                    "color": {"Literal": {"Value": f"'{max_color}'"}},
                    "value": {"Literal": {"Value": f"{max_value}D"}},
                },
                "nullColoringStrategy": {"strategy": {"Literal": {"Value": f"'{null_strategy}'"}}},
            }
        }
        gradient_name = "linearGradient3"

    color_expr = {"expr": {"FillRule": {"Input": input_node, "FillRule": fill_rule}}}

    object_name, property_key, selector = _conditional_target(visual_type, normalized_query_ref)
    objects = instance["visual"].setdefault("objects", {})
    entries = objects.setdefault(object_name, [])
    entries.append({"properties": {property_key: color_expr}, "selector": selector})

    visual_json_path.write_text(
        json.dumps(instance, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    return {
        "visual_name": visual_name, "page_name": page_name,
        "query_ref": normalized_query_ref, "gradient": gradient_name,
    }


def set_visual_conditional_color(
    pbip_path: str,
    page_name: str,
    visual_name: str,
    query_ref: str,
    rules: list[dict[str, Any]],
    default_color: str,
) -> dict[str, Any]:
    """Aplica cores discretas por regra (formatação condicional
    baseada em limiares), avaliadas na ordem dada -- a primeira regra
    cuja condição bater define a cor; `default_color` cobre o que não
    bateu em nenhuma.

    Confirmado contra a referência oficial da Microsoft para autoria
    de PBIR (skills-for-fabric/.../conditional-formatting.md).

    Args:
        pbip_path: Caminho para a pasta ou arquivo .pbip do projeto.
        page_name: Página onde o visual está.
        visual_name: Visual a formatar.
        query_ref: Campo cujo valor decide a cor (ex: "Vendas.Total Vendas").
        rules: Lista de `{"operator": "<"|"<="|">"|">="|"==", "value": número, "color": "#hex"}`.
        default_color: Cor quando nenhuma regra bate.

    Returns:
        Dict confirmando quantas regras foram escritas.

    Raises:
        PageNotFoundError: `page_name` não existe no relatório.
        VisualNotFoundError: `visual_name` não existe em `page_name`.
        UnknownFieldError: `query_ref` não existe no modelo.
        InvalidVisualRoleError: operador ou cor inválidos.
    """
    if not default_color.startswith("#"):
        raise InvalidVisualRoleError(
            f"Cor precisa começar com '#' (ex: '#FFFFFF'), recebido '{default_color}'."
        )
    for rule in rules:
        if rule["operator"] not in _COMPARISON_KIND:
            raise InvalidVisualRoleError(
                f"Operador '{rule['operator']}' inválido -- use um de {sorted(_COMPARISON_KIND)}."
            )
        if not rule["color"].startswith("#"):
            raise InvalidVisualRoleError(
                f"Cor precisa começar com '#' (ex: '#2E86AB'), recebido '{rule['color']}'."
            )

    visual_dir = _resolve_visual_dir(pbip_path, page_name, visual_name)
    visual_json_path = visual_dir / "visual.json"
    instance = json.loads(visual_json_path.read_text(encoding="utf-8"))
    visual_type = instance["visual"]["visualType"]

    field_node, normalized_query_ref = _resolve_field_node(pbip_path, query_ref)

    cases = [
        {
            "Condition": {
                "Comparison": {
                    "ComparisonKind": _COMPARISON_KIND[rule["operator"]],
                    "Left": field_node,
                    "Right": {"Literal": {"Value": f"{rule['value']}D"}},
                }
            },
            "Value": {"Literal": {"Value": f"'{rule['color']}'"}},
        }
        for rule in rules
    ]
    color_expr = {
        "expr": {"Conditional": {"Cases": cases, "DefaultValue": {"Literal": {"Value": f"'{default_color}'"}}}}
    }

    objects = instance["visual"].setdefault("objects", {})
    if visual_type == "cardVisual":
        # Cartão atual: cor do VALOR -- doc oficial conditional-formatting-part-03.md
        # (cardVisual -> value.fontColor, selector {"id": "default"}) e forma
        # `solid.color.expr.Conditional` da part-05. Entra na entrada default
        # que já existe (set_card_style), em vez de duplicar o seletor.
        selector = {"id": "default"}
        entries = objects.setdefault("value", [])
        entry = next((e for e in entries if e.get("selector") == selector), None)
        if entry is None:
            entry = {"properties": {}, "selector": selector}
            entries.append(entry)
        entry.setdefault("properties", {})["fontColor"] = {"solid": {"color": color_expr}}
    else:
        object_name, property_key, selector = _conditional_target(visual_type, normalized_query_ref)
        entries = objects.setdefault(object_name, [])
        entries.append({"properties": {property_key: color_expr}, "selector": selector})

    visual_json_path.write_text(
        json.dumps(instance, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    return {
        "visual_name": visual_name, "page_name": page_name,
        "query_ref": normalized_query_ref, "rules_count": len(rules),
    }


def set_visual_field_parameter(
    pbip_path: str,
    page_name: str,
    visual_name: str,
    role: str,
    field_parameter_table: str,
    display_column: str,
    default_field: str,
) -> dict[str, Any]:
    """Vincula um `role` de um visual já existente a um field parameter
    (ver modeling.field_parameters.create_field_parameter) -- o visual
    passa a reagir à seleção de um slicer ligado ao parâmetro, em vez de
    mostrar um campo fixo.

    CONFIRMADO AO VIVO: comparamos com um cartão vinculado a um field
    parameter manualmente pela UI do Desktop (Modelagem > Novo
    parâmetro > Campos, depois arrastado pro cartão). Achado -- a
    projeção do role NÃO referencia o parâmetro diretamente; referencia
    o campo que estava selecionado no momento (aqui, `default_field`,
    com `displayName` incluído, coisa que as outras projeções deste
    projeto não têm). Quem marca essa projeção como controlada pelo
    parâmetro é `fieldParameters`, irmão de `projections` **dentro do
    próprio objeto do `role`** (`query.queryState.<role>.fieldParameters`
    -- confirmado pelo próprio schema oficial `visualContainer/2.7.0`,
    que valida cada role como `{projections, fieldParameters?, showAll?}`
    com `additionalProperties: false`; colocar `fieldParameters` direto
    em `queryState` -- o que pareceu fazer sentido antes de checar o
    schema -- falha a validação). `fieldParameters` é uma lista de: um
    `Column` apontando pra `display_column` de `field_parameter_table`
    (mesma forma de referência de campo de sempre), mais `index` (posição
    da projeção dentro do `role`) e `length` (quantas projeções controla
    -- sempre 1 no exemplo capturado, único caso confirmado). Escopo
    desta função: um `role` com uma única projeção controlada por um
    parâmetro só -- vincular dois roles a parâmetros diferentes no mesmo
    visual não foi testado.

    Args:
        pbip_path: Caminho para a pasta ou arquivo .pbip do projeto.
        page_name: Página onde o visual está.
        visual_name: Visual a vincular.
        role: Role do visual a controlar (ex: "Values" num cartão).
        field_parameter_table: Tabela de field parameter (criada por
            create_field_parameter, ou manualmente no Desktop).
        display_column: Coluna de exibição da tabela de parâmetro (o
            `display_column` que create_field_parameter devolveu, ou o
            nome da coluna visível no Desktop pra uma tabela criada
            manualmente).
        default_field: Campo a mostrar antes de qualquer seleção (ex:
            "financials.Total Sales") -- precisa ser um dos campos
            incluídos no parâmetro, mas isso não é validado aqui.

    Raises:
        PageNotFoundError: `page_name` não existe no relatório.
        VisualNotFoundError: `visual_name` não existe em `page_name`.
        UnknownFieldError: `default_field` não existe no modelo.
    """
    visual_dir = _resolve_visual_dir(pbip_path, page_name, visual_name)
    visual_json_path = visual_dir / "visual.json"
    instance = json.loads(visual_json_path.read_text(encoding="utf-8"))

    model_metadata = modeling_metadata.get_model_metadata(pbip_path=pbip_path)
    resolved = resolve_field(model_metadata, default_field)

    projection = _projection_json(resolved)
    projection["displayName"] = resolved.native_query_ref

    query_state = instance["visual"].setdefault("query", {}).setdefault("queryState", {})
    query_state[role] = {
        "projections": [projection],
        "fieldParameters": [
            {
                "parameterExpr": {
                    "Column": {
                        "Expression": {"SourceRef": {"Entity": field_parameter_table}},
                        "Property": display_column,
                    }
                },
                "index": 0,
                "length": 1,
            }
        ],
    }

    visual_json_path.write_text(
        json.dumps(instance, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    return {
        "visual_name": visual_name, "page_name": page_name, "role": role,
        "field_parameter_table": field_parameter_table, "default_field": resolved.query_ref,
    }


def _resolve_visual_dir(pbip_path: str, page_name: str, visual_name: str) -> Path:
    """Resolve a pasta de um visual já existente.

    `visual_name` normalmente vem de um add_visual anterior (sempre um
    hex gerado por uuid.uuid4(), portanto seguro), mas as funções que
    chegam aqui (delete_visual, update_visual, set_visual_color, etc.)
    o recebem como parâmetro comum de tool -- nada impede quem chama de
    passar qualquer string. Sem validar, um visual_name tipo
    "../../../../pasta_qualquer" escaparia de `visuals/` (path
    traversal) quando concatenado abaixo -- especialmente grave em
    delete_visual, que faz shutil.rmtree no resultado. Mesma validação
    (e mesma defesa em profundidade com is_relative_to) que
    visuals.names.resolve_page_dir já aplica a page_name.
    """
    if not is_valid_object_name(visual_name):
        raise InvalidResourceNameError("visual_name", visual_name)

    report_dir = project.resolve_report_dir(pbip_path)
    definition_dir = project.get_definition_dir(report_dir)
    page_dir = resolve_page_dir(definition_dir / "pages", page_name)
    if not page_dir.is_dir():
        raise PageNotFoundError(
            f"Página '{page_name}' não existe em '{report_dir}'."
        )

    visuals_dir = page_dir / "visuals"
    visual_dir = visuals_dir / visual_name
    if not visual_dir.resolve().is_relative_to(visuals_dir.resolve()):
        raise InvalidResourceNameError("visual_name", visual_name)
    if not visual_dir.is_dir():
        raise VisualNotFoundError(visual_name=visual_name, page_name=page_name)
    return visual_dir


def _extract_textbox_text(instance: dict[str, Any]) -> str:
    paragraphs = instance["visual"]["objects"]["general"][0]["properties"]["paragraphs"]
    return "\n".join(p["textRuns"][0]["value"] for p in paragraphs)


def build_visual_json(
    visual_name: str,
    visual_type: str,
    x: float,
    y: float,
    width: float,
    height: float,
    resolved_fields: dict[str, list[ResolvedField]],
) -> dict[str, Any]:
    """Monta o dict de um visual.json válido segundo o schema
    visualContainer/2.7.0. Função pura -- não toca disco."""
    query_state = {
        role_name: {"projections": [_projection_json(field) for field in role_fields]}
        for role_name, role_fields in resolved_fields.items()
    }
    # Hierarquia de drill (doc oficial cartesian.md, "Category Drill
    # Hierarchy"): `active: true` só no primeiro nível = abre no topo. O
    # catálogo só deixa mais de um campo em Category nos gráficos
    # cartesianos (tabela/matriz não usam Category -- lá `active` some
    # colunas, segundo a mesma doc).
    category = query_state.get("Category", {}).get("projections", [])
    if len(category) > 1:
        category[0]["active"] = True

    return {
        "$schema": VISUAL_CONTAINER_SCHEMA,
        "name": visual_name,
        "position": {
            "x": x,
            "y": y,
            "width": width,
            "height": height,
            "z": 0,
            "tabOrder": 0,
        },
        "visual": {
            "visualType": visual_type,
            "query": {"queryState": query_state},
        },
    }


def build_textbox_json(
    visual_name: str,
    x: float,
    y: float,
    width: float,
    height: float,
    text: str,
) -> dict[str, Any]:
    """Monta o dict de um visual.json de textbox válido segundo o schema
    visualContainer/2.7.0 (+ formattingObjectDefinitions/1.5.0 para
    `objects.general[].properties.paragraphs`). Função pura -- não toca
    disco. Sem `query`: textbox não referencia campo nenhum do modelo."""
    paragraphs = [
        {
            "textRuns": [{"value": line, "textStyle": dict(_DEFAULT_TEXT_STYLE)}],
            "horizontalTextAlignment": "left",
        }
        for line in text.split("\n")
    ]

    return {
        "$schema": VISUAL_CONTAINER_SCHEMA,
        "name": visual_name,
        "position": {
            "x": x,
            "y": y,
            "width": width,
            "height": height,
            "z": 0,
            "tabOrder": 0,
        },
        "visual": {
            "visualType": "textbox",
            "objects": {"general": [{"properties": {"paragraphs": paragraphs}}]},
        },
    }


def _projection_json(field: ResolvedField) -> dict[str, Any]:
    kind_key = "Column" if field.kind == "column" else "Measure"
    return {
        "queryRef": field.query_ref,
        "nativeQueryRef": field.native_query_ref,
        "field": {
            kind_key: {
                "Expression": {"SourceRef": {"Entity": field.entity}},
                "Property": field.property,
            }
        },
    }
