"""Construtores puros (sem I/O) do JSON de um filtro com valor em
`filterConfig.filters[]` -- o mesmo array em page.json e report.json.

Fontes (regra do projeto: nunca inventar estrutura):
- Doc oficial de autoria de PBIR (microsoft/skills-for-fabric,
  `references/authoring/filters.md` e `expressions.md`): forma de
  `Categorical` (condição `In`), faixa (`type: "Advanced"` + `Between`),
  `Not` em volta do `In` pra excluir, `Comparison` com `ComparisonKind`
  0=Equal 1=GreaterThan 2=GreaterThanOrEqual 3=LessThan
  4=LessThanOrEqual, `howCreated: "User"` obrigatório, nome
  `"Filter" + 24 hex`, e a armadilha: dentro de `filter.Where` o
  `SourceRef` usa `"Source"` (o alias do `From`), enquanto o `field` de
  nível superior usa `"Entity"`.
- Schema `semanticQuery` vendorizado (tests/schemas/): formato dos
  literais -- Integer `"24L"`, Double `"2.4D"`, Decimal `"2.4M"`,
  DateTime `"datetime'YYYY-MM-DDThh:mm:ss'"`, Boolean `"true"`.

DIVERGÊNCIA ENTRE AS FONTES (a ser confirmada ao vivo): pra texto, o
schema descreve o literal como `"some string value"`, mas o exemplo de
`In` da doc de autoria usa `"'<value>'"` (entre aspas simples). Seguimos
a doc de autoria (é a que tem exemplo completo de filtro; aspas simples
também é o formato visto em arquivos PBIR reais). Se o teste ao vivo
mostrar o filtro sem efeito, comparar com um filtro criado pela UI do
Desktop (técnica de comparação com o Desktop).

Escopo v1: só coluna (medida exigiria filtro de nível visual), e TopN
fica de fora (a doc diz que só funciona em nível visual).
"""

from __future__ import annotations

import uuid
from typing import Any

from errors import InvalidFilterDefinitionError
from visuals.validator import ResolvedField, field_reference_node

HOW_CREATED_USER = "User"
HOW_CREATED_DRILLTHROUGH = "Drillthrough"

_COMPARISON_KINDS = {"eq": 0, "gt": 1, "gte": 2, "lt": 3, "lte": 4}


def new_filter_name() -> str:
    return f"Filter{uuid.uuid4().hex[:24]}"


def format_literal(value: Any, data_type: str | None) -> str:
    """Formata `value` como o `Value` de um `Literal` do semanticQuery,
    de acordo com o tipo da coluna."""
    if value is None:
        return "null"
    if not data_type:
        # Coluna de tabela calculada lida do TMDL (ex: parâmetro de campo):
        # o TMDL não grava `dataType` (o motor deduz), então deduzimos pelo
        # tipo do valor informado. Achado ao montar a réplica, página 2.
        data_type = ("Boolean" if isinstance(value, bool) else "Int64" if isinstance(value, int)
                     else "Double" if isinstance(value, float) else "String")
    try:
        if data_type == "String":
            return "'" + str(value).replace("'", "''") + "'"
        if data_type == "Int64":
            return f"{int(value)}L"
        if data_type == "Double":
            return f"{_number_text(value)}D"
        if data_type == "Decimal":
            return f"{_number_text(value)}M"
        if data_type == "DateTime":
            text = str(value)
            if "T" not in text:
                text += "T00:00:00"
            return f"datetime'{text}'"
        if data_type == "Boolean":
            return "true" if value in (True, "true", "True", 1) else "false"
    except (TypeError, ValueError) as exc:
        raise InvalidFilterDefinitionError(
            f"Valor '{value}' não é compatível com o tipo de coluna '{data_type}'."
        ) from exc
    raise InvalidFilterDefinitionError(
        f"Tipo de coluna '{data_type}' não tem formato de literal conhecido pra filtro."
    )


def categorical_filter(
    field: ResolvedField, values: list[Any], *, exclude: bool = False
) -> dict[str, Any]:
    """Filtro de lista de valores (`Categorical`, condição `In`);
    `exclude=True` inverte (`Not` em volta do `In`)."""
    _require_column(field)
    if not values:
        raise InvalidFilterDefinitionError("`values` não pode ser vazio num filtro categórico.")

    alias = _alias_for(field)
    condition: dict[str, Any] = {
        "In": {
            "Expressions": [_source_column(alias, field)],
            "Values": [[_literal(v, field.data_type)] for v in values],
        }
    }
    if exclude:
        condition = {"Not": {"Expression": condition}}
    return _container(field, "Categorical", alias, condition)


def between_filter(field: ResolvedField, lower: Any, upper: Any) -> dict[str, Any]:
    """Filtro de faixa inclusiva (`type: "Advanced"` + `Between`)."""
    _require_column(field)
    if lower is None or upper is None:
        raise InvalidFilterDefinitionError("`between` precisa de `lower` e `upper`.")

    alias = _alias_for(field)
    condition = {
        "Between": {
            "Expression": _source_column(alias, field),
            "LowerBound": _literal(lower, field.data_type),
            "UpperBound": _literal(upper, field.data_type),
        }
    }
    return _container(field, "Advanced", alias, condition)


def comparison_filter(field: ResolvedField, operator: str, value: Any) -> dict[str, Any]:
    """Filtro de comparação simples (`type: "Advanced"` + `Comparison`)."""
    _require_column(field)
    if operator not in _COMPARISON_KINDS:
        raise InvalidFilterDefinitionError(
            f"Operador '{operator}' desconhecido. Use um de: {', '.join(_COMPARISON_KINDS)}."
        )

    alias = _alias_for(field)
    condition = {
        "Comparison": {
            "ComparisonKind": _COMPARISON_KINDS[operator],
            "Left": _source_column(alias, field),
            "Right": _literal(value, field.data_type),
        }
    }
    return _container(field, "Advanced", alias, condition)


def filter_matches(
    entry: dict[str, Any], entity: str, property_name: str, how_created: str
) -> bool:
    """O filtro `entry` é sobre `entity.property_name` E foi criado do
    jeito `how_created`? Casar também por `howCreated` é o que deixa um
    filtro de usuário e um campo de drillthrough conviverem no mesmo
    campo, na mesma página, sem um ser confundido com o outro."""
    if entry.get("howCreated") != how_created:
        return False
    field = entry.get("field", {})
    column_or_measure = field.get("Column") or field.get("Measure") or {}
    return (
        column_or_measure.get("Expression", {}).get("SourceRef", {}).get("Entity") == entity
        and column_or_measure.get("Property") == property_name
    )


# --- internos ---------------------------------------------------------------


def _require_column(field: ResolvedField) -> None:
    if field.kind != "column":
        raise InvalidFilterDefinitionError(
            f"'{field.query_ref}' é uma medida -- filtro de página/relatório com "
            "valor só é suportado em coluna."
        )


def _alias_for(field: ResolvedField) -> str:
    # Qualquer nome único dentro do filtro serve; o Desktop costuma usar a
    # inicial minúscula da tabela.
    first = next((ch for ch in field.entity if ch.isalpha()), "t")
    return first.lower()


def _source_column(alias: str, field: ResolvedField) -> dict[str, Any]:
    return {"Column": {"Expression": {"SourceRef": {"Source": alias}}, "Property": field.property}}


def _literal(value: Any, data_type: str | None) -> dict[str, Any]:
    return {"Literal": {"Value": format_literal(value, data_type)}}


def _number_text(value: Any) -> str:
    number = float(value)
    return str(int(number)) if number.is_integer() else repr(number)


def _container(
    field: ResolvedField, filter_type: str, alias: str, condition: dict[str, Any]
) -> dict[str, Any]:
    return {
        "name": new_filter_name(),
        "field": field_reference_node(field),
        "type": filter_type,
        "filter": {
            "Version": 2,
            "From": [{"Name": alias, "Entity": field.entity, "Type": 0}],
            "Where": [{"Condition": condition}],
        },
        "howCreated": HOW_CREATED_USER,
    }
