"""Primeira etapa do contrato de orquestração: reúne metadata do modelo,
schema do blueprint e catálogo de visuais para o Claude chamador decidir
o que construir.

plan_dashboard não escreve nada -- nem no modelo, nem em disco. Ele só
lê o estado atual (via modeling.metadata.get_model_metadata, que usa a
conexão XMLA ativa se houver, senão lê os arquivos .tmdl offline) e
devolve tudo que é preciso para montar um DashboardBlueprint válido.
"""

from __future__ import annotations

from typing import Any

from modeling import metadata as modeling_metadata
from orchestrator.blueprint import DashboardBlueprint
from visuals.catalog import VISUAL_TYPES

LAYOUT_OPTIONS = ["grid", "kpi_row"]

_INSTRUCTIONS = (
    "Use model_metadata para saber quais tabelas/colunas/medidas já "
    "existem. Prefira reutilizá-las; só inclua algo em new_tables/"
    "new_measures/new_relationships se realmente faltar. Cada campo "
    "referenciado em VisualSpec.fields deve usar o formato "
    "'Tabela.Coluna' ou 'Tabela.Medida' com um nome que já existe em "
    "model_metadata OU que você está criando em new_measures neste "
    "mesmo blueprint -- NÃO é possível referenciar uma coluna de uma "
    "tabela listada em new_tables neste mesmo blueprint, porque as "
    "colunas de uma tabela nova só são conhecidas depois que o Power BI "
    "Desktop avalia sua expressão M/DAX. Use visual_catalog para saber "
    "quais roles cada visual_type aceita, quantos campos cada role "
    "espera, e se aceita coluna, medida, ou ambos. Para o dashboard não "
    "sair 'cru', preencha PageSpec.title em toda página (faixa de título "
    "já formatada; os padrões bastam, só o texto é obrigatório) e, se "
    "quiser, PageSpec.background_color (ex: '#F3F2F1', cinza-claro, pra "
    "os visuais se destacarem). Para KPIs use 'cardVisual' (cartão atual; "
    "'card' é legado e a Microsoft o considera obsoleto) -- o layout "
    "kpi_row põe os dois na faixa de cima. Depois de montar o "
    "blueprint (validando contra blueprint_schema), chame "
    "apply_dashboard_blueprint."
)


def plan_dashboard(description: str, pbip_path: str) -> dict[str, Any]:
    """Devolve tudo que é preciso para montar e validar um
    DashboardBlueprint para `description`.

    Raises:
        MetadataSourceUnavailableError: nenhuma conexão XMLA ativa e
            `pbip_path` não resolve a um projeto legível.
        SemanticModelNotFoundError: `pbip_path` não resolve a uma pasta
            .SemanticModel válida (propagado por tmdl_reader, quando não
            há conexão XMLA ativa).
    """
    model_metadata = modeling_metadata.get_model_metadata(pbip_path=pbip_path)

    return {
        "description": description,
        "model_metadata": model_metadata.to_dict(),
        "blueprint_schema": DashboardBlueprint.model_json_schema(),
        "visual_catalog": _visual_catalog_dict(),
        "custom_visuals": _custom_visuals(pbip_path),
        "layout_options": LAYOUT_OPTIONS,
        "instructions": _INSTRUCTIONS,
    }


def _custom_visuals(pbip_path: str) -> list[dict[str, Any]]:
    """Visuais personalizados importados no relatório -- usáveis no
    blueprint com `visual_type` = o `visual_type` (GUID) listado aqui e
    os roles do próprio visual. Vazio se ainda não houver relatório."""
    from errors import ReportProjectNotFoundError
    from visuals import custom_visuals

    try:
        return custom_visuals.list_custom_visuals(pbip_path)
    except (ReportProjectNotFoundError, FileNotFoundError):
        return []


def _visual_catalog_dict() -> dict[str, Any]:
    """Só visuais ligados a dado -- é o que o blueprint sabe montar via
    `fields`. `textbox` (sem roles) é escrito diretamente por add_visual,
    fora do fluxo de blueprint, então não entra aqui."""
    return {
        visual_type: {
            role_name: {
                "min_fields": role.min_fields,
                "max_fields": role.max_fields,
                "allowed_kinds": list(role.allowed_kinds),
            }
            for role_name, role in spec.roles.items()
        }
        for visual_type, spec in VISUAL_TYPES.items()
        if not spec.is_text_visual
    }
