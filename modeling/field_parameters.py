"""Criação de field parameters: uma tabela calculada especial que
permite trocar a métrica/dimensão usada num visual direto na interface
do relatório (equivalente a "Modelagem > Novo parâmetro > Campos" no
Power BI Desktop).

CONFIRMADO AO VIVO DE PONTA A PONTA (2026-09-20/21) -- a documentação
oficial da Microsoft
(learn.microsoft.com/power-bi/create-reports/power-bi-field-parameters)
só cobre a metade "modelo" da história; a metade "faz o visual reagir"
foi descoberta comparando com um field parameter criado manualmente
pela UI do Desktop (mesma técnica que resolveu outros bugs deste
projeto), inspecionando o modelo direto via TOM/pythonnet porque a
diferença não aparecia nem em `list_model_metadata` nem nas DMVs
`INFO.TABLES()`/`INFO.COLUMNS()` (só reflexão .NET achou).

**Parte 1 -- a tabela (documentada oficialmente):** tabela CALCULADA
comum (reaproveita modeling.operations.create_table, mode="calculated"),
com uma expressão de construtor `{(...), (...)}` -- uma linha por
campo, cada linha com 3 elementos: nome de exibição (texto), referência
`NAMEOF()` do campo, ordem (número). Como a expressão não nomeia as
colunas, o DAX as chama de `Value1`/`Value2`/`Value3` (confirmado via
`list_model_metadata` -- a UI do Desktop renomeia essas colunas, mas
isso é só cosmético, não muda o comportamento). Depois de
`SaveChanges`, a tabela existe mas **sem dado nenhum** até um
`refresh_table` explícito (`evaluate_dax` recusa com "does not hold any
data because it needs to be recalculated or refreshed") -- por isso
`create_field_parameter` chama `refresh_table` logo depois de criar.
Isso já é suficiente pra um SLICER com `Value1` funcionar (mostra as
opções, deixa selecionar) -- mas **não** pra um cartão/gráfico reagir à
seleção.

**Parte 2 -- fazer um visual reagir (NÃO documentada oficialmente,
achada por comparação ao vivo):** faltam duas propriedades de TOM que
não têm equivalente em nenhuma tool deste projeto antes desta, e que a
UI do Desktop configura por trás dos panos sem documentar:

1. `Value1.RelatedColumnDetails` -- um `GroupByColumn` apontando pra
   `Value2` (a coluna com a referência `NAMEOF()`). Liga a coluna de
   exibição à coluna que carrega o campo de verdade.
2. `Value2.ExtendedProperties` -- uma `JsonExtendedProperty` chamada
   `"ParameterMetadata"`, valor `{"version": 3, "kind": 2}`. É essa
   propriedade, mais que qualquer outra, que parece marcar a coluna
   como "isto é um field parameter de verdade" pro motor de consulta.

Sem essas duas, um cartão com o campo do parâmetro no lugar de uma
medida dá `Missing_References` ao vivo -- confirmado o bug e depois a
correção, comparando byte a byte (bem, propriedade a propriedade) uma
tabela nossa com uma criada manualmente. `create_field_parameter`
aplica as duas via `TomRuntime.set_column_related_column`/
`set_column_extended_property` (chamadas direto no runtime, não
passam pelas validações de `modeling.operations` porque os nomes de
coluna envolvidos são gerados por esta própria função, não vêm de
entrada externa).

**Não replicado, e não confirmado se é necessário**: a UI do Desktop
também muda `Column.SummarizeBy` (de "None" pro equivalente de "Sum"
em `Value1`/`Value2`, "Min" em `Value3`) -- mudamos isso ao vivo
durante o debug junto com as duas propriedades acima e só testamos as
três juntas, então não sabemos se `SummarizeBy` sozinho teria efeito.
Não replicado aqui por ser semanticamente estranho (campo de texto com
`SummarizeBy=Sum`) e pelas outras duas propriedades já explicarem o
mecanismo (uma liga as colunas, a outra marca explicitamente "isto é
parâmetro") -- se algum dia um field parameter nosso falhar de um jeito
que as duas propriedades não expliquem, `SummarizeBy` é a próxima
suspeita.

**Confirmado ao vivo, os dois usos**: field parameter num SLICER
(mostra as opções, deixa selecionar) e num CARTÃO (reage à seleção do
slicer, troca o valor mostrado -- testado com "Total Sales"/"Total
Profit" alternando via slicer e o cartão mudando de acordo). Ver
`visuals.visual_writer.set_visual_field_parameter` pro lado do visual
(query.queryState.<role>.fieldParameters), e README
pro relato completo do debug.
"""

from __future__ import annotations

from typing import Any

from errors import ColumnNotFoundError, FieldParameterError, TableNotFoundError
from modeling import connection, operations
from modeling.metadata import ModelMetadata, get_model_metadata

_DISPLAY_COLUMN = "Value1"
_FIELDS_COLUMN = "Value2"
_ORDER_COLUMN = "Value3"


def build_field_parameter_dax(entries: list[tuple[str, str, str]]) -> str:
    """Monta a expressão DAX do construtor de tabela pra `entries`
    (lista de `(nome_de_exibição, tabela, propriedade)`, já resolvidos
    contra o modelo). Função pura -- não toca o modelo."""
    rows = ", ".join(
        f"(\"{name}\", NAMEOF('{entity}'[{property_name}]), {order})"
        for order, (name, entity, property_name) in enumerate(entries)
    )
    return "{" + rows + "}"


def create_field_parameter(
    table_name: str,
    fields: list[str],
    display_names: list[str] | None = None,
    save: bool = True,
) -> dict[str, Any]:
    """Cria um field parameter chamado `table_name`, com um campo por
    entrada de `fields` (cada um "Tabela.Coluna" ou "Tabela.Medida"), na
    ordem em que devem aparecer no seletor.

    Arraste `table_name` (a coluna de nome de exibição) pra um slicer,
    ou pro field well de um visual -- role de dado/eixo pra campos de
    coluna, role de valor pra campos de medida (ver doc oficial, "Use a
    field parameter in visuals").

    Args:
        table_name: Nome da tabela nova (e da coluna de exibição
            dentro dela).
        fields: Campos a incluir, na ordem desejada (ex:
            `["Vendas.Total Vendas", "Vendas.Total Custo"]`).
        display_names: Nomes de exibição, na mesma ordem de `fields`.
            Precisa ter o mesmo tamanho se informado; usa o nome nativo
            do campo (coluna/medida) quando omitido.
        save: Se False, não salva ao final (a criação da tabela em si
            sempre salva no meio do processo -- ver docstring do
            módulo/comentário no código -- só o hide/sort final respeita
            este parâmetro).

    Returns:
        Dict com `table_name`, `fields` (normalizados), `display_names`
        e `display_column` (nome da coluna pra arrastar num visual).

    Raises:
        FieldParameterError: `fields` vazio, ou `display_names` com
            tamanho diferente de `fields`.
        TableNotFoundError/ColumnNotFoundError: alguma entrada de
            `fields` não existe no modelo (nem como coluna, nem como
            medida).
        TableAlreadyExistsError: já existe uma tabela chamada
            `table_name`.
    """
    if not fields:
        raise FieldParameterError("`fields` não pode ser vazio.")
    if display_names is not None and len(display_names) != len(fields):
        raise FieldParameterError(
            f"`display_names` tem {len(display_names)} nome(s), mas `fields` tem "
            f"{len(fields)} campo(s) -- precisam ter o mesmo tamanho."
        )

    model_metadata = get_model_metadata()
    resolved = [_resolve_field_reference(model_metadata, ref) for ref in fields]
    names = display_names or [property_name for _, property_name in resolved]

    entries = [(name, entity, property_name) for name, (entity, property_name) in zip(names, resolved)]
    dax_expression = build_field_parameter_dax(entries)

    # O TOM só descobre as colunas (Value1/2/3) de uma tabela calculada
    # ao processar a expressão -- por isso este create_table precisa
    # salvar por conta própria (save=True fixo aqui, não repassa o
    # `save` do parâmetro) antes de esconder/ordenar as colunas.
    # refresh=False: o refresh_table explícito logo abaixo já cobre a
    # descoberta de coluna (era o comportamento já confirmado ao vivo
    # antes do bug 1.4 existir uma versão automática em create_table) --
    # evita um round-trip de RequestRefresh/SaveChanges duplicado.
    operations.create_table(
        table_name=table_name, dax_expression=dax_expression, save=True, refresh=False,
    )

    # CONFIRMADO AO VIVO: mesmo depois de SaveChanges, a tabela existe
    # (colunas visíveis em list_model_metadata) mas sem dado nenhum --
    # `evaluate_dax` recusa com "does not hold any data because it
    # needs to be recalculated or refreshed" até um refresh_table
    # explícito (igual qualquer tabela recém-criada). refresh_table já
    # salva sozinho.
    operations.refresh_table(table_name)

    operations.set_column_visibility(table_name, _FIELDS_COLUMN, is_hidden=True, save=False)
    operations.set_column_visibility(table_name, _ORDER_COLUMN, is_hidden=True, save=False)
    operations.set_column_sort_by(table_name, _DISPLAY_COLUMN, sort_by_column=_ORDER_COLUMN, save=False)

    # CONFIRMADO AO VIVO: sem essas duas propriedades, um cartão/gráfico
    # vinculado ao parâmetro dá "Missing_References" -- ver docstring do
    # módulo. Chamadas direto no runtime (não via modeling.operations,
    # que valida contra input externo -- aqui os nomes de coluna são
    # gerados por esta própria função).
    runtime = connection.get_active_runtime()
    runtime.set_column_related_column(table_name, _DISPLAY_COLUMN, _FIELDS_COLUMN)
    runtime.set_column_extended_property(
        table_name, _FIELDS_COLUMN, "ParameterMetadata", '{\n  "version": 3,\n  "kind": 2\n}'
    )

    if save:
        runtime.save_changes()

    return {
        "table_name": table_name,
        "fields": [f"{entity}.{property_name}" for entity, property_name in resolved],
        "display_names": names,
        "display_column": _DISPLAY_COLUMN,
    }


def _resolve_field_reference(metadata: ModelMetadata, reference: str) -> tuple[str, str]:
    """Resolve "Tabela.Campo" contra `metadata`: tenta coluna primeiro
    (precisa existir na tabela informada), senão medida (únicas em todo
    o modelo). Devolve (entidade, propriedade) -- mesma lógica de
    visuals.validator.resolve_field, mas reimplementada aqui porque
    modeling/ não depende de visuals/ (a dependência vai só na outra
    direção neste projeto).

    Raises:
        TableNotFoundError: a referência não tem "." nenhum, ou a
            tabela informada não existe (e não achou medida com esse
            nome também).
        ColumnNotFoundError: a tabela existe, mas nem a coluna nem uma
            medida com esse nome foram encontradas.
    """
    if "." not in reference:
        raise TableNotFoundError(reference, known_tables=metadata.table_names())

    table_name, _, property_name = reference.partition(".")

    table = metadata.find_table(table_name)
    if table is not None and any(c.name == property_name for c in table.columns):
        return table_name, property_name

    measure = metadata.find_measure(property_name)
    if measure is not None:
        return measure.table_name, measure.name

    if table is None:
        raise TableNotFoundError(table_name, known_tables=metadata.table_names())
    raise ColumnNotFoundError(
        table_name, property_name, known_columns=[c.name for c in table.columns]
    )
