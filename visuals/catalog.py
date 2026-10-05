"""Registry declarativo dos tipos de visual suportados e seus roles.

Cada entrada de VISUAL_TYPES é dado, não código: adicionar um 8º tipo é
uma linha nova neste dicionário, não uma função nova. O validador
(visuals.validator) e o escritor de visual.json (visuals.visual_writer)
são genéricos sobre esse registry -- nenhum dos dois conhece "card" ou
"lineChart" por nome, só sabe seguir a especificação de roles.

Os nomes de role (`Category`, `Series`, `Y`, `Values`) são os nomes
internos reais usados pelos visuais nativos do Power BI em
`query.queryState` dentro de visual.json -- não são inventados por este
projeto. Confirmados contra exemplos públicos de PBIR e contra
capabilities.json de visuais nativos equivalentes (ex.: Series é o nome
interno do role de legenda em gráficos de coluna/barra/linha, mesmo a
UI mostrando "Legenda").
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from errors import UnknownVisualTypeError

FieldKind = str  # "column" ou "measure"


@dataclass(frozen=True, slots=True)
class Role:
    """Especificação de um role dentro de um tipo de visual: quantos
    campos ele aceita e que tipo de campo (coluna e/ou medida)."""

    min_fields: int
    max_fields: int | None  # None = sem limite
    allowed_kinds: tuple[FieldKind, ...]


@dataclass(frozen=True, slots=True)
class VisualSpec:
    """Especificação completa de um tipo de visual: seus roles.

    `is_text_visual=True` marca um visual como "textbox": não usa
    query/fields como os demais -- o conteúdo é texto direto, montado
    por visuals.visual_writer.build_textbox_json em vez de
    build_visual_json. `roles` fica vazio nesse caso."""

    roles: dict[str, Role] = field(default_factory=dict)
    is_text_visual: bool = False


_CATEGORY_COLUMN_ONLY = Role(min_fields=1, max_fields=1, allowed_kinds=("column",))
# Gráficos cartesianos: vários campos em Category = hierarquia de drill
# (doc oficial cartesian.md, "Category Drill Hierarchy"); build_visual_json
# marca `active: true` só no primeiro, o gráfico abre no nível de cima.
_CATEGORY_DRILL = Role(min_fields=1, max_fields=None, allowed_kinds=("column",))
# Campos extras na dica de ferramenta (doc oficial cartesian.md: role
# "Tooltips", kind Measure, opcional na família cartesiana).
_TOOLTIPS_OPTIONAL = Role(min_fields=0, max_fields=None, allowed_kinds=("measure",))
_SERIES_OPTIONAL_COLUMN = Role(min_fields=0, max_fields=1, allowed_kinds=("column",))
_Y_MEASURE_OR_COLUMN_MULTI = Role(min_fields=1, max_fields=None, allowed_kinds=("measure", "column"))

VISUAL_TYPES: dict[str, VisualSpec] = {
    "card": VisualSpec(
        roles={"Values": Role(min_fields=1, max_fields=1, allowed_kinds=("measure", "column"))}
    ),
    "clusteredColumnChart": VisualSpec(
        roles={
            "Category": _CATEGORY_DRILL,
            "Tooltips": _TOOLTIPS_OPTIONAL,
            "Y": _Y_MEASURE_OR_COLUMN_MULTI,
            "Series": _SERIES_OPTIONAL_COLUMN,
        }
    ),
    "clusteredBarChart": VisualSpec(
        roles={
            "Category": _CATEGORY_DRILL,
            "Tooltips": _TOOLTIPS_OPTIONAL,
            "Y": _Y_MEASURE_OR_COLUMN_MULTI,
            "Series": _SERIES_OPTIONAL_COLUMN,
        }
    ),
    "lineChart": VisualSpec(
        roles={
            "Category": _CATEGORY_DRILL,
            "Tooltips": _TOOLTIPS_OPTIONAL,
            "Y": _Y_MEASURE_OR_COLUMN_MULTI,
            "Series": _SERIES_OPTIONAL_COLUMN,
        }
    ),
    "donutChart": VisualSpec(
        roles={
            "Category": _CATEGORY_COLUMN_ONLY,
            "Y": _Y_MEASURE_OR_COLUMN_MULTI,
        }
    ),
    "tableEx": VisualSpec(
        roles={"Values": Role(min_fields=1, max_fields=None, allowed_kinds=("measure", "column"))}
    ),
    "slicer": VisualSpec(
        roles={"Values": Role(min_fields=1, max_fields=1, allowed_kinds=("column",))}
    ),
    "textbox": VisualSpec(roles={}, is_text_visual=True),
    # advancedSlicerVisual = slicer de BOTÕES (ladrilhos). Doc oficial
    # slicers.md: "'Values' only allow one field with Column Expression.
    # 'Label' only allow one field with Measure or Aggregation". Formatação
    # em formatting.set_button_slicer_style.
    "advancedSlicerVisual": VisualSpec(
        roles={
            "Values": Role(min_fields=1, max_fields=1, allowed_kinds=("column",)),
            "Label": Role(min_fields=0, max_fields=1, allowed_kinds=("measure",)),
        }
    ),
    # pivotTable é o nome interno real do visual "matriz" no PBIR --
    # confirmado contra a referência oficial da Microsoft para autoria
    # de PBIR (skills-for-fabric/.../table.md), não suposto.
    "pivotTable": VisualSpec(
        roles={
            "Rows": Role(min_fields=0, max_fields=None, allowed_kinds=("column",)),
            "Columns": Role(min_fields=0, max_fields=None, allowed_kinds=("column",)),
            "Values": Role(min_fields=1, max_fields=None, allowed_kinds=("measure", "column")),
        }
    ),
    # waterfallChart validado ao vivo: Category/Y corretos (ver README,
    # "Validação real"). scatterChart também validado ao vivo, mas só
    # depois de corrigir um erro: a primeira tentativa usava
    # "Details"/"Legend" (nomes dos field wells na UI) e colapsou todos
    # os pontos num só -- a doc oficial de gráficos cartesianos
    # (skills-for-fabric/.../cartesian.md) mostra que TODA a família
    # usa os nomes internos "Category" + "Y", e que o que a UI chama de
    # "Legend" é internamente "Series" (confirmado para lineChart no
    # `catalog describe`). scatterChart segue a mesma convenção.
    "waterfallChart": VisualSpec(
        roles={
            "Category": Role(min_fields=1, max_fields=1, allowed_kinds=("column",)),
            "Y": Role(min_fields=1, max_fields=1, allowed_kinds=("measure", "column")),
            "Breakdown": Role(min_fields=0, max_fields=1, allowed_kinds=("column",)),
        }
    ),
    "scatterChart": VisualSpec(
        roles={
            "Category": Role(min_fields=1, max_fields=1, allowed_kinds=("column",)),
            "X": Role(min_fields=1, max_fields=1, allowed_kinds=("measure", "column")),
            "Y": Role(min_fields=1, max_fields=1, allowed_kinds=("measure", "column")),
            "Size": Role(min_fields=0, max_fields=1, allowed_kinds=("measure", "column")),
            "Series": Role(min_fields=0, max_fields=1, allowed_kinds=("column",)),
        }
    ),
    # --- Segunda rodada: mesma família cartesiana Category+Y+Series já
    # confirmada acima. columnChart/barChart CONFIRMADOS contra a doc
    # oficial (skills-for-fabric/.../cartesian.md, exemplo completo de
    # "Stacked Column Chart"). areaChart/stackedAreaChart não têm
    # exemplo completo na mesma doc, mas ela lista os quatro
    # (areaChart, lineChart, stackedAreaChart, hundredPercentStackedAreaChart)
    # como a mesma família de "visual types with lineStyles" -- alta
    # confiança, mesmo círculo de tipos.
    "columnChart": VisualSpec(
        roles={
            "Category": _CATEGORY_DRILL,
            "Tooltips": _TOOLTIPS_OPTIONAL,
            "Y": _Y_MEASURE_OR_COLUMN_MULTI,
            "Series": _SERIES_OPTIONAL_COLUMN,
        }
    ),
    "barChart": VisualSpec(
        roles={
            "Category": _CATEGORY_DRILL,
            "Tooltips": _TOOLTIPS_OPTIONAL,
            "Y": _Y_MEASURE_OR_COLUMN_MULTI,
            "Series": _SERIES_OPTIONAL_COLUMN,
        }
    ),
    "areaChart": VisualSpec(
        roles={
            "Category": _CATEGORY_DRILL,
            "Tooltips": _TOOLTIPS_OPTIONAL,
            "Y": _Y_MEASURE_OR_COLUMN_MULTI,
            "Series": _SERIES_OPTIONAL_COLUMN,
        }
    ),
    "stackedAreaChart": VisualSpec(
        roles={
            "Category": _CATEGORY_DRILL,
            "Tooltips": _TOOLTIPS_OPTIONAL,
            "Y": _Y_MEASURE_OR_COLUMN_MULTI,
            "Series": _SERIES_OPTIONAL_COLUMN,
        }
    ),
    # hundredPercentStackedColumnChart/BarChart: nome extrapolado do
    # padrão confirmado para a variante de área
    # (hundredPercentStackedAreaChart, citada na mesma doc) -- melhor
    # esforço para column/bar, pendente de validação ao vivo.
    "hundredPercentStackedColumnChart": VisualSpec(
        roles={
            "Category": _CATEGORY_DRILL,
            "Tooltips": _TOOLTIPS_OPTIONAL,
            "Y": _Y_MEASURE_OR_COLUMN_MULTI,
            "Series": _SERIES_OPTIONAL_COLUMN,
        }
    ),
    "hundredPercentStackedBarChart": VisualSpec(
        roles={
            "Category": _CATEGORY_DRILL,
            "Tooltips": _TOOLTIPS_OPTIONAL,
            "Y": _Y_MEASURE_OR_COLUMN_MULTI,
            "Series": _SERIES_OPTIONAL_COLUMN,
        }
    ),
    # pieChart: mesma forma exata do donutChart já validado ao vivo --
    # só muda a renderização (fatias em vez de rosca), a UI/PBIR são a
    # mesma família. Alta confiança.
    "pieChart": VisualSpec(
        roles={
            "Category": _CATEGORY_COLUMN_ONLY,
            "Y": _Y_MEASURE_OR_COLUMN_MULTI,
        }
    ),
    # treemap: melhor esforço -- nomes de role a partir dos field wells
    # reais da UI ("Group", "Details", "Values"), sem referência
    # oficial encontrada. Pendente de validação ao vivo.
    "treemap": VisualSpec(
        roles={
            "Group": Role(min_fields=1, max_fields=None, allowed_kinds=("column",)),
            "Details": Role(min_fields=0, max_fields=1, allowed_kinds=("column",)),
            "Values": Role(min_fields=1, max_fields=None, allowed_kinds=("measure", "column")),
        }
    ),
    # funnel: melhor esforço -- Category/Y pela convenção da família
    # (a UI mostra "Category"/"Values", e "Values" mapeia pra "Y" no
    # padrão já confirmado em lineChart). Pendente de validação ao vivo.
    "funnel": VisualSpec(
        roles={
            "Category": _CATEGORY_COLUMN_ONLY,
            "Y": Role(min_fields=1, max_fields=1, allowed_kinds=("measure", "column")),
        }
    ),
    # gauge: melhor esforço -- roles conhecidos do visual nativo
    # (Value/MinValue/MaxValue/TargetValue). Pendente de validação ao
    # vivo.
    "gauge": VisualSpec(
        roles={
            "Y": Role(min_fields=1, max_fields=1, allowed_kinds=("measure", "column")),
            "MinValue": Role(min_fields=0, max_fields=1, allowed_kinds=("measure", "column")),
            "MaxValue": Role(min_fields=0, max_fields=1, allowed_kinds=("measure", "column")),
            "TargetValue": Role(min_fields=0, max_fields=1, allowed_kinds=("measure", "column")),
        }
    ),
    # kpi: validado ao vivo, com correção. Sem "TrendLine" (testado
    # como opcional primeiro), o visual renderiza só o título, em
    # branco -- o KPI nativo precisa da linha de tendência pra calcular
    # o que mostrar. "TrendLine" é obrigatório, não opcional.
    "kpi": VisualSpec(
        roles={
            "Indicator": Role(min_fields=1, max_fields=1, allowed_kinds=("measure", "column")),
            "TrendLine": Role(min_fields=1, max_fields=1, allowed_kinds=("measure", "column")),
            "Goal": Role(min_fields=0, max_fields=1, allowed_kinds=("measure", "column")),
        }
    ),
    # cardVisual: CONFIRMADO contra a referência oficial da Microsoft
    # (skills-for-fabric/.../card.md) -- é o visual de cartão atual
    # (não o legado "card" que já temos); o role de dado se chama
    # "Data", não "Values"/"Fields". Aceita várias medidas na mesma
    # instância (o caso de "cartão multilinha"), em vez de precisar de
    # um visual multiRowCard separado (também legado).
    "cardVisual": VisualSpec(
        roles={"Data": Role(min_fields=1, max_fields=None, allowed_kinds=("measure", "column"))}
    ),
    # lineClusteredColumnComboChart (colunas + linha): MELHOR ESFORÇO nos
    # roles. A doc oficial (cartesian-part-02.md) lista o tipo na família
    # com lineStyles e o schema de tema tem visual-lineClusteredColumnComboChart,
    # mas sem exemplo de combo; "Y" (colunas) e "Y2" (linha) são os nomes do
    # visual nativo. CONFIRMADO ao vivo em 2026-10-03 (dashboard Cristallo:
    # admissões/desligamentos em colunas + quadro em linha).
    "lineClusteredColumnComboChart": VisualSpec(
        roles={
            "Category": _CATEGORY_DRILL,
            "Tooltips": _TOOLTIPS_OPTIONAL,
            "Y": Role(min_fields=1, max_fields=None, allowed_kinds=("measure", "column")),
            "Y2": Role(min_fields=0, max_fields=None, allowed_kinds=("measure", "column")),
            "Series": _SERIES_OPTIONAL_COLUMN,
        }
    ),
    # decompositionTreeVisual (árvore de decomposição): MELHOR ESFORÇO. O
    # tipo e a formatação existem no schema oficial de tema
    # (visual-decompositionTreeVisual), mas a doc de autoria PBIR não tem
    # exemplo -- os roles "Analyze" (medida) e "ExplainBy" (colunas) são os
    # nomes do visual nativo. Pendente de validação ao vivo (réplica, pág. 3).
    "decompositionTreeVisual": VisualSpec(
        roles={
            "Analyze": Role(min_fields=1, max_fields=1, allowed_kinds=("measure",)),
            "ExplainBy": Role(min_fields=1, max_fields=None, allowed_kinds=("column",)),
        }
    ),
    # azureMap: CONFIRMADO contra a referência oficial da Microsoft
    # (skills-for-fabric/.../map.md) -- é o visual de mapa atual
    # (a doc explicitamente diz para nunca usar "map"/"filledMap",
    # legados do Bing Maps).
    "azureMap": VisualSpec(
        roles={
            "Category": Role(min_fields=1, max_fields=1, allowed_kinds=("column",)),
            "Size": Role(min_fields=0, max_fields=1, allowed_kinds=("measure", "column")),
            "Series": Role(min_fields=0, max_fields=1, allowed_kinds=("column",)),
            "X": Role(min_fields=0, max_fields=1, allowed_kinds=("measure", "column")),
            "Y": Role(min_fields=0, max_fields=1, allowed_kinds=("measure", "column")),
        }
    ),
}


def get_visual_spec(visual_type: str, report_dir: Path | None = None) -> VisualSpec:
    """Devolve a especificação de `visual_type`. Com `report_dir`, também
    reconhece um visual personalizado importado nesse relatório (roles
    lidos do próprio pacote -- ver visuals.custom_visuals).

    Raises:
        UnknownVisualTypeError: `visual_type` não está no catálogo nem é
            um visual personalizado importado.
    """
    spec = VISUAL_TYPES.get(visual_type)
    if spec is None and report_dir is not None:
        from visuals import custom_visuals

        roles = custom_visuals.custom_visual_roles(Path(report_dir), visual_type)
        if roles is not None:
            return VisualSpec(roles={
                r["name"]: Role(min_fields=r["min_fields"], max_fields=r["max_fields"], allowed_kinds=tuple(r["accepts"]))
                for r in roles
            })
    if spec is None:
        raise UnknownVisualTypeError(visual_type, known_types=sorted(VISUAL_TYPES))
    return spec
