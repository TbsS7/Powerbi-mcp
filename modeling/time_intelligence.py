"""Geração de medidas DAX de inteligência de tempo (YTD, ano anterior,
crescimento %, ...) a partir de uma medida base já existente no modelo.

Cada padrão DAX usado aqui é uma das funções de inteligência de tempo
padrão do DAX (`TOTALYTD`, `TOTALQTD`, `TOTALMTD`, `SAMEPERIODLASTYEAR`,
`DATEADD`) -- documentadas na referência oficial de funções DAX da
Microsoft, não inventadas. `DATEADD`/`SAMEPERIODLASTYEAR` exigem uma
coluna de data contígua (idealmente de uma tabela marcada como tabela
de datas), mas funcionam sobre qualquer coluna DateTime -- este módulo
só confere o tipo da coluna, não se a tabela está marcada como tabela
de datas oficialmente.

Reaproveita modeling.operations.create_measure (mesma validação de
tabela/medida existente) para cada variante, com save=False, e um único
runtime.save_changes() no final -- mesmo padrão de
orchestrator.applier: uma falha no meio não deixa parte das medidas já
comitadas enquanto o resto falhou.
"""

from __future__ import annotations

from typing import Any

from errors import (
    ColumnNotFoundError,
    MeasureNotFoundError,
    NotADateColumnError,
    TableNotFoundError,
    UnknownTimeIntelligenceVariantError,
)
from modeling import connection, operations
from modeling.metadata import get_model_metadata

_VARIANT_SUFFIXES: dict[str, str] = {
    "YTD": "YTD",
    "QTD": "QTD",
    "MTD": "MTD",
    "PY": "PY",
    "YoY": "YoY %",
    "PM": "PM",
    "MoM": "MoM %",
}

_PERCENTAGE_VARIANTS = {"YoY", "MoM"}


def build_time_intelligence_dax(measure_name: str, date_table: str, date_column: str, variant: str) -> str:
    """Monta a expressão DAX de `variant` pra `measure_name`. Função
    pura -- não toca o modelo. Ver docstring do módulo pras funções DAX
    usadas em cada variante.

    Raises:
        UnknownTimeIntelligenceVariantError: `variant` não é uma das
            reconhecidas (ver `_VARIANT_SUFFIXES`).
    """
    return _variant_dax(f"[{measure_name}]", date_table, date_column, variant)


def build_time_intelligence_calculation_item_dax(date_table: str, date_column: str, variant: str) -> str:
    """Mesma variante, mas pra um ITEM de calculation group: a medida vira
    `SELECTEDMEASURE()` (doc oficial de calculation groups -- o item se
    aplica a qualquer medida do visual). Mesmos templates DAX de
    build_time_intelligence_dax, uma fonte só."""
    return _variant_dax("SELECTEDMEASURE()", date_table, date_column, variant)


def variant_label(variant: str) -> str:
    """Rótulo da variante ("YTD", "YoY %", ...) -- sufixo das medidas
    geradas e nome do item no calculation group."""
    return _VARIANT_SUFFIXES[variant]


def is_percentage_variant(variant: str) -> bool:
    return variant in _PERCENTAGE_VARIANTS


def validate_variants(variants: list[str]) -> None:
    unknown_variants = [v for v in variants if v not in _VARIANT_SUFFIXES]
    if unknown_variants:
        raise UnknownTimeIntelligenceVariantError(unknown_variants[0], sorted(_VARIANT_SUFFIXES))


def validate_date_column(model_metadata: Any, date_table: str, date_column: str) -> None:
    """Confere que `date_table[date_column]` existe e é DateTime.

    Raises:
        TableNotFoundError, ColumnNotFoundError, NotADateColumnError.
    """
    date_table_info = model_metadata.find_table(date_table)
    if date_table_info is None:
        raise TableNotFoundError(date_table, known_tables=model_metadata.table_names())

    date_column_info = model_metadata.find_column(date_table, date_column)
    if date_column_info is None:
        raise ColumnNotFoundError(
            date_table, date_column, known_columns=[c.name for c in date_table_info.columns]
        )
    if date_column_info.data_type != "DateTime":
        raise NotADateColumnError(date_table, date_column, date_column_info.data_type)


def _variant_dax(measure_ref: str, date_table: str, date_column: str, variant: str) -> str:
    date_ref = f"'{date_table}'[{date_column}]"

    if variant == "YTD":
        return f"TOTALYTD({measure_ref}, {date_ref})"
    if variant == "QTD":
        return f"TOTALQTD({measure_ref}, {date_ref})"
    if variant == "MTD":
        return f"TOTALMTD({measure_ref}, {date_ref})"
    if variant == "PY":
        return f"CALCULATE({measure_ref}, SAMEPERIODLASTYEAR({date_ref}))"
    if variant == "PM":
        return f"CALCULATE({measure_ref}, DATEADD({date_ref}, -1, MONTH))"
    if variant == "YoY":
        prior = f"CALCULATE({measure_ref}, SAMEPERIODLASTYEAR({date_ref}))"
        return (
            f"VAR CurrentValue = {measure_ref} "
            f"VAR PriorValue = {prior} "
            "RETURN DIVIDE(CurrentValue - PriorValue, PriorValue)"
        )
    if variant == "MoM":
        prior = f"CALCULATE({measure_ref}, DATEADD({date_ref}, -1, MONTH))"
        return (
            f"VAR CurrentValue = {measure_ref} "
            f"VAR PriorValue = {prior} "
            "RETURN DIVIDE(CurrentValue - PriorValue, PriorValue)"
        )

    raise UnknownTimeIntelligenceVariantError(variant, sorted(_VARIANT_SUFFIXES))


def create_time_intelligence_measures(
    base_measure: str,
    date_table: str,
    date_column: str,
    variants: list[str],
    save: bool = True,
) -> dict[str, Any]:
    """Cria uma medida nova pra cada `variants` (ex: `["YTD", "PY",
    "YoY"]`), a partir de `base_measure`, na mesma tabela dela. Cada
    medida nova se chama "`base_measure` `<sufixo da variante>`" (ex:
    "Total Vendas YTD", "Total Vendas YoY %").

    Variantes disponíveis: "YTD"/"QTD"/"MTD" (acumulado no ano/
    trimestre/mês), "PY" (mesmo período do ano anterior), "PM" (mês
    anterior), "YoY"/"MoM" (crescimento % ano/mês contra o
    período anterior, formatadas como percentual).

    CONFIRMADO AO VIVO (YTD/PY/YoY, com TOTALYTD/SAMEPERIODLASTYEAR):
    valores batem exatamente com o total manual por ano via
    `evaluate_dax`. **Achado importante, não é bug desta função**: as
    medidas só funcionam certo quando o visual filtra/agrupa por uma
    coluna da PRÓPRIA `date_table` (ex: o "Ano" da tabela de datas) --
    se o visual agrupar por uma coluna de ano duplicada na tabela de
    fatos (comum quando a fonte de dados já vem com colunas tipo
    "Ano"/"Mês" prontas), o resultado fica em branco/errado quando o
    relacionamento entre as duas tabelas é de filtro de mão única (o
    padrão do Power BI): filtrar pela tabela de fatos não propaga de
    volta pra tabela de datas, que é o que `TOTALYTD`/
    `SAMEPERIODLASTYEAR` precisam enxergar filtrada. Ver README, seção
    "Validação real", pro teste que reproduziu isso.

    Raises:
        DesktopNotFoundError: nenhuma conexão ativa.
        MeasureNotFoundError: `base_measure` não existe no modelo.
        TableNotFoundError: `date_table` não existe no modelo.
        ColumnNotFoundError: `date_column` não existe em `date_table`.
        NotADateColumnError: `date_column` não é do tipo DateTime.
        UnknownTimeIntelligenceVariantError: alguma entrada de
            `variants` não é reconhecida.
        MeasureAlreadyExistsError: já existe uma medida com o nome
            gerado pra alguma variante (propagado por create_measure).
    """
    model_metadata = get_model_metadata()

    base = model_metadata.find_measure(base_measure)
    if base is None:
        raise MeasureNotFoundError(base_measure, known_measures=model_metadata.measure_names())

    validate_date_column(model_metadata, date_table, date_column)
    validate_variants(variants)

    created = []
    for variant in variants:
        dax_expression = build_time_intelligence_dax(base_measure, date_table, date_column, variant)
        new_measure_name = f"{base_measure} {_VARIANT_SUFFIXES[variant]}"
        format_string = "0.0%" if variant in _PERCENTAGE_VARIANTS else base.format_string
        created.append(
            operations.create_measure(
                table_name=base.table_name,
                measure_name=new_measure_name,
                dax_expression=dax_expression,
                format_string=format_string,
                save=False,
            )
        )

    if save:
        connection.get_active_runtime().save_changes()

    return {
        "base_measure": base_measure,
        "date_table": date_table,
        "date_column": date_column,
        "created": created,
    }
