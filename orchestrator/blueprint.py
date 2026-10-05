"""Modelos Pydantic do blueprint aceito por apply_dashboard_blueprint.

Este é o contrato do lado 2 do fluxo em duas etapas descrito no
docstring de plan_dashboard/apply_dashboard_blueprint em server.py: o
Claude que chamou plan_dashboard preenche uma instância deste shape
(usando exatamente os nomes de tabela/medida existentes que confirmou,
ou os que decidiu criar) e a passa para apply_dashboard_blueprint.

`model_config = ConfigDict(extra="forbid")` em cada modelo garante que
um campo digitado errado (typo) vira um erro de validação claro, em vez
de ser silenciosamente ignorado.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from errors import InvalidPageNameError
from visuals.names import validate_page_name


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class NewTable(_StrictModel):
    """Uma tabela calculada nova (DAX) a criar antes de gerar os
    visuais. Ver modeling.operations.create_table.

    NOTA (2026-09-23): só tabela calculada -- suporte a Power Query (M)
    foi removido deste servidor de propósito (decisão de projeto).
    """

    table_name: str
    dax_expression: str


class NewMeasure(_StrictModel):
    """Uma medida nova a criar antes de gerar os visuais. `table_name`
    pode ser uma tabela já existente ou uma listada em `new_tables` deste
    mesmo blueprint -- apply_dashboard_blueprint cria as tabelas antes
    das medidas. Ver modeling.operations.create_measure."""

    table_name: str
    measure_name: str
    dax_expression: str
    format_string: str | None = None


class NewRelationship(_StrictModel):
    """Um relacionamento novo a criar antes de gerar os visuais. Ver
    modeling.operations.create_relationship."""

    from_table: str
    from_column: str
    to_table: str
    to_column: str
    cardinality: Literal["many_to_one", "one_to_one", "one_to_many"] = "many_to_one"
    cross_filter_direction: Literal["single", "both"] = "single"


class VisualSpec(_StrictModel):
    """Um visual a adicionar numa página. `fields` mapeia role (ver
    visuals.catalog) para lista de referências "Tabela.Campo".

    Importante: campos aqui só podem referenciar tabelas/medidas que já
    existem no modelo OU medidas listadas em `new_measures` deste mesmo
    blueprint -- NÃO podem referenciar colunas de uma tabela listada em
    `new_tables` deste blueprint, porque as colunas de uma tabela nova
    só são conhecidas depois que o Power BI Desktop avalia sua expressão
    M/DAX (o que este servidor não faz). Para usar colunas de uma tabela
    recém-criada num visual, crie a tabela num blueprint separado
    primeiro, confirme suas colunas com list_model_metadata, e só então
    monte o blueprint dos visuais.
    """

    visual_type: str
    x: float
    y: float
    width: float
    height: float
    fields: dict[str, list[str]] = Field(default_factory=dict)
    # texto alternativo (leitor de tela) -- recomendado: o que o visual
    # mostra e a conclusão principal, ex: "Vendas por país; EUA lidera"
    alt_text: str | None = None


_HEX_COLOR_PATTERN = r"^#[0-9A-Fa-f]{6}$"


class PageTitle(_StrictModel):
    """Título da página: um textbox numa faixa colorida ocupando a
    largura inteira no topo. Os padrões já dão um título "pronto"
    (faixa azul escura, texto branco 20pt negrito centralizado); cores
    em hexadecimal com '#'."""

    text: str = Field(min_length=1)
    font_size: float = Field(default=20, ge=8, le=60)
    bold: bool = True
    color: str = Field(default="#FFFFFF", pattern=_HEX_COLOR_PATTERN)
    background_color: str = Field(default="#1F3864", pattern=_HEX_COLOR_PATTERN)
    alignment: Literal["left", "center", "right"] = "center"
    height: float = Field(default=56, gt=0, le=200)


class PageSpec(_StrictModel):
    """Uma página a criar (ou reutilizar, se já existir), com seus
    visuais e um layout opcional a aplicar depois de adicioná-los.

    `title` (recomendado em toda página) cria a faixa de título no topo;
    com título, o layout começa abaixo da faixa e, sem layout, o `y` de
    cada visual conta a partir de baixo da faixa (é somada a altura do
    título). `background_color` pinta a tela atrás dos visuais (ex:
    "#F3F2F1", cinza-claro)."""

    page_name: str
    display_name: str | None = None
    title: PageTitle | None = None
    background_color: str | None = Field(default=None, pattern=_HEX_COLOR_PATTERN)
    visuals: list[VisualSpec] = Field(default_factory=list)
    layout: Literal["grid", "kpi_row"] | None = None

    @field_validator("page_name")
    @classmethod
    def _check_page_name_is_safe(cls, value: str) -> str:
        """page_name vira um componente de caminho de arquivo
        (definition/pages/<page_name>/) -- ver visuals.names para o
        porquê (path traversal + convenção de nomes do PBIR)."""
        try:
            validate_page_name(value)
        except InvalidPageNameError as exc:
            raise ValueError(str(exc)) from exc
        return value


class DashboardBlueprint(_StrictModel):
    """O blueprint completo: o que falta criar no modelo, e as
    páginas/visuais a gerar. Todas as listas são opcionais e vazias por
    padrão -- um blueprint pode, por exemplo, só adicionar visuais a uma
    página nova sem criar nada no modelo."""

    new_tables: list[NewTable] = Field(default_factory=list)
    new_measures: list[NewMeasure] = Field(default_factory=list)
    new_relationships: list[NewRelationship] = Field(default_factory=list)
    pages: list[PageSpec] = Field(default_factory=list)
