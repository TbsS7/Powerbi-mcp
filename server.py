"""Servidor MCP powerbi-fullstack-mcp.

Registra as ferramentas (lista completa no README, "Ferramentas
disponíveis" -- tests/test_docs_consistency.py garante que está em dia) que
unem a camada de modelagem (TOM/XMLA contra
o Power BI Desktop aberto, ou leitura offline de .tmdl) e a camada de
visuais (arquivos PBIR dentro da pasta .Report de um projeto .pbip).

Este módulo é deliberadamente magro: cada tool valida/serializa a entrada
e delega para a função de domínio correspondente em modeling/, visuals/
ou orchestrator/. Erros de domínio (subclasses de errors.PowerBiMcpError)
são convertidos em mcp.server.mcpserver.exceptions.ToolError, que o SDK
devolve ao cliente como uma falha de tool legível (is_error=True) em vez
de um traceback cru.

Usa a API do pacote `mcp` 2.x: `MCPServer` (equivalente ao `FastMCP` de
versões 1.x do SDK, renomeado na v2 — ver
https://py.sdk.modelcontextprotocol.io/v2/migration/#fastmcp-renamed-to-mcpserver).
"""

from __future__ import annotations

import functools
import logging
import os
from typing import Any, Literal

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from errors import PowerBiMcpError

logging.basicConfig(level=os.environ.get("POWERBI_MCP_LOG_LEVEL", "INFO"))
logger = logging.getLogger("powerbi-fullstack-mcp")

mcp = MCPServer(
    name="powerbi-fullstack-mcp",
    instructions=(
        "Ferramentas para modelar dados (tabelas, medidas, relacionamentos) "
        "e gerar visuais/dashboards em um projeto Power BI (.pbip). Para "
        "montar um dashboard a partir de uma descrição em linguagem "
        "natural, chame plan_dashboard primeiro, monte o blueprint com o "
        "resultado, e então chame apply_dashboard_blueprint. "
        "Ferramentas de página/visual/tema escrevem direto nos arquivos: "
        "pro Desktop mostrar, o usuário clica em 'Apply external changes' "
        "('Aplicar alterações externas' no Desktop em português) "
        "na faixa que o Desktop exibe (ou fecha sem salvar e reabre). As "
        "duas coisas descartam o que não foi salvo -- se houve mudança de "
        "modelo nesta sessão (medida, tabela, perspectiva...), salve antes "
        "(save_desktop, com confirmação do usuário)."
    ),
)


def _domain_tool(fn):
    """Converte PowerBiMcpError em ToolError, preservando a mensagem
    (pensada para ser lida por um agente) e evitando que o cliente veja
    apenas 'Error executing tool <name>'."""

    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return fn(*args, **kwargs)
        except PowerBiMcpError as exc:
            raise ToolError(str(exc)) from exc

    return wrapper


# ---------------------------------------------------------------------------
# Camada de modelagem
# ---------------------------------------------------------------------------


@mcp.tool()
@_domain_tool
def connect_to_desktop(
    port: int | None = None,
    database_name: str | None = None,
) -> dict[str, Any]:
    """Conecta a uma instância aberta do Power BI Desktop via seu endpoint
    XMLA local.

    Autodescobre a porta lendo os arquivos msmdsrv.port.txt das
    AnalysisServicesWorkspaces do Desktop. Se houver mais de uma instância
    aberta, informe `port` ou `database_name` para escolher qual usar —
    caso contrário a ferramenta lista as instâncias encontradas e pede
    para você escolher.

    Requer as DLLs do Tabular Object Model (TOM) e o pacote opcional
    `pythonnet`; veja o README, seção "Licenciamento e obtenção do TOM".

    Args:
        port: Porta TCP local do endpoint XMLA, se já conhecida.
        database_name: Nome do banco/modelo, se você quiser escolher por
            nome em vez de porta.

    Returns:
        Dict com `port`, `database_name` e `compatibility_level` da
        conexão estabelecida.
    """
    from modeling import connection

    return connection.connect_to_desktop(port=port, database_name=database_name)


@mcp.tool()
@_domain_tool
def save_desktop() -> dict[str, Any]:
    """Salva (Ctrl+S) o projeto aberto na conexão TOM ativa, via
    automação de janela do Windows -- TOM/XMLA não tem comando de
    "salvar arquivo" (save_changes() persiste no modelo vivo em
    memória, não no .pbip em disco).

    ATENÇÃO -- NUNCA chame esta tool logo depois de create_report_page,
    add_visual, set_page_layout ou apply_dashboard_blueprint terem
    escrito páginas/visuais. Confirmado ao vivo: o Power BI Desktop
    reescreve toda a pasta de páginas do projeto com o que está na
    memória dele ao salvar, apagando qualquer página que ainda não
    tenha sido carregada -- ou seja, salvar logo depois de escrever um
    visual novo apaga esse visual. Chame esta tool só depois de
    connect_to_desktop + create_table/create_measure/
    create_relationship (ou apply_dashboard_blueprint sem nenhuma
    página), para persistir essas mudanças de modelo antes de criar
    visuais numa chamada separada. Veja o README, seção "O ciclo
    salvar / reabrir".

    Esta tool não tem como pedir confirmação sozinha -- confirme com o
    usuário em texto que ele quer salvar agora antes de chamá-la.

    Requer que a janela do Power BI Desktop correspondente à conexão
    ativa seja identificável sem ambiguidade (ver
    modeling.desktop_automation); se não for possível, falha em vez de
    arriscar salvar o projeto errado.

    Returns:
        Dict com `port`, `pid` da janela do Desktop, e confirmação de
        que o Ctrl+S foi enviado.
    """
    from modeling import desktop_automation

    return desktop_automation.save_desktop()


@mcp.tool()
@_domain_tool
def create_table(
    table_name: str,
    dax_expression: str,
) -> dict[str, Any]:
    """Cria uma tabela calculada (expressão DAX) no modelo conectado.

    NOTA (2026-09-23): este servidor só cria tabela calculada -- suporte
    a tabela via Power Query (M) foi removido de propósito (a
    investigação do bug 1.4 do plano de robustez achou que o TOM/AMO não
    tem nenhuma API pra descobrir colunas a partir de uma fonte M; essa
    descoberta é feita pelo motor Mashup do Query Editor, do lado do
    Desktop, fora do alcance deste servidor).

    Args:
        table_name: Nome da nova tabela.
        dax_expression: A expressão DAX da tabela calculada.

    Returns:
        Dict com `table_name`, `columns` (colunas reais detectadas após
        um refresh automático -- necessário pra construtores de tupla
        sem nome de coluna, ex: field parameters), `refreshed` (bool) e
        `refresh_error` (mensagem do motor se o refresh falhar -- a
        tabela continua criada mesmo assim; chame refresh_table de novo
        se precisar).
    """
    from modeling import operations

    return operations.create_table(table_name=table_name, dax_expression=dax_expression)


@mcp.tool()
@_domain_tool
def create_measure(
    table_name: str,
    measure_name: str,
    dax_expression: str,
    format_string: str | None = None,
) -> dict[str, Any]:
    """Cria uma medida DAX numa tabela já existente no modelo.

    Args:
        table_name: Tabela onde a medida será criada. Precisa já existir
            no modelo (chame list_model_metadata para confirmar).
        measure_name: Nome da medida.
        dax_expression: Expressão DAX da medida (sem o nome, só o corpo
            após o `=`).
        format_string: Máscara de formatação opcional (ex: "#,##0.00").

    Returns:
        Dict com a medida criada.
    """
    from modeling import operations

    return operations.create_measure(
        table_name=table_name,
        measure_name=measure_name,
        dax_expression=dax_expression,
        format_string=format_string,
    )


@mcp.tool()
@_domain_tool
def create_relationship(
    from_table: str,
    from_column: str,
    to_table: str,
    to_column: str,
    cardinality: Literal["many_to_one", "one_to_one", "one_to_many"] = "many_to_one",
    cross_filter_direction: Literal["single", "both"] = "single",
) -> dict[str, Any]:
    """Cria um relacionamento entre duas tabelas existentes no modelo.

    Args:
        from_table: Tabela do lado "muitos" (tipicamente uma tabela fato).
        from_column: Coluna de chave estrangeira em `from_table`.
        to_table: Tabela do lado "um" (tipicamente uma dimensão).
        to_column: Coluna de chave em `to_table`.
        cardinality: Cardinalidade do relacionamento.
        cross_filter_direction: Direção do filtro cruzado.

    Returns:
        Dict com o relacionamento criado.
    """
    from modeling import operations

    return operations.create_relationship(
        from_table=from_table,
        from_column=from_column,
        to_table=to_table,
        to_column=to_column,
        cardinality=cardinality,
        cross_filter_direction=cross_filter_direction,
    )


@mcp.tool()
@_domain_tool
def update_measure(
    table_name: str,
    measure_name: str,
    dax_expression: str | None = None,
    format_string: str | None = None,
) -> dict[str, Any]:
    """Atualiza a expressão DAX e/ou a formatação de uma medida já
    existente. Só os parâmetros passados são alterados -- o que for
    omitido mantém o valor atual.

    Args:
        table_name: Tabela onde a medida existe.
        measure_name: Nome da medida a atualizar.
        dax_expression: Nova expressão DAX, se for mudar.
        format_string: Nova máscara de formatação, se for mudar.

    Returns:
        Dict com a medida já atualizada.
    """
    from modeling import operations

    return operations.update_measure(
        table_name=table_name,
        measure_name=measure_name,
        dax_expression=dax_expression,
        format_string=format_string,
    )


@mcp.tool()
@_domain_tool
def delete_measure(table_name: str, measure_name: str) -> dict[str, Any]:
    """Remove uma medida do modelo.

    Args:
        table_name: Tabela onde a medida existe.
        measure_name: Nome da medida a remover.

    Returns:
        Dict confirmando a remoção.
    """
    from modeling import operations

    return operations.delete_measure(table_name=table_name, measure_name=measure_name)


@mcp.tool()
@_domain_tool
def create_time_intelligence_measures(
    base_measure: str,
    date_table: str,
    date_column: str,
    variants: list[str],
    save: bool = True,
) -> dict[str, Any]:
    """Cria, a partir de uma medida já existente, uma ou mais medidas
    padrão de inteligência de tempo (acumulado no ano/trimestre/mês,
    mesmo período do ano/mês anterior, crescimento %) -- em vez de
    escrever cada expressão DAX na mão.

    Cada medida nova se chama "<base_measure> <sufixo>" (ex: "Total
    Vendas YTD", "Total Vendas YoY %") e fica na mesma tabela da medida
    base. Usa as funções padrão de inteligência de tempo do DAX
    (TOTALYTD/TOTALQTD/TOTALMTD/SAMEPERIODLASTYEAR/DATEADD) -- exige uma
    coluna de data de verdade (tipo DateTime); idealmente de uma tabela
    marcada como tabela de datas, mas funciona sobre qualquer coluna
    DateTime contígua.

    CONFIRMADO AO VIVO (valores batem com o total manual por ano).
    IMPORTANTE: no visual, agrupe/filtre por uma coluna da PRÓPRIA
    `date_table` (ex: o "Ano" dela) -- se usar uma coluna de ano
    duplicada na tabela de fatos, o resultado fica em branco/errado
    (relacionamento de filtro de mão única, comportamento normal do
    Power BI, não bug desta função).

    Args:
        base_measure: Nome da medida existente a partir da qual gerar
            as variantes (ex: "Total Vendas").
        date_table: Tabela que tem a coluna de data.
        date_column: Coluna de data (precisa ser do tipo DateTime).
        variants: Lista com uma ou mais de: "YTD"/"QTD"/"MTD"
            (acumulado no ano/trimestre/mês), "PY" (mesmo período do
            ano anterior), "PM" (mês anterior), "YoY"/"MoM" (crescimento
            % ano/mês contra o período anterior -- formatadas como
            percentual, as demais herdam a formatação da medida base).
        save: Se False, não salva as mudanças (uso avançado -- combine
            com outras chamadas de modelagem antes de salvar uma vez só;
            regra geral do projeto continua: não misture com escrita de
            visual/página na mesma rodada).

    Returns:
        Dict com `base_measure`, `date_table`, `date_column`, e
        `created` (lista com a medida criada por variante, na mesma
        ordem de `variants`).
    """
    from modeling import time_intelligence

    return time_intelligence.create_time_intelligence_measures(
        base_measure=base_measure,
        date_table=date_table,
        date_column=date_column,
        variants=variants,
        save=save,
    )


@mcp.tool()
@_domain_tool
def create_calculation_group(
    table_name: str,
    items: list[dict[str, Any]],
    column_name: str | None = None,
    precedence: int = 0,
    allow_discourage_implicit_measures: bool = False,
) -> dict[str, Any]:
    """Cria um calculation group: itens de cálculo que se aplicam a
    QUALQUER medida explícita do visual via SELECTEDMEASURE() (ex: um
    item "YTD" serve pra Total Vendas, Total Custo, ...). O usuário
    arrasta a coluna do grupo pra um slicer ou pras colunas de uma
    matriz. Pra inteligência de tempo, prefira
    create_time_intelligence_calculation_group.

    ATENÇÃO -- efeito no modelo inteiro: exige "Discourage implicit
    measures" ligado. Se ainda não estiver, a tool RECUSA, a menos que
    `allow_discourage_implicit_measures=True` -- pergunte ao usuário
    antes (dali pra frente o Desktop não deixa arrastar coluna como
    SUM/MÉDIA implícitos; com um calculation group no modelo, todas as
    medidas passam a ser 'variant'). Mudança de modelagem: confirme ao
    vivo e chame save_desktop (com confirmação) antes de escrever
    visuais.

    Args:
        table_name: Nome da tabela do calculation group (nova).
        items: Lista, na ordem de exibição, de
            {"name": ..., "expression": "<DAX com SELECTEDMEASURE()>",
             "format_string_expression": '<DAX que devolve a máscara,
             ex: "\\"0.0%\\""> (opcional)'}.
        column_name: Coluna usada no slicer/matriz (padrão: table_name).
        precedence: Ordem de aplicação entre grupos (maior = aplicado por
            fora).
        allow_discourage_implicit_measures: Opt-in explícito pro efeito
            colateral descrito acima.

    Returns:
        Dict com o grupo criado, `discourage_implicit_measures_enabled_now`,
        `refreshed` e `refresh_error`.
    """
    from modeling import calculation_groups

    return calculation_groups.create_calculation_group(
        table_name=table_name, items=items, column_name=column_name, precedence=precedence,
        allow_discourage_implicit_measures=allow_discourage_implicit_measures,
    )


@mcp.tool()
@_domain_tool
def create_time_intelligence_calculation_group(
    table_name: str,
    date_table: str,
    date_column: str,
    variants: list[str],
    column_name: str | None = None,
    include_current: bool = True,
    allow_discourage_implicit_measures: bool = False,
) -> dict[str, Any]:
    """Calculation group de inteligência de tempo: um item por variante
    (YTD, QTD, MTD, PY, PM, YoY, MoM -- os mesmos DAX de
    create_time_intelligence_measures, com SELECTEDMEASURE() no lugar da
    medida), mais "Atual" no começo. YoY/MoM saem como percentual.
    Substitui criar uma medida por combinação medida × variante.

    Mesmo aviso de create_calculation_group sobre "Discourage implicit
    measures" (opt-in explícito). E o mesmo cuidado de
    create_time_intelligence_measures: o visual precisa agrupar por uma
    coluna da PRÓPRIA `date_table`.

    Args:
        table_name: Nome da tabela do calculation group (nova).
        date_table: Tabela de datas.
        date_column: Coluna DateTime da tabela de datas.
        variants: Ex: ["YTD", "PY", "YoY"].
        column_name: Coluna usada no slicer/matriz (padrão: table_name).
        include_current: Inclui o item "Atual" (SELECTEDMEASURE()).
        allow_discourage_implicit_measures: Opt-in explícito.

    Returns:
        Dict com o grupo criado (itens com expressão DAX de cada um).
    """
    from modeling import calculation_groups

    return calculation_groups.create_time_intelligence_calculation_group(
        table_name=table_name, date_table=date_table, date_column=date_column,
        variants=variants, column_name=column_name, include_current=include_current,
        allow_discourage_implicit_measures=allow_discourage_implicit_measures,
    )


@mcp.tool()
@_domain_tool
def add_calculation_item(
    table_name: str,
    item_name: str,
    expression: str,
    format_string_expression: str | None = None,
) -> dict[str, Any]:
    """Adiciona um item ao fim de um calculation group existente.

    Args:
        table_name: Calculation group.
        item_name: Nome do item novo.
        expression: DAX do item (use SELECTEDMEASURE()).
        format_string_expression: DAX que devolve a máscara (opcional).

    Returns:
        Dict com `item_name` e o `ordinal` atribuído.
    """
    from modeling import calculation_groups

    return calculation_groups.add_calculation_item(
        table_name=table_name, item_name=item_name, expression=expression,
        format_string_expression=format_string_expression,
    )


@mcp.tool()
@_domain_tool
def delete_calculation_item(table_name: str, item_name: str) -> dict[str, Any]:
    """Remove um item de um calculation group (pra remover o grupo
    inteiro, use delete_table).

    Args:
        table_name: Calculation group.
        item_name: Item a remover.

    Returns:
        Dict confirmando a remoção.
    """
    from modeling import calculation_groups

    return calculation_groups.delete_calculation_item(table_name=table_name, item_name=item_name)


@mcp.tool()
@_domain_tool
def list_calculation_groups() -> list[dict[str, Any]]:
    """Lista os calculation groups do modelo conectado, com os itens
    (nome, expressão DAX, ordinal, format string) em ordem de exibição.

    Returns:
        Lista de dicts (`table_name`, `column_name`, `precedence`, `items`).
    """
    from modeling import calculation_groups

    return calculation_groups.list_calculation_groups()


@mcp.tool()
@_domain_tool
def delete_relationship(
    from_table: str, from_column: str, to_table: str, to_column: str
) -> dict[str, Any]:
    """Remove um relacionamento existente entre duas tabelas.

    Args:
        from_table: Tabela do lado "muitos" do relacionamento.
        from_column: Coluna de chave estrangeira em `from_table`.
        to_table: Tabela do lado "um" do relacionamento.
        to_column: Coluna de chave em `to_table`.

    Returns:
        Dict confirmando a remoção.
    """
    from modeling import operations

    return operations.delete_relationship(
        from_table=from_table, from_column=from_column, to_table=to_table, to_column=to_column
    )


@mcp.tool()
@_domain_tool
def delete_table(table_name: str) -> dict[str, Any]:
    """Remove uma tabela do modelo.

    Recusa se algum relacionamento ainda apontar pra essa tabela --
    remova o(s) relacionamento(s) primeiro (delete_relationship), pra
    nunca deixar o modelo com uma referência quebrada.

    Args:
        table_name: Tabela a remover.

    Returns:
        Dict confirmando a remoção.
    """
    from modeling import operations

    return operations.delete_table(table_name=table_name)


@mcp.tool()
@_domain_tool
def create_calculated_column(
    table_name: str,
    column_name: str,
    dax_expression: str,
    format_string: str | None = None,
) -> dict[str, Any]:
    """Cria uma coluna calculada numa tabela já existente no modelo.

    Diferente de uma medida (calculada sob demanda por visual/consulta),
    uma coluna calculada é avaliada linha a linha e armazenada no
    modelo -- ocupa espaço, mas pode ser usada em roles que exigem
    coluna (ex: Category de um gráfico, ou lado de um relacionamento).

    Args:
        table_name: Tabela onde a coluna será criada. Precisa já existir
            no modelo.
        column_name: Nome da coluna.
        dax_expression: Expressão DAX da coluna (avaliada por linha).
        format_string: Máscara de formatação opcional (ex: "#,##0.00").

    Returns:
        Dict com a coluna criada (nome e tipo de dado inferido).
    """
    from modeling import operations

    return operations.create_calculated_column(
        table_name=table_name,
        column_name=column_name,
        dax_expression=dax_expression,
        format_string=format_string,
    )


@mcp.tool()
@_domain_tool
def delete_column(table_name: str, column_name: str) -> dict[str, Any]:
    """Remove uma coluna (calculada ou de origem) de uma tabela.

    Args:
        table_name: Tabela onde a coluna existe.
        column_name: Nome da coluna a remover.

    Returns:
        Dict confirmando a remoção.
    """
    from modeling import operations

    return operations.delete_column(table_name=table_name, column_name=column_name)


@mcp.tool()
@_domain_tool
def create_hierarchy(table_name: str, hierarchy_name: str, levels: list[str]) -> dict[str, Any]:
    """Cria uma hierarquia de drill-down numa tabela existente.

    Uma hierarquia agrupa colunas já existentes numa ordem fixa (ex:
    Ano > Trimestre > Mês), permitindo drill-down em visuais que a
    referenciarem no Desktop -- a camada de visuais deste servidor
    ainda não referencia hierarquias em `fields` de add_visual.

    Args:
        table_name: Tabela onde a hierarquia será criada.
        hierarchy_name: Nome da hierarquia.
        levels: Nomes das colunas, em ordem do nível mais alto pro mais
            baixo (ex: ["Ano", "Trimestre", "Mês"]). Cada coluna
            precisa já existir na tabela.

    Returns:
        Dict com a hierarquia criada.
    """
    from modeling import operations

    return operations.create_hierarchy(
        table_name=table_name, hierarchy_name=hierarchy_name, levels=levels
    )


@mcp.tool()
@_domain_tool
def delete_hierarchy(table_name: str, hierarchy_name: str) -> dict[str, Any]:
    """Remove uma hierarquia de uma tabela.

    Args:
        table_name: Tabela onde a hierarquia existe.
        hierarchy_name: Nome da hierarquia a remover.

    Returns:
        Dict confirmando a remoção.
    """
    from modeling import operations

    return operations.delete_hierarchy(table_name=table_name, hierarchy_name=hierarchy_name)


@mcp.tool()
@_domain_tool
def list_hierarchies() -> list[dict[str, Any]]:
    """Lista as hierarquias existentes no modelo (conexão XMLA ativa).

    Returns:
        Lista de dicts, cada um com `table_name`, `hierarchy_name` e
        `levels`.
    """
    from modeling import operations

    return operations.list_hierarchies()


@mcp.tool()
@_domain_tool
def create_role(role_name: str) -> dict[str, Any]:
    """Cria um role de segurança em nível de linha (RLS), sem nenhum
    filtro ainda -- use add_table_permission para definir o que esse
    role pode ver.

    Args:
        role_name: Nome do role.

    Returns:
        Dict com o role criado (sem table_permissions ainda).
    """
    from modeling import operations

    return operations.create_role(role_name=role_name)


@mcp.tool()
@_domain_tool
def add_table_permission(role_name: str, table_name: str, filter_expression: str) -> dict[str, Any]:
    """Define o filtro de RLS de um role para uma tabela.

    Membros desse role só verão linhas de `table_name` (e, por
    propagação de relacionamento, de tabelas relacionadas) que
    satisfaçam `filter_expression`. Cada role só pode ter um filtro por
    tabela -- chame delete_role e recrie se precisar mudar.

    Args:
        role_name: Role já criado (via create_role).
        table_name: Tabela a filtrar.
        filter_expression: Expressão DAX booleana (ex:
            'Vendas[Regiao] = "Sul"').

    Returns:
        Dict com o role e todos os filtros de tabela que ele já tem.
    """
    from modeling import operations

    return operations.add_table_permission(
        role_name=role_name, table_name=table_name, filter_expression=filter_expression
    )


@mcp.tool()
@_domain_tool
def delete_role(role_name: str) -> dict[str, Any]:
    """Remove um role de RLS (e todos os filtros de tabela dele).

    Args:
        role_name: Role a remover.

    Returns:
        Dict confirmando a remoção.
    """
    from modeling import operations

    return operations.delete_role(role_name=role_name)


@mcp.tool()
@_domain_tool
def create_perspective(
    name: str,
    tables: list[str] | None = None,
    fields: list[str] | None = None,
    description: str | None = None,
) -> dict[str, Any]:
    """Cria uma PERSPECTIVA: um recorte do modelo com só as tabelas e
    campos de um assunto (ex: "Vendas" sem as tabelas de parâmetro e
    auxiliares). No Power BI, é usada no "Personalizar visuais": o
    leitor do relatório só vê esses campos ao mexer num visual. NÃO é
    segurança -- quem tem acesso ao modelo ainda vê tudo (use RLS/OLS
    pra isso).

    Muda o modelo: depois de confirmar, chame save_desktop (com
    confirmação do usuário) pra gravar no arquivo.

    Args:
        name: Nome da perspectiva.
        tables: Tabelas inteiras (inclui colunas/medidas criadas nelas
            depois).
        fields: Campos avulsos "Tabela.Campo" -- coluna, medida ou
            hierarquia (o tipo é descoberto sozinho).
        description: Descrição opcional.

    Returns:
        Dict com a perspectiva criada, tabela por tabela.
    """
    from modeling import perspectives

    return perspectives.create_perspective(name=name, tables=tables, fields=fields, description=description)


@mcp.tool()
@_domain_tool
def delete_perspective(name: str) -> dict[str, Any]:
    """Remove uma perspectiva do modelo. Antes, confira com o usuário se
    ela não está escolhida em alguma página no "Personalizar visuais"
    (Formatar página -> Personalizar visual) -- a doc oficial pede isso.

    Args:
        name: Nome da perspectiva.

    Returns:
        Dict confirmando a remoção.
    """
    from modeling import perspectives

    return perspectives.delete_perspective(name=name)


@mcp.tool()
@_domain_tool
def list_perspectives() -> list[dict[str, Any]]:
    """Lista as perspectivas do modelo, com as tabelas inteiras
    (`include_all`) e os campos avulsos de cada uma.

    Returns:
        Lista de dicts com name, description e tables.
    """
    from modeling import perspectives

    return perspectives.list_perspectives()


@mcp.tool()
@_domain_tool
def list_roles() -> list[dict[str, Any]]:
    """Lista os roles de RLS/OLS existentes no modelo (conexão XMLA ativa).

    Returns:
        Lista de dicts, cada um com `role_name` e `table_permissions`
        (lista de `table_name`/`filter_expression`/`hidden_columns`).
    """
    from modeling import operations

    return operations.list_roles()


@mcp.tool()
@_domain_tool
def hide_column(role_name: str, table_name: str, column_name: str) -> dict[str, Any]:
    """Esconde uma coluna, por completo (dado e metadado), para
    membros de um role -- segurança em nível de OBJETO (OLS).

    Diferente de add_table_permission (RLS, que filtra quais LINHAS
    aparecem), isto esconde a coluna inteira: membros do role nem
    sabem que ela existe. Exige que o role já tenha uma permissão
    definida para essa tabela (chame add_table_permission primeiro --
    use filter_expression="TRUE()" se não quiser filtrar linha
    nenhuma, só esconder a coluna).

    Args:
        role_name: Role já criado (via create_role).
        table_name: Tabela onde a coluna está. Precisa já ter uma
            permissão definida para esse role (add_table_permission).
        column_name: Coluna a esconder.

    Returns:
        Dict com o role e todos os filtros/colunas escondidas que ele
        já tem.
    """
    from modeling import operations

    return operations.hide_column(role_name=role_name, table_name=table_name, column_name=column_name)


@mcp.tool()
@_domain_tool
def unhide_column(role_name: str, table_name: str, column_name: str) -> dict[str, Any]:
    """Reverte hide_column -- volta a mostrar a coluna para membros
    desse role.

    Args:
        role_name: Role onde a coluna está escondida.
        table_name: Tabela onde a coluna está.
        column_name: Coluna a voltar a mostrar.

    Returns:
        Dict com o estado atualizado do role.
    """
    from modeling import operations

    return operations.unhide_column(
        role_name=role_name, table_name=table_name, column_name=column_name
    )


@mcp.tool()
@_domain_tool
def refresh_table(table_name: str) -> dict[str, Any]:
    """Dispara uma nova leitura dos dados de uma tabela.

    ATENÇÃO: pode demorar dependendo do volume de dados e da fonte --
    não há timeout embutido, a chamada bloqueia até o Power BI Desktop
    terminar o refresh (ou reportar erro). Não confunda com
    list_model_metadata/evaluate_dax, que só leem o que já está
    carregado.

    Args:
        table_name: Tabela a atualizar.

    Returns:
        Dict confirmando o refresh.
    """
    from modeling import operations

    return operations.refresh_table(table_name=table_name)


@mcp.tool()
@_domain_tool
def refresh_model() -> dict[str, Any]:
    """Dispara uma nova leitura dos dados de todas as tabelas do
    modelo de uma vez.

    ATENÇÃO: mesmo aviso de refresh_table, mas para o modelo inteiro --
    pode demorar bem mais. Sem timeout embutido.

    Returns:
        Dict confirmando o refresh, com a lista de tabelas atualizadas.
    """
    from modeling import operations

    return operations.refresh_model()


@mcp.tool()
@_domain_tool
def audit_model(rules: list[str] | None = None) -> dict[str, Any]:
    """Audita a qualidade/documentação do modelo conectado e APONTA
    problemas -- é só leitura, não corrige nada (use as tools de escrita,
    como set_measure_metadata/set_table_description/create_relationship,
    se o usuário quiser corrigir algo depois de revisar o relatório).

    Regras (códigos aceitos em `rules`):
      - MEDIDA_SEM_FORMAT_STRING (aviso): medida sem format string.
      - COLUNA_CHAVE_ORFA (aviso): coluna com nome de chave (…Id, …Key,
        …Codigo) fora de qualquer relacionamento.
      - MEDIDA_SEM_DESCRICAO (sugestao): medida sem descrição.
      - TABELA_SEM_DESCRICAO (sugestao): tabela sem descrição.
      - TABELA_DESCONECTADA (sugestao): tabela sem relacionamento com
        nenhuma outra (fora as tabelas de data automáticas) -- tabela de
        parâmetro/medidas costuma ser assim de propósito.
      - COLUNA_OCULTA_SEM_USO (sugestao): coluna oculta fora de
        relacionamento, sort-by, field parameter e texto de medida.
    Tabelas de data automáticas (LocalDateTable_*/DateTableTemplate_*) e
    colunas de sistema RowNumber-* são sempre ignoradas.

    Exige conexão ativa (connect_to_desktop) -- a leitura TMDL offline não
    tem os campos necessários.

    Args:
        rules: Códigos das regras a rodar; todas quando omitido.

    Returns:
        Dict com `issues` (cada um com `code`, `severity`, `object_kind`,
        `object_ref`, `message`; avisos primeiro), `summary` (contagem
        por severidade), `total` e `rules_run`.
    """
    from modeling import audit

    return audit.audit_model(rules=rules)


@mcp.tool()
@_domain_tool
def set_table_description(table_name: str, description: str) -> dict[str, Any]:
    """Define a descrição de uma tabela (aparece como tooltip no
    painel de campos do Power BI Desktop).

    Args:
        table_name: Tabela a documentar.
        description: Texto da descrição.

    Returns:
        Dict confirmando a atualização.
    """
    from modeling import operations

    return operations.set_table_description(table_name=table_name, description=description)


@mcp.tool()
@_domain_tool
def set_column_metadata(
    table_name: str,
    column_name: str,
    description: str | None = None,
    display_folder: str | None = None,
) -> dict[str, Any]:
    """Define descrição e/ou pasta de exibição de uma coluna.

    `display_folder` organiza colunas no painel de campos do Desktop
    (ex: "Financeiro" agrupa a coluna dentro dessa pasta; use "\\" pra
    subpastas, ex: "Financeiro\\Custos"). Só os parâmetros passados
    mudam.

    Args:
        table_name: Tabela onde a coluna existe.
        column_name: Coluna a documentar/organizar.
        description: Nova descrição, se for mudar.
        display_folder: Nova pasta de exibição, se for mudar.

    Returns:
        Dict confirmando a atualização.
    """
    from modeling import operations

    return operations.set_column_metadata(
        table_name=table_name, column_name=column_name,
        description=description, display_folder=display_folder,
    )


@mcp.tool()
@_domain_tool
def set_column_sort_by(
    table_name: str,
    column_name: str,
    sort_by_column: str | None,
) -> dict[str, Any]:
    """Ordena uma coluna pelos valores de outra, em vez da ordem
    alfabética/natural padrão -- ex: "Mês" (texto: "Janeiro",
    "Fevereiro", ...) ordenado por "NumeroMes" (1, 2, ...) pra sair na
    ordem cronológica certa em vez da alfabética.

    Args:
        table_name: Tabela onde as duas colunas existem (precisam estar
            na mesma tabela).
        column_name: Coluna a ordenar.
        sort_by_column: Coluna cujos valores definem a ordem. `None`
            reverte pra ordem alfabética/natural padrão.

    Returns:
        Dict confirmando a configuração.
    """
    from modeling import operations

    return operations.set_column_sort_by(
        table_name=table_name, column_name=column_name, sort_by_column=sort_by_column
    )


@mcp.tool()
@_domain_tool
def set_column_format(
    table_name: str,
    column_name: str,
    format_string: str | None = None,
    data_category: str | None = None,
) -> dict[str, Any]:
    """Define a máscara de formatação e/ou a categoria de dado de uma
    coluna. Só os parâmetros passados mudam.

    Args:
        table_name: Tabela onde a coluna existe.
        column_name: Coluna a formatar.
        format_string: Máscara de formatação (ex: "R$ #,##0.00" pra
            moeda, "0.0%" pra percentual, "#,##0" pra inteiro com
            separador de milhar).
        data_category: Categoria de dado -- controla recursos especiais
            do Power BI (ex: "WebUrl" faz uma coluna de texto virar link
            clicável em tabela, "ImageUrl" mostra a imagem em vez da
            URL, "Address"/"City"/"Country"/"Latitude"/"Longitude"
            habilitam mapas). Passado direto pro modelo -- o Power BI
            valida o valor, não este servidor.

    Returns:
        Dict confirmando a atualização.
    """
    from modeling import operations

    return operations.set_column_format(
        table_name=table_name, column_name=column_name,
        format_string=format_string, data_category=data_category,
    )


@mcp.tool()
@_domain_tool
def set_column_visibility(table_name: str, column_name: str, is_hidden: bool) -> dict[str, Any]:
    """Esconde/reexibe uma coluna do painel de Campos do Desktop, pra
    todo mundo -- diferente de hide_column/unhide_column, que só
    escondem pra membros de um role de RLS específico.

    Args:
        table_name: Tabela onde a coluna existe.
        column_name: Coluna a esconder/reexibir.
        is_hidden: True esconde, False reexibe.

    Returns:
        Dict confirmando a atualização.
    """
    from modeling import operations

    return operations.set_column_visibility(
        table_name=table_name, column_name=column_name, is_hidden=is_hidden
    )


@mcp.tool()
@_domain_tool
def create_field_parameter(
    table_name: str,
    fields: list[str],
    display_names: list[str] | None = None,
    save: bool = True,
) -> dict[str, Any]:
    """Cria um field parameter: uma tabela especial que deixa quem lê o
    relatório trocar a métrica/dimensão de um visual direto na
    interface (equivalente a "Modelagem > Novo parâmetro > Campos" no
    Power BI Desktop).

    Depois de criado, arraste `table_name` (a coluna de nome de
    exibição) pra um slicer, ou pro field well de um visual -- role de
    dado/eixo pra campos de coluna, role de valor pra campos de medida
    (via visuals.visual_writer.set_visual_field_parameter, depois de
    criar o visual normalmente).

    CONFIRMADO AO VIVO DE PONTA A PONTA: tabela, uso num slicer, e uso
    num cartão/gráfico reagindo à seleção -- testado com 4 medidas,
    trocar a seleção no slicer mudou o valor mostrado no cartão.
    Achado que a doc oficial da Microsoft não cobre: pra um cartão/
    gráfico reagir de verdade (não só o slicer funcionar), a coluna de
    referência do campo (`Value2`, oculta) precisa de uma
    `ExtendedProperty` `"ParameterMetadata"` e a coluna de exibição
    (`Value1`) precisa de `RelatedColumnDetails` apontando pra `Value2`
    -- sem isso, o cartão dá `Missing_References`. Ver a docstring de
    `modeling.field_parameters` e README pro relato
    completo do debug.

    Args:
        table_name: Nome da tabela nova (e da coluna de exibição
            dentro dela).
        fields: Campos a incluir, na ordem desejada (ex:
            ["Vendas.Total Vendas", "Vendas.Total Custo"]).
        display_names: Nomes de exibição, na mesma ordem de `fields`.
            Precisa ter o mesmo tamanho se informado; usa o nome nativo
            do campo quando omitido.
        save: Se False, não salva a etapa final de esconder/ordenar as
            colunas auxiliares (a criação da tabela em si sempre salva
            por conta própria, pra processar e descobrir as colunas).

    Returns:
        Dict com `table_name`, `fields` (normalizados), `display_names`
        e `display_column` (nome da coluna pra arrastar num visual).
    """
    from modeling import field_parameters

    return field_parameters.create_field_parameter(
        table_name=table_name, fields=fields, display_names=display_names, save=save
    )


@mcp.tool()
@_domain_tool
def set_measure_metadata(
    table_name: str,
    measure_name: str,
    description: str | None = None,
    display_folder: str | None = None,
) -> dict[str, Any]:
    """Define descrição e/ou pasta de exibição de uma medida.

    Diferente de update_measure (que muda a lógica/formatação da
    medida), isto só organiza -- mesma ideia de display_folder de
    set_column_metadata. Só os parâmetros passados mudam.

    Args:
        table_name: Tabela onde a medida existe.
        measure_name: Medida a documentar/organizar.
        description: Nova descrição, se for mudar.
        display_folder: Nova pasta de exibição, se for mudar.

    Returns:
        Dict confirmando a atualização.
    """
    from modeling import operations

    return operations.set_measure_metadata(
        table_name=table_name, measure_name=measure_name,
        description=description, display_folder=display_folder,
    )


@mcp.tool()
@_domain_tool
def list_model_metadata(pbip_path: str | None = None) -> dict[str, Any]:
    """Lista tabelas, colunas, medidas e relacionamentos do modelo.

    Usa a conexão XMLA ativa (estabelecida por connect_to_desktop) se
    houver uma; caso contrário, se `pbip_path` for informado, lê os
    arquivos .tmdl da pasta .SemanticModel do projeto — funciona mesmo
    com o Power BI Desktop fechado. Esta é a ferramenta que a camada de
    visuais usa para saber o que existe antes de gerar um visual.

    Args:
        pbip_path: Caminho para a pasta ou arquivo .pbip do projeto, para
            leitura offline via TMDL. Opcional se já houver uma conexão
            XMLA ativa.

    Returns:
        Dict com listas `tables`, `measures` e `relationships`.
    """
    from modeling import metadata

    return metadata.list_model_metadata(pbip_path=pbip_path)


@mcp.tool()
@_domain_tool
def evaluate_dax(dax_query: str, max_rows: int | None = None) -> dict[str, Any]:
    """Executa uma consulta DAX contra o modelo e devolve os valores
    reais do resultado (não só a estrutura).

    Diferente de list_model_metadata (que lista tabelas/medidas/
    relacionamentos), esta ferramenta lê dados de verdade -- use-a para
    saber o valor agregado de uma medida, o total de uma tabela, etc.
    Exige uma consulta DAX válida e completa, por exemplo:
    'EVALUATE ROW("Total", [Total Vendas])' ou
    'EVALUATE SUMMARIZECOLUMNS(Produtos[Categoria], "Total", [Total Vendas])'.
    Também aceita uma medida ad-hoc que não existe no modelo, via
    DEFINE MEASURE: 'DEFINE MEASURE Vendas[Temp] = SUM(Vendas[Valor])
    EVALUATE ROW("Total", [Temp])' -- a medida só existe durante essa
    consulta, não é salva no modelo.

    Exige uma conexão ativa com o Power BI Desktop (connect_to_desktop).
    Não altera o modelo -- é só leitura.

    Args:
        dax_query: A consulta DAX completa (precisa começar com EVALUATE
            ou DEFINE, como no editor de consultas DAX do Power BI).
        max_rows: Se informado, limita a quantidade de linhas lidas do
            resultado (proteção contra resultado muito grande). Quando
            omitido, traz o resultado inteiro.

    Returns:
        Dict com `rows` (lista de dicts, uma por linha do resultado),
        `row_count`, e `truncated` (True se `max_rows` cortou o
        resultado antes do fim -- refine a consulta com um TOPN/filtro
        em vez de confiar só em `max_rows` pra paginação de verdade).
    """
    from modeling import query

    return query.evaluate_dax(dax_query=dax_query, max_rows=max_rows)


@mcp.tool()
@_domain_tool
def profile_measures(
    measures: list[str] | None = None,
    group_by: str | None = None,
    runs: int = 3,
    cold_cache: bool = True,
) -> dict[str, Any]:
    """Diagnóstico de DAX lento: mede quanto tempo cada medida leva e
    devolve da MAIS LENTA pra mais rápida, com dicas do guia oficial da
    Microsoft (IFERROR, FILTER dentro de CALCULATE, BLANK virando 0,
    COUNT em vez de COUNTROWS, expressão repetida sem VAR). Só leitura --
    não muda nada no modelo.

    `cold_ms` = tempo com o cache do motor limpo (o que o usuário sente
    ao abrir o relatório); `warm_ms` = mediana com cache. Os tempos
    servem pra COMPARAR medidas entre si. Com `group_by`, cada medida é
    calculada por uma coluna (como num gráfico), o que costuma revelar
    mais diferença que o valor total.

    Args:
        measures: Medidas a medir ("Tabela.Medida" ou só "Medida");
            todas do modelo quando omitido.
        group_by: Coluna pra agrupar ("Tabela.Coluna"), ex:
            "financials.Country". Omita pra medir só o total.
        runs: Execuções a quente por medida (1 a 10).
        cold_cache: Limpa o cache do motor antes de cada medida pra
            medir "a frio" (só esvazia o cache, não mexe no modelo).

    Returns:
        Dict com `measures` (ordenadas da mais lenta), cada uma com
        cold_ms, warm_ms, rows, error e hints.
    """
    from modeling import performance

    return performance.profile_measures(
        measures=measures, group_by=group_by, runs=runs, cold_cache=cold_cache
    )


@mcp.tool()
@_domain_tool
def evaluate_dax_as_role(
    dax_query: str,
    roles: list[str],
    max_rows: int | None = None,
) -> dict[str, Any]:
    """Simulação de RLS: executa uma consulta DAX "como se fosse" um ou
    mais roles de segurança (o mesmo que "Exibir como" na aba Modelagem
    do Desktop) e devolve o que esse perfil enxergaria. Use pra conferir
    se uma regra de RLS funciona antes de publicar -- ex: comparar
    `EVALUATE ROW("Vendas", [Total Sales])` como o role "Gerente
    Governo" com o mesmo cálculo filtrado à mão. Só leitura: não muda
    nada no modelo.

    Limitação: simula ROLES, não um usuário específico. RLS dinâmico
    (regra com USERPRINCIPALNAME()) não dá pra simular aqui -- o Desktop
    local não resolve um usuário arbitrário sem domínio corporativo; use
    "Exibir como > Outro usuário" no próprio Desktop.

    Args:
        dax_query: Consulta DAX completa (EVALUATE ... ou DEFINE ...).
        roles: Um ou mais roles existentes (ver list_roles). Vários
            roles = a combinação das permissões deles.
        max_rows: Limite de linhas lidas (opcional).

    Returns:
        Dict com `rows`, `row_count`, `truncated` e os `roles` usados.
    """
    from modeling import query

    return query.evaluate_dax_as_role(
        dax_query=dax_query, roles=roles, max_rows=max_rows
    )


# ---------------------------------------------------------------------------
# Camada de visuais
# ---------------------------------------------------------------------------


@mcp.tool()
@_domain_tool
def create_report_page(
    pbip_path: str,
    page_name: str,
    display_name: str | None = None,
    tooltip: bool = False,
) -> dict[str, Any]:
    """Cria uma nova página vazia no relatório PBIR.

    Com `tooltip=True`, cria uma PÁGINA DE TOOLTIP (400x300): uma
    mini-página que aparece ao passar o mouse num visual. Monte nela os
    visuais de detalhe (ex: cartão + gráfico pequeno) e ligue a um
    gráfico com set_visual_tooltip_page -- a mini-página aparece já
    filtrada pelo ponto em que o mouse está.

    Args:
        pbip_path: Caminho para a pasta ou arquivo .pbip do projeto.
        page_name: Identificador interno da página (usado como nome da
            pasta em definition/pages/).
        display_name: Nome exibido na aba da página. Usa `page_name` se
            omitido.
        tooltip: True pra criar uma página de tooltip.

    Returns:
        Dict com o nome da página criada.
    """
    from visuals import page_writer

    return page_writer.create_report_page(
        pbip_path=pbip_path, page_name=page_name, display_name=display_name, tooltip=tooltip
    )


@mcp.tool()
@_domain_tool
def delete_report_page(pbip_path: str, page_name: str) -> dict[str, Any]:
    """Remove uma página do relatório (e todos os visuais dela).

    Args:
        pbip_path: Caminho para a pasta ou arquivo .pbip do projeto.
        page_name: Página a remover.

    Returns:
        Dict confirmando a remoção.
    """
    from visuals import page_writer

    return page_writer.delete_report_page(pbip_path=pbip_path, page_name=page_name)


@mcp.tool()
@_domain_tool
def add_drillthrough_field(pbip_path: str, page_name: str, query_ref: str) -> dict[str, Any]:
    """Configura uma página como destino de drillthrough por um campo --
    o menu de clique direito "Drill through" passa a aparecer em
    qualquer visual de outra página que use esse mesmo campo, sem
    precisar mexer na página de origem.

    Chame de novo com outro `query_ref` na mesma página pra adicionar
    mais um campo de drillthrough (o usuário poderá escolher qual campo
    usar ao clicar com o botão direito).

    Args:
        pbip_path: Caminho para a pasta ou arquivo .pbip do projeto.
        page_name: Página que vai virar o destino do drillthrough.
        query_ref: Campo pelo qual o drillthrough acontece, no formato
            "Tabela.Coluna" (ex: "financials.Segment").

    Returns:
        Dict com `page_name`, `query_ref` normalizado e `filter_name`
        (identificador interno gerado pro filtro).
    """
    from visuals import page_writer

    return page_writer.add_drillthrough_field(
        pbip_path=pbip_path, page_name=page_name, query_ref=query_ref
    )


@mcp.tool()
@_domain_tool
def remove_drillthrough_field(pbip_path: str, page_name: str, query_ref: str) -> dict[str, Any]:
    """Reverte add_drillthrough_field: remove um campo de drillthrough
    de uma página. Se era o último campo, a página deixa de ser um
    destino de drillthrough por completo.

    Args:
        pbip_path: Caminho para a pasta ou arquivo .pbip do projeto.
        page_name: Página de onde remover o campo de drillthrough.
        query_ref: Campo a remover, no formato "Tabela.Coluna".

    Returns:
        Dict confirmando a remoção.
    """
    from visuals import page_writer

    return page_writer.remove_drillthrough_field(
        pbip_path=pbip_path, page_name=page_name, query_ref=query_ref
    )


@mcp.tool()
@_domain_tool
def add_visual_filter(
    pbip_path: str,
    page_name: str,
    visual_name: str,
    query_ref: str,
    filter_type: Literal["categorical", "between", "comparison"],
    values: list[Any] | None = None,
    exclude: bool = False,
    lower: Any = None,
    upper: Any = None,
    operator: Literal["eq", "gt", "gte", "lt", "lte"] | None = None,
    value: Any = None,
) -> dict[str, Any]:
    """Filtro com valor em UM visual só (mesmos tipos de add_page_filter).
    Ex: um gráfico com a coluna de um calculation group na legenda,
    limitado aos itens "Atual" e "PY".

    Escreve direto no disco (PBIR) -- mesma regra de add_visual: no Desktop, clique em
    "Apply external changes" ("Aplicar alterações externas") (ou feche sem salvar e reabra); NÃO chame save_desktop logo depois.

    Args:
        pbip_path: Caminho para a pasta ou arquivo .pbip do projeto.
        page_name: Página do visual.
        visual_name: Visual (ver list_visuals).
        query_ref: Coluna filtrada, no formato "Tabela.Coluna".

    Returns:
        Dict com `scope`, `query_ref`, `filter_name` e `type`.
    """
    from visuals import filter_writer

    return filter_writer.add_visual_filter(
        pbip_path=pbip_path, page_name=page_name, visual_name=visual_name, query_ref=query_ref,
        filter_type=filter_type, values=values, exclude=exclude,
        lower=lower, upper=upper, operator=operator, value=value,
    )


@mcp.tool()
@_domain_tool
def remove_visual_filter(pbip_path: str, page_name: str, visual_name: str, query_ref: str) -> dict[str, Any]:
    """Remove o filtro com valor de um visual (ver add_visual_filter).

    Escreve direto no disco (PBIR) -- mesma regra de add_visual: no Desktop, clique em
    "Apply external changes" ("Aplicar alterações externas") (ou feche sem salvar e reabra); NÃO chame save_desktop logo depois.

    Args:
        pbip_path: Caminho para a pasta ou arquivo .pbip do projeto.
        page_name: Página do visual.
        visual_name: Visual.
        query_ref: Coluna do filtro, no formato "Tabela.Coluna".

    Returns:
        Dict confirmando a remoção.
    """
    from visuals import filter_writer

    return filter_writer.remove_visual_filter(
        pbip_path=pbip_path, page_name=page_name, visual_name=visual_name, query_ref=query_ref,
    )


@mcp.tool()
@_domain_tool
def set_visual_hidden(pbip_path: str, page_name: str, visual_name: str, hidden: bool) -> dict[str, Any]:
    """Esconde (ou mostra) um visual na página. Uso típico: um painel de
    informações que começa escondido e aparece por um bookmark de
    mostrar/esconder (create_bookmark com visible_visuals/hidden_visuals).

    Escreve direto no disco (PBIR) -- mesma regra de add_visual: no Desktop, clique em
    "Apply external changes" ("Aplicar alterações externas") (ou feche sem salvar e reabra); NÃO chame save_desktop logo depois.

    Args:
        pbip_path: Caminho para a pasta ou arquivo .pbip do projeto.
        page_name: Página do visual.
        visual_name: Visual.
        hidden: True esconde, False mostra.

    Returns:
        Dict confirmando o estado.
    """
    from visuals import visual_writer

    return visual_writer.set_visual_hidden(
        pbip_path=pbip_path, page_name=page_name, visual_name=visual_name, hidden=hidden,
    )


@mcp.tool()
@_domain_tool
def set_button_slicer_style(
    pbip_path: str,
    page_name: str,
    visual_name: str,
    single_select: bool | None = None,
    force_selection: bool | None = None,
    tiles_per_row: int | None = None,
    rows: int | None = None,
    tile_spacing: int | None = None,
    tile_color: str | None = None,
    tile_transparency: float | None = None,
    selected_tile_color: str | None = None,
    selected_tile_transparency: float | None = None,
    text_color: str | None = None,
    selected_text_color: str | None = None,
    text_size: float | None = None,
    text_bold: bool | None = None,
    text_transparency: float | None = None,
    outline_show: bool | None = None,
    outline_color: str | None = None,
    outline_weight: float | None = None,
    outline_transparency: float | None = None,
    selected_outline_color: str | None = None,
    corner_radius: int | None = None,
) -> dict[str, Any]:
    """Formata um SLICER DE BOTÕES (add_visual com
    visual_type="advancedSlicerVisual" -- ladrilhos clicáveis, ex: anos
    2013 | 2014, moedas USD | EUR). Cores do ladrilho e do texto no estado
    normal e SELECIONADO, seleção única, ladrilhos por linha, contorno e
    cantos.

    Truque "cartão clicável": ponha o slicer de botões por cima de
    cartões desenhados, com ladrilho e texto transparentes
    (tile_transparency=100, selected_tile_transparency=100,
    text_transparency=100) e só o contorno do selecionado colorido
    (outline_show=True, outline_transparency=100,
    selected_outline_color="#...").

    Escreve direto no disco (PBIR) -- mesma regra de add_visual: no Desktop, clique em
    "Apply external changes" ("Aplicar alterações externas") (ou feche sem salvar e reabra); NÃO chame save_desktop logo depois.

    Args:
        pbip_path: Caminho para a pasta ou arquivo .pbip do projeto.
        page_name: Página do slicer.
        visual_name: Slicer de botões (ver list_visuals).
        single_select: Só um item por vez.
        force_selection: Sempre um item marcado ("Forçar seleção") -- use com
            field parameter, senão sem seleção o gráfico mostra todas as métricas.
        tiles_per_row: Ladrilhos por linha (colunas da grade).
        rows: Linhas da grade (ex: 1 pra todos numa linha só).
        tile_spacing: Espaço entre ladrilhos em px (padrão do Desktop: 8) -- pra
            alinhar com cartões desenhados, use o mesmo vão do desenho.
        tile_color: Cor do ladrilho normal (hexadecimal).
        tile_transparency: Transparência do ladrilho normal (0 a 100).
        selected_tile_color: Cor do ladrilho selecionado.
        selected_tile_transparency: Transparência do selecionado (0 a 100).
        text_color: Cor do texto normal.
        selected_text_color: Cor do texto do selecionado.
        text_size: Tamanho do texto em pt (8 a 60).
        text_bold: Texto em negrito.
        text_transparency: Transparência do texto (0 a 100).
        outline_show: Mostra/esconde o contorno dos ladrilhos.
        outline_color: Cor do contorno normal.
        outline_weight: Espessura do contorno.
        outline_transparency: Transparência do contorno normal (0 a 100).
        selected_outline_color: Cor do contorno do selecionado.
        corner_radius: Arredondamento dos cantos (px).

    Returns:
        Dict com o que mudou.
    """
    from visuals import formatting

    return formatting.set_button_slicer_style(
        pbip_path=pbip_path, page_name=page_name, visual_name=visual_name,
        single_select=single_select, force_selection=force_selection, tiles_per_row=tiles_per_row, rows=rows, tile_spacing=tile_spacing,
        tile_color=tile_color, tile_transparency=tile_transparency,
        selected_tile_color=selected_tile_color, selected_tile_transparency=selected_tile_transparency,
        text_color=text_color, selected_text_color=selected_text_color, text_size=text_size,
        text_bold=text_bold, text_transparency=text_transparency, outline_show=outline_show,
        outline_color=outline_color, outline_weight=outline_weight,
        outline_transparency=outline_transparency, selected_outline_color=selected_outline_color,
        corner_radius=corner_radius,
    )


@mcp.tool()
@_domain_tool
def add_page_filter(
    pbip_path: str,
    page_name: str,
    query_ref: str,
    filter_type: Literal["categorical", "between", "comparison"],
    values: list[Any] | None = None,
    exclude: bool = False,
    lower: Any = None,
    upper: Any = None,
    operator: Literal["eq", "gt", "gte", "lt", "lte"] | None = None,
    value: Any = None,
) -> dict[str, Any]:
    """Pré-aplica um filtro com valor numa página inteira (painel
    "Filtros nesta página"), sem precisar de slicer -- ex: Segment =
    Government pra todos os visuais da página.
    Tipos de filtro (`filter_type`):
      - "categorical": lista de valores -- `values` (ex: ["Government"]);
        `exclude=True` inverte (tudo MENOS esses valores).
      - "between": faixa inclusiva -- `lower` e `upper` (ex: 2013, 2014).
      - "comparison": `operator` ("eq", "gt", "gte", "lt", "lte") + `value`.
    Só em coluna (não medida), e TopN não é suportado (só existe em nível
    de visual). Datas como "2014-01-01" ou "2014-01-01T10:30:00".

    Escreve direto no disco (PBIR) -- mesma regra de add_visual: se o
    Desktop estiver aberto com o projeto, clique em "Apply external changes" ("Aplicar alterações externas") no Desktop (ou feche sem salvar e reabra) pra
    ver o filtro; NÃO chame save_desktop logo depois (apagaria a mudança).

    Args:
        pbip_path: Caminho para a pasta ou arquivo .pbip do projeto.
        page_name: Página onde aplicar o filtro.
        query_ref: Coluna filtrada, no formato "Tabela.Coluna".

    Returns:
        Dict com `scope`, `query_ref`, `filter_name` e `type`.
    """
    from visuals import filter_writer

    return filter_writer.add_page_filter(
        pbip_path=pbip_path, page_name=page_name, query_ref=query_ref,
        filter_type=filter_type, values=values, exclude=exclude,
        lower=lower, upper=upper, operator=operator, value=value,
    )


@mcp.tool()
@_domain_tool
def remove_page_filter(pbip_path: str, page_name: str, query_ref: str) -> dict[str, Any]:
    """Remove o filtro com valor em `query_ref` de uma página (não mexe
    num campo de drillthrough no mesmo campo, se houver).

    Args:
        pbip_path: Caminho para a pasta ou arquivo .pbip do projeto.
        page_name: Página de onde remover o filtro.
        query_ref: Coluna do filtro, no formato "Tabela.Coluna".

    Returns:
        Dict confirmando a remoção.
    """
    from visuals import filter_writer

    return filter_writer.remove_page_filter(
        pbip_path=pbip_path, page_name=page_name, query_ref=query_ref
    )


@mcp.tool()
@_domain_tool
def add_report_filter(
    pbip_path: str,
    query_ref: str,
    filter_type: Literal["categorical", "between", "comparison"],
    values: list[Any] | None = None,
    exclude: bool = False,
    lower: Any = None,
    upper: Any = None,
    operator: Literal["eq", "gt", "gte", "lt", "lte"] | None = None,
    value: Any = None,
) -> dict[str, Any]:
    """Pré-aplica um filtro com valor no relatório inteiro (painel
    "Filtros em todas as páginas") -- ex: Year entre 2013 e 2014 em
    todas as páginas. Preserva o resto do report.json (tema etc).
    Tipos de filtro (`filter_type`):
      - "categorical": lista de valores -- `values` (ex: ["Government"]);
        `exclude=True` inverte (tudo MENOS esses valores).
      - "between": faixa inclusiva -- `lower` e `upper` (ex: 2013, 2014).
      - "comparison": `operator` ("eq", "gt", "gte", "lt", "lte") + `value`.
    Só em coluna (não medida), e TopN não é suportado (só existe em nível
    de visual). Datas como "2014-01-01" ou "2014-01-01T10:30:00".

    Escreve direto no disco (PBIR) -- mesma regra de add_visual: se o
    Desktop estiver aberto com o projeto, clique em "Apply external changes" ("Aplicar alterações externas") no Desktop (ou feche sem salvar e reabra) pra
    ver o filtro; NÃO chame save_desktop logo depois (apagaria a mudança).

    Args:
        pbip_path: Caminho para a pasta ou arquivo .pbip do projeto.
        query_ref: Coluna filtrada, no formato "Tabela.Coluna".

    Returns:
        Dict com `scope` ("report"), `query_ref`, `filter_name` e `type`.
    """
    from visuals import filter_writer

    return filter_writer.add_report_filter(
        pbip_path=pbip_path, query_ref=query_ref,
        filter_type=filter_type, values=values, exclude=exclude,
        lower=lower, upper=upper, operator=operator, value=value,
    )


@mcp.tool()
@_domain_tool
def remove_report_filter(pbip_path: str, query_ref: str) -> dict[str, Any]:
    """Remove o filtro com valor em `query_ref` do relatório.

    Args:
        pbip_path: Caminho para a pasta ou arquivo .pbip do projeto.
        query_ref: Coluna do filtro, no formato "Tabela.Coluna".

    Returns:
        Dict confirmando a remoção.
    """
    from visuals import filter_writer

    return filter_writer.remove_report_filter(pbip_path=pbip_path, query_ref=query_ref)


@mcp.tool()
@_domain_tool
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
    """Adiciona um visual a uma página existente.

    Cada nome de tabela/coluna/medida em `fields` é validado contra o
    modelo (via list_model_metadata) antes de qualquer arquivo ser
    escrito — se algum campo não existir, a ferramenta falha sem gerar
    um visual quebrado.

    `textbox` é diferente dos demais: não usa `fields` (não referencia
    o modelo) — use `text` para o conteúdo. Uma linha por `\n` vira um
    parágrafo. Não passe `fields` e `text` ao mesmo tempo.

    Args:
        pbip_path: Caminho para a pasta ou arquivo .pbip do projeto.
        page_name: Página onde o visual será adicionado.
        visual_type: Um dos tipos suportados (ver
            visuals.catalog.VISUAL_TYPES): card, clusteredColumnChart,
            clusteredBarChart, lineChart, donutChart, tableEx, slicer,
            textbox, pivotTable (a "matriz"), waterfallChart (cascata),
            scatterChart (dispersão), columnChart/barChart (empilhado),
            areaChart, stackedAreaChart, hundredPercentStackedColumnChart,
            hundredPercentStackedBarChart, pieChart, treemap, funnel,
            gauge, kpi, cardVisual (cartão atual, aceita várias medidas
            em `Data`), azureMap, advancedSlicerVisual (slicer de
            botões/ladrilhos -- formate com set_button_slicer_style) -- ou o
            GUID de um visual personalizado
            importado (import_custom_visual / list_custom_visuals), com
            os roles dele. Ver README, seção "Validação real",
            para o que já foi confirmado ao vivo.
        x: Posição horizontal (esquerda) em pixels.
        y: Posição vertical (topo) em pixels.
        width: Largura em pixels.
        height: Altura em pixels.
        fields: Mapa de role (ex: "Category", "Y", "Values") para lista
            de referências de campo no formato "Tabela.Coluna" ou
            "Tabela.Medida". Obrigatório para todos os tipos exceto
            textbox. Em gráfico de barras/colunas/linha/área, vários
            campos em "Category" (ex: ["t.Segment", "t.Product"]) viram
            drill-down: abre no primeiro nível e o usuário desce pelos
            botões de drill do visual. Nesses mesmos gráficos,
            "Tooltips" (só medidas) acrescenta campos na dica de
            ferramenta que aparece ao passar o mouse. Árvore de
            decomposição ("decompositionTreeVisual"): "Analyze" (1 medida)
            e "ExplainBy" (colunas, uma por nível) -- abra os níveis com
            expand_decomposition_tree.
        text: Conteúdo de texto. Só para visual_type="textbox";
            obrigatório nesse caso, e não deve ser usado com `fields`.

    Returns:
        Dict com o nome do visual criado e os campos resolvidos (ou o
        texto, no caso de textbox).
    """
    from visuals import visual_writer

    return visual_writer.add_visual(
        pbip_path=pbip_path,
        page_name=page_name,
        visual_type=visual_type,
        x=x,
        y=y,
        width=width,
        height=height,
        fields=fields,
        text=text,
    )


@mcp.tool()
@_domain_tool
def list_visuals(pbip_path: str, page_name: str) -> list[dict[str, Any]]:
    """Lista os visuais existentes numa página, com posição e conteúdo
    básico -- use antes de editar/remover um visual criado numa chamada
    anterior sem precisar lembrar o `visual_name` gerado na criação.

    Args:
        pbip_path: Caminho para a pasta ou arquivo .pbip do projeto.
        page_name: Página a listar.

    Returns:
        Lista de dicts, um por visual: `visual_name`, `visual_type`,
        `page_name`, `position` (x/y/width/height), e `fields` (visual
        ligado a dado) ou `text` (textbox) quando aplicável.
    """
    from visuals import visual_writer

    return visual_writer.list_visuals(pbip_path=pbip_path, page_name=page_name)


@mcp.tool()
@_domain_tool
def delete_visual(pbip_path: str, page_name: str, visual_name: str) -> dict[str, Any]:
    """Remove um visual de uma página.

    Args:
        pbip_path: Caminho para a pasta ou arquivo .pbip do projeto.
        page_name: Página onde o visual está.
        visual_name: Nome (identificador) do visual, devolvido por
            add_visual/apply_dashboard_blueprint na criação.

    Returns:
        Dict confirmando a remoção.
    """
    from visuals import visual_writer

    return visual_writer.delete_visual(
        pbip_path=pbip_path, page_name=page_name, visual_name=visual_name
    )


@mcp.tool()
@_domain_tool
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
) -> dict[str, Any]:
    """Atualiza um visual já existente, no lugar (mesmo nome/pasta).

    Cada parâmetro omitido mantém o valor atual -- passe só `x`/`y`/
    `width`/`height` para reposicionar sem tocar no conteúdo. Passar
    `fields` (visual ligado a dado) ou `text` (textbox) substitui o
    conteúdo por completo, revalidado exatamente como em add_visual. Com
    `fields`, a formatação (cores, título, fundo), os filtros do visual e
    a visibilidade são mantidos -- só os campos mudam.

    Args:
        pbip_path: Caminho para a pasta ou arquivo .pbip do projeto.
        page_name: Página onde o visual está.
        visual_name: Nome (identificador) do visual a atualizar.
        x: Nova posição horizontal, se for mudar.
        y: Nova posição vertical, se for mudar.
        width: Nova largura, se for mudar.
        height: Nova altura, se for mudar.
        fields: Novo mapa de role -> campos, se for mudar o conteúdo
            (só para visuais ligados a dado).
        text: Novo texto, se for mudar o conteúdo (só para textbox).

    Returns:
        Dict com o estado atualizado do visual.
    """
    from visuals import visual_writer

    return visual_writer.update_visual(
        pbip_path=pbip_path,
        page_name=page_name,
        visual_name=visual_name,
        x=x,
        y=y,
        width=width,
        height=height,
        fields=fields,
        text=text,
    )


@mcp.tool()
@_domain_tool
def set_slicer_sync(
    pbip_path: str,
    page_name: str,
    visual_name: str,
    group_name: str,
    field_changes: bool = True,
    filter_changes: bool = True,
) -> dict[str, Any]:
    """Sincroniza um slicer com outros slicers que tenham o mesmo
    `group_name` (em qualquer página do relatório) -- selecionar um
    valor num propaga pros demais automaticamente.

    Args:
        pbip_path: Caminho para a pasta ou arquivo .pbip do projeto.
        page_name: Página onde o slicer está.
        visual_name: Slicer a sincronizar (precisa ser
            "slicer" ou slicer de botões "advancedSlicerVisual").
        group_name: Nome do grupo de sincronização -- use o mesmo em
            todos os slicers que devem ficar sincronizados.
        field_changes: Atualizar os demais quando o campo do slicer
            mudar.
        filter_changes: Atualizar os demais quando o filtro (seleção)
            mudar.

    Returns:
        Dict com o `sync_group` configurado.
    """
    from visuals import visual_writer

    return visual_writer.set_slicer_sync(
        pbip_path=pbip_path, page_name=page_name, visual_name=visual_name,
        group_name=group_name, field_changes=field_changes, filter_changes=filter_changes,
    )


@mcp.tool()
@_domain_tool
def remove_slicer_sync(pbip_path: str, page_name: str, visual_name: str) -> dict[str, Any]:
    """Reverte set_slicer_sync -- volta o slicer a não estar
    sincronizado com nenhum grupo.

    Args:
        pbip_path: Caminho para a pasta ou arquivo .pbip do projeto.
        page_name: Página onde o slicer está.
        visual_name: Slicer a desincronizar.

    Returns:
        Dict confirmando a remoção do sync.
    """
    from visuals import visual_writer

    return visual_writer.remove_slicer_sync(
        pbip_path=pbip_path, page_name=page_name, visual_name=visual_name
    )


@mcp.tool()
@_domain_tool
def set_slicer_config(
    pbip_path: str,
    page_name: str,
    visual_name: str,
    style: str | None = None,
    selection_mode: Literal["single", "multi_ctrl", "multi"] | None = None,
    show_select_all: bool | None = None,
    show_search: bool | None = None,
) -> dict[str, Any]:
    """Configura um slicer (`visual_type="slicer"` -- não funciona em
    `listSlicer`/`advancedSlicerVisual`): estilo, modo de seleção,
    opção "Selecionar tudo" e caixa de pesquisa. Só os parâmetros
    passados mudam.

    O botão de limpar seleção (borracha) não é configurável -- aparece
    sozinho no cabeçalho do slicer.

    Escreve direto no disco (PBIR) -- mesma regra de add_visual: no Desktop, clique em
    "Apply external changes" ("Aplicar alterações externas") (ou feche sem salvar e reabra); NÃO chame save_desktop logo depois.

    Args:
        pbip_path: Caminho para a pasta ou arquivo .pbip do projeto.
        page_name: Página onde o slicer está.
        visual_name: Slicer a configurar.
        style: Um de "Dropdown" (caixa suspensa), "Basic" (lista),
            "Between" (intervalo), "Single" (seleção única), "Before"/
            "After" (limite superior/inferior), "Relative" (data
            relativa, ex: "últimos 30 dias") ou "RelativeTime" (tempo
            relativo, ex: "últimas 2 horas"). "Relative"/"RelativeTime"
            exigem um campo de data/hora no slicer.
        selection_mode: "single" (só um item por vez -- ATENÇÃO: o Power BI
            mantém SEMPRE um item selecionado e escolhe o primeiro sozinho;
            num filtro que deve começar em "todos", use "multi_ctrl"), "multi_ctrl"
            (padrão do Power BI: clique seleciona um, CTRL+clique
            acrescenta) ou "multi" (cada clique acrescenta, sem CTRL).
        show_select_all: Mostra/esconde a opção "Selecionar tudo".
        show_search: Mostra/esconde a caixa de pesquisa no topo.

    Returns:
        Dict confirmando a configuração.
    """
    from visuals import visual_writer

    return visual_writer.set_slicer_config(
        pbip_path=pbip_path, page_name=page_name, visual_name=visual_name, style=style,
        selection_mode=selection_mode, show_select_all=show_select_all, show_search=show_search,
    )


@mcp.tool()
@_domain_tool
def add_navigation_button(
    pbip_path: str,
    page_name: str,
    x: float,
    y: float,
    width: float,
    height: float,
    target_type: Literal["page", "bookmark", "clear_slicers"],
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
    ou LIMPA as segmentações da página ("voltar ao padrão") ao ser
    clicado. No Desktop o clique funciona com CTRL+clique (ou no modo de
    leitura).

    Truque pra dashboards com imagem de fundo: desenhe o botão no fundo
    (círculo, ícone) e ponha por cima um botão `transparent=True` do
    mesmo tamanho -- fica invisível e clicável.

    Escreve direto no disco (PBIR) -- mesma regra de add_visual: no Desktop, clique em
    "Apply external changes" ("Aplicar alterações externas") (ou feche sem salvar e reabra); NÃO chame save_desktop logo depois.

    Args:
        pbip_path: Caminho para a pasta ou arquivo .pbip do projeto.
        page_name: Página onde o botão será adicionado.
        x: Posição horizontal (esquerda) em pixels.
        y: Posição vertical (topo) em pixels.
        width: Largura em pixels.
        height: Altura em pixels.
        target_type: "page" (navega para uma página -- `target` é o
            `page_name` interno), "bookmark" (aplica um bookmark --
            `target` é o `bookmark_name`, criado via create_bookmark) ou
            "clear_slicers" (limpa todas as segmentações da página; sem
            `target`).
        target: Página ou bookmark de destino, conforme `target_type`.
        transparent: Botão invisível (sem preenchimento, contorno, texto,
            ícone, fundo nem borda) -- pra pôr por cima de um desenho.
        text: Rótulo do botão.
        text_color: Cor do rótulo (hexadecimal).
        text_size: Tamanho do rótulo em pt.
        icon_path: Ícone PERSONALIZADO do botão (arquivo .png/.svg/...) --
            com transparent=True vira um botão que mostra só o ícone.
        fill_color: Cor de fundo do botão (hex). Sem ela o Desktop usa a
            cor padrão do tema (em geral azul). Não combina com transparent.
        corner_radius: Arredondamento dos cantos (px), junto com fill_color.

    Returns:
        Dict com o nome do botão criado e o destino configurado.
    """
    from visuals import visual_writer

    return visual_writer.add_navigation_button(
        pbip_path=pbip_path, page_name=page_name, x=x, y=y, width=width, height=height,
        target_type=target_type, target=target, transparent=transparent,
        text=text, text_color=text_color, text_size=text_size, icon_path=icon_path,
        fill_color=fill_color, corner_radius=corner_radius,
    )


@mcp.tool()
@_domain_tool
def create_bookmark(
    pbip_path: str,
    bookmark_name: str,
    page_name: str,
    display_name: str | None = None,
    visible_visuals: list[str] | None = None,
    hidden_visuals: list[str] | None = None,
) -> dict[str, Any]:
    """Cria um bookmark. Dois usos:
    - só `page_name`: ao aplicar, vai pra essa página;
    - com `visible_visuals`/`hidden_visuals`: MOSTRA/ESCONDE visuais
      nessa página, sem trocar de página nem mexer em filtro/slicer.
      Ex: painel de informações -- crie o painel (textbox/forma +
      botão fechar), esconda com set_visual_hidden, e faça dois
      bookmarks: "Mostrar info" (visíveis) e "Esconder info"
      (escondidos), ligados a botões com target_type="bookmark".

    Args:
        pbip_path: Caminho para a pasta ou arquivo .pbip do projeto.
        bookmark_name: Identificador interno do bookmark.
        page_name: Página que este bookmark ativa. Precisa já existir.
        display_name: Nome exibido no painel de bookmarks. Usa
            `bookmark_name` se omitido.
        visible_visuals: Visuais que ficam visíveis ao aplicar.
        hidden_visuals: Visuais que ficam escondidos ao aplicar.

    Returns:
        Dict com o bookmark criado.
    """
    from visuals import bookmark_writer

    return bookmark_writer.create_bookmark(
        pbip_path=pbip_path, bookmark_name=bookmark_name, page_name=page_name,
        display_name=display_name, visible_visuals=visible_visuals, hidden_visuals=hidden_visuals,
    )


@mcp.tool()
@_domain_tool
def create_reset_bookmark(
    pbip_path: str,
    bookmark_name: str,
    page_name: str,
    display_name: str | None = None,
) -> dict[str, Any]:
    """Cria um bookmark "voltar ao padrão" da página: guarda a seleção de
    cada slicer, os filtros de visual, o nível de drill dos gráficos e o
    que está escondido. Ligue um botão a ele (add_navigation_button com
    target_type="bookmark") pra ter um "resetar tudo" -- diferente do
    "Limpar segmentações", ele também desfaz clique em gráfico e volta slicer
    de seleção obrigatória (ex: moeda) pro valor padrão.

    Captura o estado SALVO nos arquivos: antes, deixe a página no padrão
    no Desktop e salve (Ctrl+S) -- o Desktop grava a seleção dos slicers.

    Escreve direto no disco (PBIR) -- mesma regra de add_visual: no Desktop, clique em
    "Apply external changes" ("Aplicar alterações externas") (ou feche sem salvar e reabra); NÃO chame save_desktop logo depois.

    Args:
        pbip_path: Caminho para a pasta ou arquivo .pbip do projeto.
        bookmark_name: Nome interno do bookmark (letras, números, _ e -).
        page_name: Página cujo estado padrão será guardado.
        display_name: Nome que aparece no painel de Indicadores.

    Returns:
        Dict com o bookmark, quantos visuais foram capturados e quais
        slicers tinham seleção salva.
    """
    from visuals import bookmark_writer

    return bookmark_writer.create_reset_bookmark(
        pbip_path=pbip_path, bookmark_name=bookmark_name, page_name=page_name, display_name=display_name,
    )


@mcp.tool()
@_domain_tool
def delete_bookmark(pbip_path: str, bookmark_name: str) -> dict[str, Any]:
    """Remove um bookmark.

    Args:
        pbip_path: Caminho para a pasta ou arquivo .pbip do projeto.
        bookmark_name: Bookmark a remover.

    Returns:
        Dict confirmando a remoção.
    """
    from visuals import bookmark_writer

    return bookmark_writer.delete_bookmark(pbip_path=pbip_path, bookmark_name=bookmark_name)


@mcp.tool()
@_domain_tool
def list_bookmarks(pbip_path: str) -> list[dict[str, Any]]:
    """Lista os bookmarks existentes no relatório.

    Args:
        pbip_path: Caminho para a pasta ou arquivo .pbip do projeto.

    Returns:
        Lista de dicts, cada um com `bookmark_name`, `display_name` e
        `page_name`.
    """
    from visuals import bookmark_writer

    return bookmark_writer.list_bookmarks(pbip_path=pbip_path)


@mcp.tool()
@_domain_tool
def set_visual_color(
    pbip_path: str,
    page_name: str,
    visual_name: str,
    query_ref: str,
    hex_color: str,
    value: Any = None,
) -> dict[str, Any]:
    """Define a cor de uma série/categoria específica dentro de um
    visual (ex: fixar "Vendas.Total Vendas" sempre em azul) -- ou, com
    `value`, de UM ITEM de uma coluna de legenda/categoria (ex:
    query_ref="Inteligencia de Tempo.Calculo", value="PY" em cinza).

    Args:
        pbip_path: Caminho para a pasta ou arquivo .pbip do projeto.
        page_name: Página onde o visual está.
        visual_name: Visual a formatar.
        query_ref: Referência de campo exatamente como usada em
            `fields` na criação do visual (ex: "Vendas.Total Vendas").
            Chamar de novo com o mesmo query_ref substitui a cor.
        hex_color: Cor em hexadecimal, com "#" (ex: "#2E86AB").
        value: Item da coluna de `query_ref` a pintar (ex: "PY", "Government").

    Returns:
        Dict confirmando a cor aplicada.
    """
    from visuals import visual_writer

    return visual_writer.set_visual_color(
        pbip_path=pbip_path, page_name=page_name, visual_name=visual_name,
        query_ref=query_ref, hex_color=hex_color, value=value,
    )


@mcp.tool()
@_domain_tool
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
    """Configura o título de um visual e o subtítulo. Só os parâmetros
    passados mudam. O Desktop costuma mostrar um subtítulo automático
    ("Total Sales e Total Profit por Country") -- esconda com
    subtitle_show=False pra um visual mais limpo.

    Args:
        pbip_path: Caminho para a pasta ou arquivo .pbip do projeto.
        page_name: Página onde o visual está.
        visual_name: Visual a formatar.
        text: Novo texto do título, se for mudar.
        font_size: Novo tamanho de fonte (pt), se for mudar.
        font_color: Nova cor do texto, em hexadecimal com "#", se for mudar.
        show: True/False pra mostrar ou esconder o título por completo.
        subtitle_show: True/False pra mostrar ou esconder o subtítulo.
        subtitle_text: Texto do subtítulo (ex: "Ano de 2014").

    Returns:
        Dict confirmando o que foi configurado.
    """
    from visuals import visual_writer

    return visual_writer.set_visual_title(
        pbip_path=pbip_path, page_name=page_name, visual_name=visual_name,
        text=text, font_size=font_size, font_color=font_color, show=show,
        subtitle_show=subtitle_show, subtitle_text=subtitle_text,
    )


@mcp.tool()
@_domain_tool
def set_textbox_style(
    pbip_path: str,
    page_name: str,
    visual_name: str,
    font_size: float | None = None,
    bold: bool | None = None,
    italic: bool | None = None,
    underline: bool | None = None,
    color: str | None = None,
    font_family: str | None = None,
    alignment: Literal["left", "center", "right"] | None = None,
    line: int | None = None,
) -> dict[str, Any]:
    """Formata o texto de um textbox (ex: o título de uma página):
    tamanho, negrito, itálico, sublinhado, cor, fonte e alinhamento.
    Aplica em todas as linhas, ou só em `line` -- ex: linha 1 = título
    grande em negrito, linha 2 = subtítulo menor. Só o que for passado
    muda. Um textbox recém-criado por add_visual vem em 12pt, alinhado à
    esquerda, sem destaque -- use esta tool pra deixar com cara de
    título. Se trocar o texto com update_visual, aplique o estilo de
    novo (o texto novo volta ao padrão).

    Pra fundo/borda (faixa colorida atrás do título), use
    set_visual_container_style. Pra título de GRÁFICO (não textbox), use
    set_visual_title.

    Escreve direto no disco (PBIR) -- mesma regra de add_visual: no Desktop, clique em
    "Apply external changes" ("Aplicar alterações externas") (ou feche sem salvar e reabra); NÃO chame save_desktop logo depois.

    Args:
        pbip_path: Caminho para a pasta ou arquivo .pbip do projeto.
        page_name: Página do textbox.
        visual_name: Textbox (ver list_visuals).
        font_size: Tamanho em pt (8 a 60; título costuma ficar entre 20 e 32).
        bold: Negrito.
        italic: Itálico.
        underline: Sublinhado.
        color: Cor do texto em hexadecimal (ex: "#1F3864").
        font_family: Fonte (ex: "Segoe UI Semibold").
        alignment: "left", "center" ou "right".
        line: Só essa linha (1 = primeira); todas quando omitido.

    Returns:
        Dict com as linhas alteradas.
    """
    from visuals import formatting

    return formatting.set_textbox_style(
        pbip_path=pbip_path, page_name=page_name, visual_name=visual_name, font_size=font_size,
        bold=bold, italic=italic, underline=underline, color=color, font_family=font_family,
        alignment=alignment, line=line,
    )


@mcp.tool()
@_domain_tool
def set_visual_container_style(
    pbip_path: str,
    page_name: str,
    visual_name: str,
    background_show: bool | None = None,
    background_color: str | None = None,
    background_transparency: float | None = None,
    border_show: bool | None = None,
    border_color: str | None = None,
    border_width: float | None = None,
    border_radius: float | None = None,
    padding: float | None = None,
) -> dict[str, Any]:
    """Moldura de QUALQUER visual: cor/transparência do fundo e borda
    (mostrar, cor, largura, cantos arredondados). Ex: faixa colorida
    atrás do título da página (textbox), ou cartões com fundo branco e
    borda arredondada. Passar uma cor já liga o fundo/borda. Só o que for
    passado muda; título e demais formatações do visual são preservados.

    Escreve direto no disco (PBIR) -- mesma regra de add_visual: no Desktop, clique em
    "Apply external changes" ("Aplicar alterações externas") (ou feche sem salvar e reabra); NÃO chame save_desktop logo depois.

    Args:
        pbip_path: Caminho para a pasta ou arquivo .pbip do projeto.
        page_name: Página do visual.
        visual_name: Visual (ver list_visuals).
        background_show: Mostra/esconde o fundo.
        background_color: Cor do fundo em hexadecimal.
        background_transparency: Transparência do fundo, 0 (opaco) a 100.
        border_show: Mostra/esconde a borda.
        border_color: Cor da borda em hexadecimal.
        border_width: Largura da borda.
        border_radius: Arredondamento dos cantos.
        padding: Espaço interno (px) nos 4 lados -- ex: texto que não
            fica colado na borda.

    Returns:
        Dict com o tipo do visual e o que mudou.
    """
    from visuals import formatting

    return formatting.set_visual_container_style(
        pbip_path=pbip_path, page_name=page_name, visual_name=visual_name,
        background_show=background_show, background_color=background_color,
        background_transparency=background_transparency, border_show=border_show,
        border_color=border_color, border_width=border_width, border_radius=border_radius,
        padding=padding,
    )


@mcp.tool()
@_domain_tool
def set_visual_alt_text(pbip_path: str, page_name: str, visual_name: str, text: str) -> dict[str, Any]:
    """Texto alternativo de um visual -- o que um leitor de tela (pessoa
    com deficiência visual) ouve sobre ele. Boa prática: dizer o que o
    visual mostra e a conclusão principal (ex: "Vendas por país; Estados
    Unidos e Canadá lideram"). Texto vazio remove.

    Escreve direto no disco (PBIR) -- mesma regra de add_visual: no Desktop, clique em
    "Apply external changes" ("Aplicar alterações externas") (ou feche sem salvar e reabra); NÃO chame save_desktop logo depois.

    Args:
        pbip_path: Caminho para a pasta ou arquivo .pbip do projeto.
        page_name: Página do visual.
        visual_name: Visual (ver list_visuals).
        text: Texto alternativo ("" remove).

    Returns:
        Dict com o texto gravado.
    """
    from visuals import formatting

    return formatting.set_visual_alt_text(
        pbip_path=pbip_path, page_name=page_name, visual_name=visual_name, text=text
    )


@mcp.tool()
@_domain_tool
def set_visual_tooltip_page(
    pbip_path: str, page_name: str, visual_name: str, tooltip_page: str | None = None
) -> dict[str, Any]:
    """Liga um visual a uma página de tooltip (criada com
    create_report_page(tooltip=True)): ao passar o mouse, aparece essa
    mini-página filtrada pelo ponto, em vez da dica padrão. Sem
    `tooltip_page`, volta pra dica padrão.

    Escreve direto no disco (PBIR) -- mesma regra de add_visual: no Desktop, clique em
    "Apply external changes" ("Aplicar alterações externas") (ou feche sem salvar e reabra); NÃO chame save_desktop logo depois.

    Args:
        pbip_path: Caminho para a pasta ou arquivo .pbip do projeto.
        page_name: Página do visual.
        visual_name: Visual (ver list_visuals).
        tooltip_page: Nome interno da página de tooltip; omita pra desligar.

    Returns:
        Dict com a página de tooltip ligada.
    """
    from visuals import formatting

    return formatting.set_visual_tooltip_page(
        pbip_path=pbip_path, page_name=page_name, visual_name=visual_name, tooltip_page=tooltip_page
    )


@mcp.tool()
@_domain_tool
def set_mobile_layout(
    pbip_path: str,
    page_name: str,
    visuals: list[str] | None = None,
    replace: bool = False,
) -> dict[str, Any]:
    """Monta o LAYOUT DE CELULAR de uma página (o que aparece no app do
    Power BI no celular): empilha os visuais numa tela de 324px -- título
    em cima, cartões em dupla, gráficos na largura toda. Não mexe no
    layout da área de trabalho.

    Recusa se a página já tem layout de celular (montado pela UI ou numa
    chamada anterior), pra não apagar trabalho -- passe replace=True só
    depois de confirmar com o usuário.

    Escreve direto no disco (PBIR) -- mesma regra de add_visual: no Desktop, clique em
    "Apply external changes" ("Aplicar alterações externas") (ou feche sem salvar e reabra); NÃO chame save_desktop logo depois. No
    Desktop: Exibição -> Layout móvel.

    Args:
        pbip_path: Caminho para a pasta ou arquivo .pbip do projeto.
        page_name: Página.
        visuals: Visuais a colocar, nessa ordem (ver list_visuals). Omita
            pra usar todos, na ordem de leitura da área de trabalho.
        replace: Substituir um layout de celular já existente (os visuais
            fora da lista saem do celular).

    Returns:
        Dict com a posição de cada visual no celular e os removidos.
    """
    from visuals import mobile_layout

    return mobile_layout.set_mobile_layout(
        pbip_path=pbip_path, page_name=page_name, visuals=visuals, replace=replace
    )


@mcp.tool()
@_domain_tool
def import_custom_visual(
    pbip_path: str, pbiviz_path: str, replace: bool = False, visual_guid: str | None = None
) -> dict[str, Any]:
    """Importa um VISUAL PERSONALIZADO (arquivo .pbiviz -- ex: baixado do
    AppSource pelo usuário -- ou um .pbix que já use o visual, como o
    relatório de exemplo do AppSource) no relatório. Depois disso, o visual pode ser
    usado em add_visual / blueprint com `visual_type` = o `visual_type`
    devolvido aqui (o GUID do visual) e os `roles` do próprio visual.

    Este servidor nunca baixa visual nenhum -- o arquivo vem do usuário.
    O GUID é lido do próprio pacote (nunca adivinhado pelo nome).

    Escreve direto no disco (PBIR) -- mesma regra de add_visual: no Desktop, clique em
    "Apply external changes" ("Aplicar alterações externas") (ou feche sem salvar e reabra); NÃO chame save_desktop logo depois.

    Args:
        pbip_path: Caminho para a pasta ou arquivo .pbip do projeto.
        pbiviz_path: Caminho do arquivo .pbiviz (ou .pbix com o visual).
        replace: Substituir um visual já importado (atualizar versão).
        visual_guid: Só pra .pbix com vários visuais personalizados:
            qual importar (a mensagem de erro lista os disponíveis).

    Returns:
        Dict com visual_type (GUID), display_name, version e roles (nome,
        o que aceita -- coluna/medida --, mínimo e máximo de campos).
    """
    from visuals import custom_visuals

    return custom_visuals.import_custom_visual(
        pbip_path=pbip_path, pbiviz_path=pbiviz_path, replace=replace, visual_guid=visual_guid
    )


@mcp.tool()
@_domain_tool
def list_custom_visuals(pbip_path: str) -> list[dict[str, Any]]:
    """Lista os visuais personalizados importados no relatório, com os
    roles de cada um (pra usar em add_visual / blueprint).

    Args:
        pbip_path: Caminho para a pasta ou arquivo .pbip do projeto.

    Returns:
        Lista de dicts com visual_type, display_name, version e roles.
    """
    from visuals import custom_visuals

    return custom_visuals.list_custom_visuals(pbip_path=pbip_path)


@mcp.tool()
@_domain_tool
def remove_custom_visual(pbip_path: str, visual_type: str) -> dict[str, Any]:
    """Remove um visual personalizado importado (pasta + registro).
    Recusa se algum visual do relatório ainda usa ele -- remova esses
    visuais antes (confirme com o usuário).

    Escreve direto no disco (PBIR) -- no Desktop, clique em "Apply external changes" ("Aplicar alterações externas") (ou feche sem salvar e reabra).

    Args:
        pbip_path: Caminho para a pasta ou arquivo .pbip do projeto.
        visual_type: O GUID do visual (ver list_custom_visuals).

    Returns:
        Dict confirmando a remoção.
    """
    from visuals import custom_visuals

    return custom_visuals.remove_custom_visual(pbip_path=pbip_path, visual_type=visual_type)


@mcp.tool()
@_domain_tool
def set_page_perspective(pbip_path: str, page_name: str, perspective: str | None = None) -> dict[str, Any]:
    """Escolhe a PERSPECTIVA que o leitor do relatório vê no
    "Personalizar visuais" desta página (o mesmo que Formatar página ->
    Personalizar visual -> Perspectiva do leitor de relatório). Sem
    `perspective`, volta pra "Campos padrão" (o modelo inteiro). A
    perspectiva precisa existir no modelo (create_perspective + salvar).

    Não liga o "Personalizar visuais" do relatório (vale pro relatório
    inteiro) -- se estiver desligado, a resposta avisa como ligar.

    Escreve direto no disco (PBIR) -- mesma regra de add_visual: no Desktop, clique em
    "Apply external changes" ("Aplicar alterações externas") (ou feche sem salvar e reabra); NÃO chame save_desktop logo depois.

    Args:
        pbip_path: Caminho para a pasta ou arquivo .pbip do projeto.
        page_name: Página.
        perspective: Nome da perspectiva; omita pra voltar ao padrão.

    Returns:
        Dict com a perspectiva gravada e se o "Personalizar visuais" está
        ligado no relatório.
    """
    from visuals import page_writer

    return page_writer.set_page_perspective(pbip_path=pbip_path, page_name=page_name, perspective=perspective)


@mcp.tool()
@_domain_tool
def set_page_background(
    pbip_path: str,
    page_name: str,
    color: str | None = None,
    transparency: float | None = None,
    wallpaper_color: str | None = None,
    wallpaper_transparency: float | None = None,
) -> dict[str, Any]:
    """Cor de fundo da PÁGINA: a tela atrás dos visuais (ex: cinza-claro
    "#F3F2F1" pra os cartões brancos se destacarem) e, opcionalmente, o
    papel de parede (área fora da página). Passar só a cor já deixa o
    fundo opaco (transparência 0). Pra fundo de UM visual, use
    set_visual_container_style.

    Escreve direto no disco (PBIR) -- mesma regra de add_visual: no Desktop, clique em
    "Apply external changes" ("Aplicar alterações externas") (ou feche sem salvar e reabra); NÃO chame save_desktop logo depois.

    Args:
        pbip_path: Caminho para a pasta ou arquivo .pbip do projeto.
        page_name: Página (ver list_visuals / nome da pasta da página).
        color: Cor da tela em hexadecimal (ex: "#F3F2F1").
        transparency: Transparência da tela, 0 (opaco) a 100.
        wallpaper_color: Cor do papel de parede em hexadecimal.
        wallpaper_transparency: Transparência do papel de parede, 0 a 100.

    Returns:
        Dict com o que mudou.
    """
    from visuals import formatting

    return formatting.set_page_background(
        pbip_path=pbip_path, page_name=page_name, color=color, transparency=transparency,
        wallpaper_color=wallpaper_color, wallpaper_transparency=wallpaper_transparency,
    )


@mcp.tool()
@_domain_tool
def add_image(
    pbip_path: str,
    page_name: str,
    image_path: str,
    x: float,
    y: float,
    width: float,
    height: float,
    fit: Literal["fit", "stretch", "fill"] | None = None,
) -> dict[str, Any]:
    """Adiciona um visual IMAGEM a partir de um arquivo do usuário -- ícone
    (PNG/SVG), logo, foto. Ex: ícones em cima de cartões desenhados, logo
    no canto do título. A imagem é copiada pro projeto (a mesma imagem é
    reaproveitada se já estiver lá) e o visual vai por cima dos outros.

    Escreve direto no disco (PBIR) -- mesma regra de add_visual: no Desktop, clique em
    "Apply external changes" ("Aplicar alterações externas") (ou feche sem salvar e reabra); NÃO chame save_desktop logo depois.

    Args:
        pbip_path: Caminho para a pasta ou arquivo .pbip do projeto.
        page_name: Página.
        image_path: Caminho da imagem (.png, .jpg, .jpeg, .gif, .bmp, .svg).
        x: Posição horizontal (esquerda) em pixels.
        y: Posição vertical (topo) em pixels.
        width: Largura em pixels.
        height: Altura em pixels.
        fit: "fit" (ajustar, sem cortar), "stretch" (esticar) ou "fill"
            (preencher, pode cortar). Omitido = padrão do Desktop.

    Returns:
        Dict com o nome do visual, o arquivo no projeto e se foi reaproveitado.
    """
    from visuals import formatting

    return formatting.add_image(
        pbip_path=pbip_path, page_name=page_name, image_path=image_path,
        x=x, y=y, width=width, height=height, fit=fit,
    )


@mcp.tool()
@_domain_tool
def set_page_background_image(
    pbip_path: str,
    page_name: str,
    image_path: str | None = None,
    scaling: str = "Fit",
    transparency: float = 0,
    wallpaper: bool = False,
) -> dict[str, Any]:
    """Coloca uma IMAGEM de fundo na página -- ex: um fundo desenhado no
    PowerPoint/Figma/Canva (faixa de título, espaços dos cartões, logo),
    exportado em PNG do tamanho da página (1280x720). A imagem vem do
    usuário (caminho de um arquivo dele); é copiada pro projeto e, se já
    estiver no projeto, reaproveitada (pode usar a mesma em várias
    páginas). Sem `image_path`, tira a imagem (a cor de fundo fica).

    Dica: por cima de um fundo desenhado, deixe os visuais sem fundo ou
    com fundo transparente (set_visual_container_style).

    Escreve direto no disco (PBIR) -- mesma regra de add_visual: no Desktop, clique em
    "Apply external changes" ("Aplicar alterações externas") (ou feche sem salvar e reabra); NÃO chame save_desktop logo depois.

    Args:
        pbip_path: Caminho para a pasta ou arquivo .pbip do projeto.
        page_name: Página.
        image_path: Caminho da imagem (.png, .jpg, .jpeg, .gif, .bmp,
            .svg); omita pra tirar a imagem.
        scaling: "Fit" (ajustar, sem cortar), "Fill" (preencher, pode
            cortar) ou "Stretch" (esticar).
        transparency: Transparência da imagem, 0 (opaca) a 100.
        wallpaper: True = papel de parede (área fora da página) em vez
            da tela.

    Returns:
        Dict com o nome do arquivo no projeto e se foi reaproveitado.
    """
    from visuals import formatting

    return formatting.set_page_background_image(
        pbip_path=pbip_path, page_name=page_name, image_path=image_path,
        scaling=scaling, transparency=transparency, wallpaper=wallpaper,
    )


@mcp.tool()
@_domain_tool
def set_card_style(
    pbip_path: str,
    page_name: str,
    visual_name: str,
    value_font_size: float | None = None,
    value_color: str | None = None,
    value_bold: bool | None = None,
    value_font_family: str | None = None,
    value_display_units: str | None = None,
    value_precision: int | None = None,
    label_show: bool | None = None,
    label_font_size: float | None = None,
    label_color: str | None = None,
    label_bold: bool | None = None,
    label_text: str | None = None,
    card_background_show: bool | None = None,
    card_background_color: str | None = None,
    card_background_transparency: float | None = None,
    outline_show: bool | None = None,
    image_path: str | None = None,
    image_show: bool | None = None,
) -> dict[str, Any]:
    """Formata um CARTÃO (KPI): o número grande (valor) e o texto de baixo
    (nome da medida). Funciona no cartão atual (`cardVisual`) e no legado
    (`card`) -- cada um é gravado com os nomes certos. Só o que for
    passado muda. Pra fundo/borda do cartão, use set_visual_container_style.

    Escreve direto no disco (PBIR) -- mesma regra de add_visual: no Desktop, clique em
    "Apply external changes" ("Aplicar alterações externas") (ou feche sem salvar e reabra); NÃO chame save_desktop logo depois.

    Args:
        pbip_path: Caminho para a pasta ou arquivo .pbip do projeto.
        page_name: Página do cartão.
        visual_name: Cartão (ver list_visuals).
        value_font_size: Tamanho do valor em pt (8 a 60; KPI costuma ficar entre 20 e 32).
        value_color: Cor do valor em hexadecimal (ex: "#1F3864").
        value_bold: Valor em negrito.
        value_font_family: Fonte do valor (ex: "Segoe UI Semibold").
        value_display_units: "auto", "none", "thousands", "millions", "billions" ou "trillions".
        value_precision: Casas decimais do valor.
        label_show: Mostra/esconde o texto de baixo.
        label_font_size: Tamanho do texto de baixo em pt (8 a 60).
        label_color: Cor do texto de baixo em hexadecimal.
        label_bold: Texto de baixo em negrito.
        label_text: Troca o texto de baixo (ex: "Vendas totais") -- só no cardVisual.
        card_background_show: Mostra/esconde o preenchimento INTERNO do
            cartão (a caixa branca atrás do número) -- só no cardVisual.
            Pra cartão sobre um fundo desenhado, use False junto com
            set_visual_container_style(background_show=False).
        card_background_color: Cor do preenchimento interno (hexadecimal).
        card_background_transparency: Transparência do preenchimento interno (0 a 100).
        outline_show: Mostra/esconde a borda interna do cartão -- só no cardVisual.
        image_path: Imagem/ícone DENTRO do cartão (arquivo .png/.svg/...) --
            só no cardVisual; copiada pro projeto (reaproveitada se já estiver).
        image_show: Mostra/esconde a imagem do cartão.

    Returns:
        Dict com o tipo do cartão e o que mudou.
    """
    from visuals import formatting

    return formatting.set_card_style(
        pbip_path=pbip_path, page_name=page_name, visual_name=visual_name,
        value_font_size=value_font_size, value_color=value_color, value_bold=value_bold,
        value_font_family=value_font_family, value_display_units=value_display_units,
        value_precision=value_precision, label_show=label_show, label_font_size=label_font_size,
        label_color=label_color, label_bold=label_bold, label_text=label_text,
        card_background_show=card_background_show, card_background_color=card_background_color,
        card_background_transparency=card_background_transparency, outline_show=outline_show,
        image_path=image_path, image_show=image_show,
    )


@mcp.tool()
@_domain_tool
def set_visual_data_labels(
    pbip_path: str,
    page_name: str,
    visual_name: str,
    show: bool | None = None,
    position: str | None = None,
    display_units: Literal["auto", "none", "thousands", "millions", "billions", "trillions"] | None = None,
    precision: int | None = None,
    font_size: float | None = None,
    color: str | None = None,
    style: Literal[
        "Category", "Data", "Percent of total", "Both", "Category, percent of total",
        "Data value, percent of total", "Category, data value, percent of total",
    ] | None = None,
    show_center_value: bool | None = None,
) -> dict[str, Any]:
    """Rótulos de dado de um visual (o número em cima de cada barra,
    fatia ou ponto). Só os parâmetros passados mudam; formatação por
    série já existente é preservada.

    O que vale depende do tipo de visual (schema oficial de tema): ex. o
    cartão não tem `show` (o valor sempre aparece), tabela/matriz/slicer
    não têm rótulos. Se não valer, a tool recusa dizendo o que existe.

    Escreve direto no disco (PBIR): se o Desktop estiver aberto com o
    projeto, clique em "Apply external changes" ("Aplicar alterações externas") no Desktop (ou feche sem salvar e reabra) pra ver; NÃO chame save_desktop
    logo depois.

    Args:
        pbip_path: Caminho para a pasta ou arquivo .pbip do projeto.
        page_name: Página do visual.
        visual_name: Visual (ver list_visuals).
        show: Liga/desliga os rótulos.
        position: Posição -- em gráfico de colunas/barras: "Auto",
            "InsideEnd", "OutsideEnd", "InsideCenter", "InsideBase";
            em linha: "Above", "Under" (a lista exata por tipo é validada).
        display_units: Unidade de exibição (ex: "millions").
        precision: Casas decimais.
        font_size: Tamanho da fonte (8 a 60).
        color: Cor em hexadecimal (ex: "#333333").
        style: Só rosca/pizza -- o que o rótulo mostra ("Percent of total" =
            porcentagem, "Category" = nome da fatia, "Data" = valor...).
        show_center_value: Só rosca -- mostra/esconde o número grande no meio.

    Returns:
        Dict com o tipo do visual, o objeto e o que mudou.
    """
    from visuals import formatting

    return formatting.set_visual_data_labels(
        pbip_path=pbip_path, page_name=page_name, visual_name=visual_name, show=show,
        position=position, display_units=display_units, precision=precision,
        font_size=font_size, color=color, style=style, show_center_value=show_center_value,
    )


@mcp.tool()
@_domain_tool
def set_visual_legend(
    pbip_path: str,
    page_name: str,
    visual_name: str,
    show: bool | None = None,
    position: Literal[
        "Top", "TopCenter", "TopRight", "Left", "Right", "LeftCenter",
        "RightCenter", "Bottom", "BottomCenter", "BottomRight",
    ] | None = None,
    show_title: bool | None = None,
    title: str | None = None,
    font_size: float | None = None,
) -> dict[str, Any]:
    """Legenda de um visual: mostrar/esconder, posição, título, fonte.
    Só os parâmetros passados mudam. Não existe em cartão, tabela,
    matriz, slicer, KPI (schema oficial de tema) -- a tool recusa.

    Escreve direto no disco (PBIR) -- mesma regra de add_visual: no Desktop, clique em
    "Apply external changes" ("Aplicar alterações externas") (ou feche sem salvar e reabra); NÃO chame save_desktop logo depois.

    Args:
        pbip_path: Caminho para a pasta ou arquivo .pbip do projeto.
        page_name: Página do visual.
        visual_name: Visual (ver list_visuals).
        show: Mostra/esconde a legenda.
        position: Posição ("Top" = em cima à esquerda, "TopCenter",
            "Right", "BottomCenter", ...).
        show_title: Mostra/esconde o título da legenda.
        title: Texto do título da legenda.
        font_size: Tamanho da fonte (8 a 60).

    Returns:
        Dict com o tipo do visual, o objeto e o que mudou.
    """
    from visuals import formatting

    return formatting.set_visual_legend(
        pbip_path=pbip_path, page_name=page_name, visual_name=visual_name, show=show,
        position=position, show_title=show_title, title=title, font_size=font_size,
    )


@mcp.tool()
@_domain_tool
def set_visual_tooltip_style(
    pbip_path: str,
    page_name: str,
    visual_name: str,
    label_color: str | None = None,
    value_color: str | None = None,
    background_color: str | None = None,
) -> dict[str, Any]:
    """Cores da dica de ferramenta de um visual (a caixa que aparece ao
    passar o mouse): texto dos rótulos, texto dos valores e fundo -- ex:
    caixa escura com valor laranja num dashboard escuro. Pra acrescentar
    campos na dica (ex: ano anterior), use o role "Tooltips" em add_visual.

    Escreve direto no disco (PBIR) -- mesma regra de add_visual: no Desktop, clique em
    "Apply external changes" ("Aplicar alterações externas") (ou feche sem salvar e reabra); NÃO chame save_desktop logo depois.

    Args:
        pbip_path: Caminho para a pasta ou arquivo .pbip do projeto.
        page_name: Página do visual.
        visual_name: Visual (ver list_visuals).
        label_color: Cor do texto dos rótulos (hex).
        value_color: Cor do texto dos valores (hex).
        background_color: Cor de fundo da caixa (hex).

    Returns:
        Dict com o visual e as cores aplicadas.
    """
    from visuals import formatting

    return formatting.set_visual_tooltip_style(
        pbip_path=pbip_path, page_name=page_name, visual_name=visual_name,
        label_color=label_color, value_color=value_color, background_color=background_color,
    )


@mcp.tool()
@_domain_tool
def set_table_data_bars(
    pbip_path: str,
    page_name: str,
    visual_name: str,
    field: str,
    color: str | None = None,
    negative_color: str = "#D64554",
    axis_color: str = "#999999",
    show_bar_only: bool = False,
    include_totals: bool = False,
    remove: bool = False,
) -> dict[str, Any]:
    """Barra de dados numa coluna numérica de tabela/matriz (a barrinha
    horizontal dentro de cada célula, proporcional ao valor). Chamar de
    novo na mesma coluna substitui; `remove=True` tira.

    Escreve direto no disco (PBIR) -- mesma regra de add_visual: no Desktop, clique em
    "Apply external changes" ("Aplicar alterações externas") (ou feche sem salvar e reabra); NÃO chame save_desktop logo depois.

    Args:
        pbip_path: Caminho para a pasta ou arquivo .pbip do projeto.
        page_name: Página do visual.
        visual_name: Tabela ou matriz (ver list_visuals).
        field: Coluna da tabela, como está em `fields` (ex: "financials.Total Sales").
        color: Cor da barra (hex, ex: "#6B6F80"). Obrigatória, exceto com remove=True.
        negative_color: Cor da barra de valor negativo.
        axis_color: Cor do eixo (linha do zero).
        show_bar_only: True esconde o número e mostra só a barra.
        include_totals: True desenha a barra também na linha de total.
        remove: True remove a barra dessa coluna.

    Returns:
        Dict com o visual, a coluna e o que foi aplicado.
    """
    from visuals import formatting

    return formatting.set_table_data_bars(
        pbip_path=pbip_path, page_name=page_name, visual_name=visual_name, field=field, color=color,
        negative_color=negative_color, axis_color=axis_color, show_bar_only=show_bar_only,
        include_totals=include_totals, remove=remove,
    )


@mcp.tool()
@_domain_tool
def set_decomposition_tree_style(
    pbip_path: str,
    page_name: str,
    visual_name: str,
    bar_color: str | None = None,
    bar_background_color: str | None = None,
    label_color: str | None = None,
    value_color: str | None = None,
    value_display_units: Literal["auto", "none", "thousands", "millions", "billions", "trillions"] | None = None,
    value_precision: int | None = None,
    header_background: str | None = None,
    header_title_color: str | None = None,
    header_subtitle_color: str | None = None,
    connector_color: str | None = None,
    bars_per_level: int | None = None,
    density: Literal["dense", "default", "sparse"] | None = None,
    accent_color: str | None = None,
    label_font_size: float | None = None,
    value_font_size: float | None = None,
) -> dict[str, Any]:
    """Cores e layout de uma árvore de decomposição -- ex: árvore escura num
    dashboard escuro: barras, nomes e valores, faixa de cabeçalho dos
    níveis, linhas que ligam os níveis, quantas barras aparecem por nível
    antes de rolar e o espaçamento. Só os parâmetros passados mudam.

    Escreve direto no disco (PBIR) -- mesma regra de add_visual: no Desktop, clique em
    "Apply external changes" ("Aplicar alterações externas") (ou feche sem salvar e reabra); NÃO chame save_desktop logo depois.

    Args:
        pbip_path: Caminho para a pasta ou arquivo .pbip do projeto.
        page_name: Página do visual.
        visual_name: Árvore de decomposição.
        bar_color: Cor da parte preenchida da barra (hex).
        bar_background_color: Cor do fundo da barra (hex).
        label_color: Cor do nome de cada item (hex).
        value_color: Cor do valor de cada item (hex).
        value_display_units: Unidade dos valores (ex: "millions").
        value_precision: Casas decimais dos valores.
        header_background: Fundo da faixa de cabeçalho dos níveis (hex).
        header_title_color: Cor do nome do nível no cabeçalho (hex).
        header_subtitle_color: Cor do item escolhido, embaixo do nome do nível (hex).
        connector_color: Cor das linhas que ligam os níveis (hex).
        bars_per_level: Máximo de barras por nível antes de rolar.
        density: "dense" (compacta), "default" ou "sparse" (espaçada).
        accent_color: Cor do caminho aberto (linhas entre os itens escolhidos), hex.
        label_font_size: Tamanho do nome de cada item (8 a 60) -- menor = cabem mais itens.
        value_font_size: Tamanho do valor de cada item (8 a 60).

    Returns:
        Dict com o que mudou em cada parte da árvore.
    """
    from visuals import formatting

    return formatting.set_decomposition_tree_style(
        pbip_path=pbip_path, page_name=page_name, visual_name=visual_name, bar_color=bar_color,
        bar_background_color=bar_background_color, label_color=label_color, value_color=value_color,
        value_display_units=value_display_units, value_precision=value_precision,
        header_background=header_background, header_title_color=header_title_color,
        header_subtitle_color=header_subtitle_color, connector_color=connector_color,
        bars_per_level=bars_per_level, density=density, accent_color=accent_color,
        label_font_size=label_font_size, value_font_size=value_font_size,
    )


@mcp.tool()
@_domain_tool
def expand_decomposition_tree(
    pbip_path: str,
    page_name: str,
    visual_name: str,
    path: list[str | int | float | bool],
) -> dict[str, Any]:
    """Abre os níveis de uma árvore de decomposição pra ela já aparecer
    aberta: o 1º campo de "Explicar por" sempre abre, e cada valor em
    `path` abre aquele item pro próximo nível. Ex: com Explicar por =
    Segmento, País, Produto, `path=["Channel Partners"]` mostra todos os
    segmentos e, dentro de Channel Partners, os países. `path=[]` abre só
    o 1º nível.

    Escreve direto no disco (PBIR) -- mesma regra de add_visual: no Desktop, clique em
    "Apply external changes" ("Aplicar alterações externas") (ou feche sem salvar e reabra); NÃO chame save_desktop logo depois.

    Args:
        pbip_path: Caminho para a pasta ou arquivo .pbip do projeto.
        page_name: Página do visual.
        visual_name: Árvore de decomposição (visual_type "decompositionTreeVisual").
        path: Itens a abrir, um por nível, na ordem de "Explicar por".

    Returns:
        Dict com os níveis abertos e o caminho.
    """
    from visuals import visual_writer

    return visual_writer.expand_decomposition_tree(
        pbip_path=pbip_path, page_name=page_name, visual_name=visual_name, path=path,
    )


@mcp.tool()
@_domain_tool
def set_visual_field_name(
    pbip_path: str,
    page_name: str,
    visual_name: str,
    field: str,
    display_name: str,
) -> dict[str, Any]:
    """Renomeia um campo SÓ neste visual -- cabeçalho de coluna da tabela,
    item da legenda, título do eixo (ex: "Total Units Sold" -> "Unidades").
    O nome no modelo não muda. `display_name=""` volta ao nome do modelo.
    É o "Renomear para este visual" do Desktop.

    Escreve direto no disco (PBIR) -- mesma regra de add_visual: no Desktop, clique em
    "Apply external changes" ("Aplicar alterações externas") (ou feche sem salvar e reabra); NÃO chame save_desktop logo depois.

    Args:
        pbip_path: Caminho para a pasta ou arquivo .pbip do projeto.
        page_name: Página do visual.
        visual_name: Visual (ver list_visuals).
        field: Campo como está em `fields` (ex: "financials.Total Units Sold").
        display_name: Nome a mostrar neste visual; "" volta ao nome do modelo.

    Returns:
        Dict com o visual, o campo e o nome aplicado.
    """
    from visuals import visual_writer

    return visual_writer.set_visual_field_name(
        pbip_path=pbip_path, page_name=page_name, visual_name=visual_name, field=field, display_name=display_name,
    )


@mcp.tool()
@_domain_tool
def set_visual_default_color(
    pbip_path: str,
    page_name: str,
    visual_name: str,
    color: str,
) -> dict[str, Any]:
    """Cor de um gráfico de UMA série (uma medida, sem legenda), ex: todas
    as barras em laranja. Pra gráfico com várias séries, use set_visual_color
    por série -- em série única aquela cor por série é ignorada pelo Power BI.

    Escreve direto no disco (PBIR) -- mesma regra de add_visual: no Desktop, clique em
    "Apply external changes" ("Aplicar alterações externas") (ou feche sem salvar e reabra); NÃO chame save_desktop logo depois.

    Args:
        pbip_path: Caminho para a pasta ou arquivo .pbip do projeto.
        page_name: Página do visual.
        visual_name: Gráfico (ver list_visuals).
        color: Cor em hexadecimal (ex: "#E8825C").

    Returns:
        Dict com o visual e a cor aplicada.
    """
    from visuals import formatting

    return formatting.set_visual_default_color(
        pbip_path=pbip_path, page_name=page_name, visual_name=visual_name, color=color,
    )


@mcp.tool()
@_domain_tool
def set_slicer_style(
    pbip_path: str,
    page_name: str,
    visual_name: str,
    header_show: bool | None = None,
    header_font_color: str | None = None,
    header_text_size: float | None = None,
    items_font_color: str | None = None,
    items_background: str | None = None,
    items_text_size: float | None = None,
) -> dict[str, Any]:
    """Visual de um slicer clássico (lista ou suspenso): cabeçalho
    (mostrar, cor, tamanho) e itens (cor do texto, fundo, tamanho) -- ex:
    slicer escuro com texto claro num dashboard escuro. Só os parâmetros
    passados mudam. Pro slicer de botões use set_button_slicer_style.

    Escreve direto no disco (PBIR) -- mesma regra de add_visual: no Desktop, clique em
    "Apply external changes" ("Aplicar alterações externas") (ou feche sem salvar e reabra); NÃO chame save_desktop logo depois.

    Args:
        pbip_path: Caminho para a pasta ou arquivo .pbip do projeto.
        page_name: Página do slicer.
        visual_name: Slicer clássico (visual_type "slicer").
        header_show: Mostra/esconde o cabeçalho (nome do campo em cima).
        header_font_color: Cor do texto do cabeçalho (hex).
        header_text_size: Tamanho do texto do cabeçalho (8 a 60).
        items_font_color: Cor do texto dos itens (hex).
        items_background: Cor de fundo dos itens (hex).
        items_text_size: Tamanho do texto dos itens (8 a 60).

    Returns:
        Dict com o que mudou no cabeçalho e nos itens.
    """
    from visuals import formatting

    return formatting.set_slicer_style(
        pbip_path=pbip_path, page_name=page_name, visual_name=visual_name, header_show=header_show,
        header_font_color=header_font_color, header_text_size=header_text_size,
        items_font_color=items_font_color, items_background=items_background, items_text_size=items_text_size,
    )


@mcp.tool()
@_domain_tool
def set_table_column_format(
    pbip_path: str,
    page_name: str,
    visual_name: str,
    field: str,
    display_units: Literal["none", "thousands", "millions", "billions", "trillions"] | None = None,
    precision: int | None = None,
) -> dict[str, Any]:
    """Formato do número de UMA coluna de tabela/matriz: unidade (mil,
    milhão...) e casas decimais -- ex: 24,887,654.88 vira 24.89M. Útil
    quando a tabela fica larga demais e aparece barra de rolagem.

    Escreve direto no disco (PBIR) -- mesma regra de add_visual: no Desktop, clique em
    "Apply external changes" ("Aplicar alterações externas") (ou feche sem salvar e reabra); NÃO chame save_desktop logo depois.

    Args:
        pbip_path: Caminho para a pasta ou arquivo .pbip do projeto.
        page_name: Página do visual.
        visual_name: Tabela ou matriz (ver list_visuals).
        field: Coluna da tabela, como está em `fields` (ex: "financials.Total Sales").
        display_units: "none", "thousands" (mil), "millions" (milhão), "billions", "trillions".
        precision: Casas decimais.

    Returns:
        Dict com o visual, a coluna e o que mudou.
    """
    from visuals import formatting

    return formatting.set_table_column_format(
        pbip_path=pbip_path, page_name=page_name, visual_name=visual_name, field=field,
        display_units=display_units, precision=precision,
    )


@mcp.tool()
@_domain_tool
def set_table_style(
    pbip_path: str,
    page_name: str,
    visual_name: str,
    header_font_color: str | None = None,
    header_background: str | None = None,
    header_bold: bool | None = None,
    row_font_color: str | None = None,
    row_background: str | None = None,
    alt_row_background: str | None = None,
    total_font_color: str | None = None,
    total_background: str | None = None,
    total_bold: bool | None = None,
    font_size: float | None = None,
) -> dict[str, Any]:
    """Cores e fonte de tabela/matriz: cabeçalho, linhas (com zebra
    opcional) e linha de total -- ex: tabela escura com texto claro num
    dashboard de fundo escuro. Só os parâmetros passados mudam. Desliga o
    "estilo pronto" da tabela (sem isso o Power BI ignora as cores).

    Escreve direto no disco (PBIR) -- mesma regra de add_visual: no Desktop, clique em
    "Apply external changes" ("Aplicar alterações externas") (ou feche sem salvar e reabra); NÃO chame save_desktop logo depois.

    Args:
        pbip_path: Caminho para a pasta ou arquivo .pbip do projeto.
        page_name: Página do visual.
        visual_name: Tabela ou matriz (ver list_visuals).
        header_font_color: Cor do texto do cabeçalho (hex).
        header_background: Cor de fundo do cabeçalho (hex).
        header_bold: Cabeçalho em negrito.
        row_font_color: Cor do texto das linhas (hex).
        row_background: Cor de fundo das linhas (hex).
        alt_row_background: Fundo das linhas pares (zebra); omitido = igual a row_background.
        total_font_color: Cor do texto da linha de total (hex).
        total_background: Cor de fundo da linha de total (hex).
        total_bold: Total em negrito.
        font_size: Tamanho da fonte (8 a 60) de cabeçalho, linhas e total.

    Returns:
        Dict com o visual e as regiões (cabeçalho/linhas/total) alteradas.
    """
    from visuals import formatting

    return formatting.set_table_style(
        pbip_path=pbip_path, page_name=page_name, visual_name=visual_name,
        header_font_color=header_font_color, header_background=header_background, header_bold=header_bold,
        row_font_color=row_font_color, row_background=row_background, alt_row_background=alt_row_background,
        total_font_color=total_font_color, total_background=total_background, total_bold=total_bold,
        font_size=font_size,
    )


@mcp.tool()
@_domain_tool
def set_line_style(
    pbip_path: str,
    page_name: str,
    visual_name: str,
    series: str | None = None,
    line_style: Literal["solid", "dashed", "dotted"] | None = None,
    width: float | None = None,
    show_marker: bool | None = None,
    interpolation: Literal["linear", "smooth", "step"] | None = None,
) -> dict[str, Any]:
    """Estilo das linhas de um gráfico de linha/área: tracejada ou
    pontilhada (ex: ano anterior tracejado), espessura, marcadores nos
    pontos e curva (reta, suave ou em degrau). Só os parâmetros passados mudam.

    Escreve direto no disco (PBIR) -- mesma regra de add_visual: no Desktop, clique em
    "Apply external changes" ("Aplicar alterações externas") (ou feche sem salvar e reabra); NÃO chame save_desktop logo depois.

    Args:
        pbip_path: Caminho para a pasta ou arquivo .pbip do projeto.
        page_name: Página do visual.
        visual_name: Gráfico de linha/área (ver list_visuals).
        series: Medida do eixo Y cuja linha muda (ex: "financials.Total Sales PY");
            omitido = todas as linhas.
        line_style: "solid" (contínua), "dashed" (tracejada), "dotted" (pontilhada).
        width: Espessura da linha em pixels.
        show_marker: Mostra/esconde o marcador em cada ponto.
        interpolation: "linear", "smooth" (suave) ou "step" (degrau).

    Returns:
        Dict com o visual, a série e o que mudou.
    """
    from visuals import formatting

    return formatting.set_line_style(
        pbip_path=pbip_path, page_name=page_name, visual_name=visual_name, series=series,
        line_style=line_style, width=width, show_marker=show_marker, interpolation=interpolation,
    )


@mcp.tool()
@_domain_tool
def set_visual_axis(
    pbip_path: str,
    page_name: str,
    visual_name: str,
    axis: Literal["category", "value"],
    show: bool | None = None,
    show_title: bool | None = None,
    title: str | None = None,
    font_size: float | None = None,
    invert: bool | None = None,
    start: float | None = None,
    end: float | None = None,
    display_units: Literal["auto", "none", "thousands", "millions", "billions", "trillions"] | None = None,
    gridlines: bool | None = None,
    min_category_width: float | None = None,
    axis_type: Literal["categorical", "continuous"] | None = None,
) -> dict[str, Any]:
    """Eixo de um gráfico: `axis="category"` (o das categorias -- em
    colunas é o horizontal, em barras horizontais é o vertical) ou
    `axis="value"` (o dos números). Só os parâmetros passados mudam. Não
    existe em pizza/rosca, cartão, tabela, matriz (schema oficial).

    Escreve direto no disco (PBIR) -- mesma regra de add_visual: no Desktop, clique em
    "Apply external changes" ("Aplicar alterações externas") (ou feche sem salvar e reabra); NÃO chame save_desktop logo depois.

    Args:
        pbip_path: Caminho para a pasta ou arquivo .pbip do projeto.
        page_name: Página do visual.
        visual_name: Visual (ver list_visuals).
        axis: "category" ou "value".
        show: Mostra/esconde o eixo.
        show_title: Mostra/esconde o título do eixo.
        title: Texto do título do eixo.
        font_size: Tamanho da fonte dos rótulos do eixo (8 a 60).
        invert: Inverte a ordem/direção do eixo.
        start: Valor inicial (ex: 0 pra forçar começar no zero).
        end: Valor final.
        display_units: Unidade dos rótulos (ex: "millions").
        gridlines: Mostra/esconde as linhas de grade.
        min_category_width: Só eixo de categorias -- largura mínima de cada
            categoria em pixels; menor = cabem mais categorias sem barra de rolagem.
        axis_type: Só eixo de categorias -- "categorical" (um rótulo por
            categoria, ex: todos os anos) ou "continuous" (escala contínua,
            o padrão do Power BI pra número/data).

    Returns:
        Dict com o tipo do visual, o objeto e o que mudou.
    """
    from visuals import formatting

    return formatting.set_visual_axis(
        pbip_path=pbip_path, page_name=page_name, visual_name=visual_name, axis=axis,
        show=show, show_title=show_title, title=title, font_size=font_size, invert=invert,
        start=start, end=end, display_units=display_units, gridlines=gridlines,
        min_category_width=min_category_width, axis_type=axis_type,
    )


@mcp.tool()
@_domain_tool
def apply_report_theme(pbip_path: str, theme_name: str, data_colors: list[str]) -> dict[str, Any]:
    """Cria (ou substitui) o tema de cores customizado do relatório
    inteiro -- a paleta padrão que qualquer visual sem cor explícita
    própria usa.

    Diferente de set_visual_color (que muda uma série num visual
    específico), isto muda o relatório inteiro de uma vez. Exige que o
    relatório já tenha ao menos uma página (create_report_page).

    Args:
        pbip_path: Caminho para a pasta ou arquivo .pbip do projeto.
        theme_name: Nome do tema.
        data_colors: Lista de cores em hexadecimal com "#" (ex:
            ["#2E86AB", "#E6553A", "#F1A208"]), na ordem em que os
            visuais vão usá-las pra cada série/categoria nova.

    Returns:
        Dict com o tema aplicado.
    """
    from visuals import theme_writer

    return theme_writer.apply_report_theme(
        pbip_path=pbip_path, theme_name=theme_name, data_colors=data_colors
    )


@mcp.tool()
@_domain_tool
def remove_report_theme(pbip_path: str) -> dict[str, Any]:
    """Remove o tema customizado do relatório (volta ao tema padrão do
    Power BI).

    Args:
        pbip_path: Caminho para a pasta ou arquivo .pbip do projeto.

    Returns:
        Dict confirmando a remoção.
    """
    from visuals import theme_writer

    return theme_writer.remove_report_theme(pbip_path=pbip_path)


@mcp.tool()
@_domain_tool
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
    um visual, baseado no valor de um campo.

    Sem `mid_color`: gradiente de 2 pontos (mínimo -> máximo), bom pra
    magnitude simples (ex: vendas). Com `mid_color` (e `min_value`/
    `mid_value`/`max_value`, os três obrigatórios juntos): gradiente de
    3 pontos (ruim -> neutro -> bom), bom pra variação/desempenho vs
    meta.

    Args:
        pbip_path: Caminho para a pasta ou arquivo .pbip do projeto.
        page_name: Página onde o visual está.
        visual_name: Visual a formatar.
        query_ref: Campo cujo valor decide a cor (ex: "Vendas.Total Vendas").
        min_color: Cor no valor mínimo, em hexadecimal com "#".
        max_color: Cor no valor máximo, em hexadecimal com "#".
        mid_color: Cor no ponto médio (ativa o gradiente de 3 pontos).
        min_value: Valor do ponto mínimo (obrigatório com mid_color).
        mid_value: Valor do ponto médio (obrigatório com mid_color).
        max_value: Valor do ponto máximo (obrigatório com mid_color).
        null_strategy: Como tratar valor nulo ("noColor" ou "asZero").

    Returns:
        Dict confirmando o gradiente aplicado.
    """
    from visuals import visual_writer

    return visual_writer.set_visual_color_gradient(
        pbip_path=pbip_path, page_name=page_name, visual_name=visual_name, query_ref=query_ref,
        min_color=min_color, max_color=max_color, mid_color=mid_color,
        min_value=min_value, mid_value=mid_value, max_value=max_value, null_strategy=null_strategy,
    )


@mcp.tool()
@_domain_tool
def set_visual_conditional_color(
    pbip_path: str,
    page_name: str,
    visual_name: str,
    query_ref: str,
    rules: list[dict[str, Any]],
    default_color: str,
) -> dict[str, Any]:
    """Aplica cores discretas por regra a um visual (ex: verde se
    lucro >= 500, vermelho se < 0), avaliadas na ordem dada -- a
    primeira regra cuja condição bater define a cor.

    Args:
        pbip_path: Caminho para a pasta ou arquivo .pbip do projeto.
        page_name: Página onde o visual está.
        visual_name: Visual a formatar.
        query_ref: Campo cujo valor decide a cor (ex: "Vendas.Total Vendas").
        rules: Lista de dicts `{"operator": "<"|"<="|">"|">="|"==",
            "value": número, "color": "#hex"}`.
        default_color: Cor quando nenhuma regra bate, em hexadecimal com "#".

    Returns:
        Dict confirmando quantas regras foram escritas.
    """
    from visuals import visual_writer

    return visual_writer.set_visual_conditional_color(
        pbip_path=pbip_path, page_name=page_name, visual_name=visual_name,
        query_ref=query_ref, rules=rules, default_color=default_color,
    )


@mcp.tool()
@_domain_tool
def set_visual_field_parameter(
    pbip_path: str,
    page_name: str,
    visual_name: str,
    role: str,
    field_parameter_table: str,
    display_column: str,
    default_field: str,
) -> dict[str, Any]:
    """Vincula um role de um visual já existente a um field parameter
    (criado por create_field_parameter) -- o visual passa a reagir à
    seleção de um slicer ligado ao parâmetro (ex: trocar a medida
    mostrada num cartão), em vez de mostrar um campo fixo.

    CONFIRMADO AO VIVO: comparamos com um cartão vinculado a um field
    parameter manualmente pela UI do Desktop. `fieldParameters` (a
    marcação que faz o role reagir à seleção) fica dentro do objeto do
    próprio `role`, irmão de `projections` -- confirmado contra o schema
    oficial `visualContainer/2.7.0`.

    Args:
        pbip_path: Caminho para a pasta ou arquivo .pbip do projeto.
        page_name: Página onde o visual está.
        visual_name: Visual a vincular.
        role: Role do visual a controlar (ex: "Values" num cartão,
            "Y" num gráfico).
        field_parameter_table: Tabela de field parameter (de
            create_field_parameter, ou criada manualmente no Desktop).
        display_column: Coluna de exibição da tabela de parâmetro (o
            `display_column` que create_field_parameter devolveu).
        default_field: Campo a mostrar antes de qualquer seleção (ex:
            "financials.Total Sales") -- precisa ser um dos campos do
            parâmetro, mas isso não é validado aqui.

    Returns:
        Dict confirmando o vínculo.
    """
    from visuals import visual_writer

    return visual_writer.set_visual_field_parameter(
        pbip_path=pbip_path, page_name=page_name, visual_name=visual_name, role=role,
        field_parameter_table=field_parameter_table, display_column=display_column,
        default_field=default_field,
    )


@mcp.tool()
@_domain_tool
def set_page_layout(
    pbip_path: str,
    page_name: str,
    layout: Literal["grid", "kpi_row"],
    top: float | None = None,
    keep_fixed: list[str] | None = None,
) -> dict[str, Any]:
    """Reorganiza os visuais existentes numa página.

    Se a página já tem um título (textbox) no topo, passe o nome dele em
    `keep_fixed` e a altura da faixa do título em `top` -- senão o
    título é reposicionado junto com os outros visuais.

    Args:
        pbip_path: Caminho para a pasta ou arquivo .pbip do projeto.
        page_name: Página cujos visuais serão reposicionados.
        layout: "grid" distribui os visuais em uma grade uniforme;
            "kpi_row" põe cards numa faixa no topo e os demais visuais
            abaixo.
        top: y (em px) onde o layout começa; padrão = margem de 8px.
        keep_fixed: Nomes de visuais que ficam onde estão (ver list_visuals).

    Returns:
        Dict com as novas posições de cada visual.
    """
    from visuals import layout as layout_module

    return layout_module.set_page_layout(
        pbip_path=pbip_path, page_name=page_name, layout=layout, top=top, keep_fixed=keep_fixed
    )


# ---------------------------------------------------------------------------
# Camada de orquestração
# ---------------------------------------------------------------------------


@mcp.tool()
@_domain_tool
def plan_dashboard(description: str, pbip_path: str) -> dict[str, Any]:
    """Primeira etapa para montar um dashboard a partir de linguagem
    natural. Não escreve nada.

    Devolve o metadata completo do modelo, o JSON Schema do blueprint
    esperado por apply_dashboard_blueprint, o catálogo de tipos de visual
    disponíveis (com seus roles) e as regras de layout. Você (o modelo
    que chamou esta ferramenta) deve usar isso para decidir quais
    tabelas/medidas existentes usar, o que precisa ser criado, e montar
    o blueprint — depois chamar apply_dashboard_blueprint com ele.

    Args:
        description: Pedido em linguagem natural (ex: "dashboard de
            vendas por região").
        pbip_path: Caminho para a pasta ou arquivo .pbip do projeto.

    Returns:
        Dict com `model_metadata`, `blueprint_schema`, `visual_catalog` e
        `layout_options`.
    """
    from orchestrator import planner

    return planner.plan_dashboard(description=description, pbip_path=pbip_path)


@mcp.tool()
@_domain_tool
def apply_dashboard_blueprint(
    blueprint: dict[str, Any],
    pbip_path: str,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Segunda etapa: executa um blueprint montado a partir do resultado
    de plan_dashboard.

    Ordem de execução: valida o shape do blueprint -> executa as
    operações de modelagem que faltam (tabelas/medidas/relacionamentos
    novos) -> relê o metadata do modelo -> resolve cada referência de
    campo usada nos visuais -> escreve os arquivos PBIR (página(s) e
    visuais) de forma atômica.

    Args:
        blueprint: Estrutura conforme o schema devolvido por
            plan_dashboard.
        pbip_path: Caminho para a pasta ou arquivo .pbip do projeto.
        dry_run: Se True, valida e reporta o que seria feito sem
            executar nenhuma escrita real (nem no modelo, nem em disco).

    Returns:
        Dict com relatório do que foi criado/validado: tabelas, medidas,
        relacionamentos, páginas e visuais.
    """
    from orchestrator import applier

    return applier.apply_dashboard_blueprint(
        blueprint=blueprint, pbip_path=pbip_path, dry_run=dry_run
    )


if __name__ == "__main__":
    mcp.run(transport="stdio")
