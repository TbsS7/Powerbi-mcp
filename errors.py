"""Hierarquia de erros do powerbi-fullstack-mcp.

Todas as exceções que devem ser reportadas de volta ao cliente MCP como
uma falha de ferramenta (em vez de um traceback cru) herdam de
``PowerBiMcpError``. Cada uma carrega uma mensagem já pensada para ser
lida por um agente/LLM, não apenas por um humano depurando.
"""

from __future__ import annotations


class PowerBiMcpError(Exception):
    """Classe-base para todos os erros previstos deste servidor."""


# --- Camada de modelagem -----------------------------------------------


class TomDllNotFoundError(PowerBiMcpError):
    """Nenhuma das DLLs do AMO/TOM foi encontrada nos locais conhecidos."""

    def __init__(self, searched_paths: list[str]) -> None:
        self.searched_paths = searched_paths
        paths = "\n  - ".join(searched_paths) or "(nenhum)"
        super().__init__(
            "Não foi possível localizar as DLLs do Tabular Object Model "
            "(Microsoft.AnalysisServices.Core.dll, "
            "Microsoft.AnalysisServices.Tabular.dll, "
            "Microsoft.AnalysisServices.Tabular.Json.dll).\n"
            f"Locais verificados:\n  - {paths}\n"
            "Defina a variável de ambiente TOM_DLL_PATH apontando para o "
            "diretório que contém essas DLLs. Veja o README, seção "
            "'Licenciamento e obtenção do TOM', para instruções de "
            "instalação."
        )


class DesktopNotFoundError(PowerBiMcpError):
    """Nenhuma instância do Power BI Desktop foi encontrada em execução."""


class DesktopWindowNotFoundError(PowerBiMcpError):
    """Não foi possível identificar, sem ambiguidade, a janela do
    Power BI Desktop correspondente à conexão TOM ativa -- usado por
    save_desktop antes de mandar qualquer tecla, para nunca arriscar
    ativar a janela errada."""


class DesktopSaveFailedError(PowerBiMcpError):
    """A janela do Power BI Desktop foi identificada, mas ativá-la ou
    enviar o Ctrl+S falhou."""


class DatabaseNotFoundOnPortError(PowerBiMcpError):
    """A porta conectou, mas nenhum banco com o nome pedido foi
    encontrado nela (a instância do Desktop tem outro modelo aberto)."""

    def __init__(self, database_name: str, port: int, available: list[str]) -> None:
        self.database_name = database_name
        self.port = port
        self.available = available
        super().__init__(
            f"Banco '{database_name}' não encontrado na porta {port}. "
            f"Bancos disponíveis nessa porta: {', '.join(available) or '(nenhum)'}."
        )


class MultipleDesktopInstancesError(PowerBiMcpError):
    """Mais de uma instância do Power BI Desktop está aberta; é preciso
    escolher qual usar."""

    def __init__(self, instances: list[dict]) -> None:
        self.instances = instances
        listed = "; ".join(f"port={i['port']} ({i['workspace_name']})" for i in instances)
        super().__init__(
            f"Encontradas {len(instances)} instâncias do Power BI Desktop "
            f"abertas: {listed}. Chame connect_to_desktop novamente "
            "informando 'port' ou 'database_name' para escolher qual usar."
        )


class TableNotFoundError(PowerBiMcpError):
    """Tabela referenciada não existe no modelo."""

    def __init__(self, table_name: str, known_tables: list[str]) -> None:
        self.table_name = table_name
        self.known_tables = known_tables
        super().__init__(
            f"Tabela '{table_name}' não existe no modelo. "
            f"Tabelas conhecidas: {', '.join(known_tables) or '(nenhuma)'}."
        )


class ColumnAlreadyExistsError(PowerBiMcpError):
    """Já existe uma coluna com esse nome na tabela."""

    def __init__(self, table_name: str, column_name: str) -> None:
        self.table_name = table_name
        self.column_name = column_name
        super().__init__(
            f"Já existe uma coluna chamada '{column_name}' na tabela "
            f"'{table_name}'. Escolha outro nome."
        )


class ColumnNotFoundError(PowerBiMcpError):
    """Coluna referenciada não existe na tabela informada."""

    def __init__(self, table_name: str, column_name: str, known_columns: list[str]) -> None:
        self.table_name = table_name
        self.column_name = column_name
        self.known_columns = known_columns
        super().__init__(
            f"Coluna '{column_name}' não existe na tabela '{table_name}'. "
            f"Colunas conhecidas: {', '.join(known_columns) or '(nenhuma)'}."
        )


class TableAlreadyExistsError(PowerBiMcpError):
    """Já existe uma tabela com esse nome no modelo."""

    def __init__(self, table_name: str) -> None:
        self.table_name = table_name
        super().__init__(
            f"Já existe uma tabela chamada '{table_name}' no modelo. "
            "Escolha outro nome, ou use a tabela existente."
        )


class MeasureAlreadyExistsError(PowerBiMcpError):
    """Já existe uma medida com esse nome no modelo (nomes de medida são
    únicos em todo o modelo tabular, não só dentro da tabela)."""

    def __init__(self, measure_name: str) -> None:
        self.measure_name = measure_name
        super().__init__(
            f"Já existe uma medida chamada '{measure_name}' no modelo. "
            "Nomes de medida precisam ser únicos em todo o modelo."
        )


class MeasureNotFoundError(PowerBiMcpError):
    """Medida referenciada não existe no modelo."""

    def __init__(self, measure_name: str, known_measures: list[str]) -> None:
        self.measure_name = measure_name
        self.known_measures = known_measures
        super().__init__(
            f"Medida '{measure_name}' não existe no modelo. "
            f"Medidas conhecidas: {', '.join(known_measures) or '(nenhuma)'}."
        )


class RelationshipNotFoundError(PowerBiMcpError):
    """Relacionamento referenciado (pelo par tabela.coluna de cada
    lado) não existe no modelo."""

    def __init__(self, from_table: str, from_column: str, to_table: str, to_column: str) -> None:
        self.from_table = from_table
        self.from_column = from_column
        self.to_table = to_table
        self.to_column = to_column
        super().__init__(
            f"Não existe relacionamento entre '{from_table}.{from_column}' e "
            f"'{to_table}.{to_column}' no modelo."
        )


class TableHasRelationshipsError(PowerBiMcpError):
    """A tabela não pode ser removida porque ainda há relacionamento(s)
    apontando pra ela -- removê-la primeiro deixaria o modelo com uma
    referência quebrada. Remova o(s) relacionamento(s) primeiro."""

    def __init__(self, table_name: str, relationships: list[dict]) -> None:
        self.table_name = table_name
        self.relationships = relationships
        listed = "; ".join(
            f"{r['from_table']}.{r['from_column']} -> {r['to_table']}.{r['to_column']}"
            for r in relationships
        )
        super().__init__(
            f"Não é possível remover a tabela '{table_name}': ainda há "
            f"relacionamento(s) apontando pra ela ({listed}). Remova o(s) "
            "relacionamento(s) primeiro (delete_relationship)."
        )


class VisualNotFoundError(PowerBiMcpError):
    """Visual referenciado (por nome) não existe na página."""

    def __init__(self, visual_name: str, page_name: str) -> None:
        self.visual_name = visual_name
        self.page_name = page_name
        super().__init__(
            f"Visual '{visual_name}' não existe na página '{page_name}'."
        )


class MobileLayoutExistsError(PowerBiMcpError):
    """A página já tem layout de celular (mobile.json) -- montado pela UI
    ou numa chamada anterior; só é sobrescrito com `replace=True`."""


class InvalidLayoutError(PowerBiMcpError):
    """Parâmetro de set_page_layout fora do possível (ex: `top` fora da
    altura da página)."""


class InvalidResourceNameError(PowerBiMcpError):
    """Um nome usado como componente de caminho de arquivo dentro do
    PBIR (visual_name, bookmark_name, theme_name, ...) não é seguro --
    mesma razão de InvalidPageNameError: um valor com "..", "/", "\\"
    ou dois-pontos poderia escapar da pasta pretendida (path
    traversal), e o PBIR só aceita letras/dígitos/underscore/hífen em
    nome de objeto de qualquer forma."""

    def __init__(self, resource_kind: str, name: str) -> None:
        self.resource_kind = resource_kind
        self.name = name
        super().__init__(
            f"{resource_kind} inválido: '{name}'. Só letras, dígitos, "
            "underscore ('_') e hífen ('-') são permitidos, sem espaços, "
            "barras, dois-pontos ou '..'."
        )


class HierarchyAlreadyExistsError(PowerBiMcpError):
    """Já existe uma hierarquia com esse nome nessa tabela."""

    def __init__(self, table_name: str, hierarchy_name: str) -> None:
        self.table_name = table_name
        self.hierarchy_name = hierarchy_name
        super().__init__(
            f"Já existe uma hierarquia chamada '{hierarchy_name}' na tabela "
            f"'{table_name}'. Escolha outro nome."
        )


class HierarchyNotFoundError(PowerBiMcpError):
    """Hierarquia referenciada não existe na tabela."""

    def __init__(self, table_name: str, hierarchy_name: str) -> None:
        self.table_name = table_name
        self.hierarchy_name = hierarchy_name
        super().__init__(
            f"Hierarquia '{hierarchy_name}' não existe na tabela '{table_name}'."
        )


class RoleAlreadyExistsError(PowerBiMcpError):
    """Já existe um role com esse nome no modelo."""

    def __init__(self, role_name: str) -> None:
        self.role_name = role_name
        super().__init__(
            f"Já existe um role chamado '{role_name}' no modelo. Escolha outro nome."
        )


class RoleNotFoundError(PowerBiMcpError):
    """Role de RLS referenciado não existe no modelo."""

    def __init__(self, role_name: str) -> None:
        self.role_name = role_name
        super().__init__(f"Role '{role_name}' não existe no modelo.")


class TablePermissionAlreadyExistsError(PowerBiMcpError):
    """Esse role já tem um filtro de RLS definido para essa tabela."""

    def __init__(self, role_name: str, table_name: str) -> None:
        self.role_name = role_name
        self.table_name = table_name
        super().__init__(
            f"O role '{role_name}' já tem um filtro definido para a tabela "
            f"'{table_name}'. Remova o role e recrie, ou escolha outra tabela."
        )


class TablePermissionNotFoundError(PowerBiMcpError):
    """O role não tem uma permissão de tabela (TablePermission) ainda
    para essa tabela -- hide_column/unhide_column precisam de uma já
    existente (mesmo objeto TOM usado pelo filtro de RLS)."""

    def __init__(self, role_name: str, table_name: str) -> None:
        self.role_name = role_name
        self.table_name = table_name
        super().__init__(
            f"O role '{role_name}' não tem uma permissão definida para a "
            f"tabela '{table_name}' ainda. Chame add_table_permission "
            "primeiro (use filter_expression=\"TRUE()\" se só quiser "
            "esconder colunas, sem filtrar linhas)."
        )


class ColumnAlreadyHiddenError(PowerBiMcpError):
    """Essa coluna já está escondida (OLS) para esse role/tabela."""

    def __init__(self, role_name: str, table_name: str, column_name: str) -> None:
        self.role_name = role_name
        self.table_name = table_name
        self.column_name = column_name
        super().__init__(
            f"A coluna '{column_name}' da tabela '{table_name}' já está "
            f"escondida para o role '{role_name}'."
        )


class ColumnNotHiddenError(PowerBiMcpError):
    """Essa coluna não está escondida (OLS) para esse role/tabela --
    não há nada para reverter em unhide_column."""

    def __init__(self, role_name: str, table_name: str, column_name: str) -> None:
        self.role_name = role_name
        self.table_name = table_name
        self.column_name = column_name
        super().__init__(
            f"A coluna '{column_name}' da tabela '{table_name}' não está "
            f"escondida para o role '{role_name}'."
        )


class AdomdDllNotFoundError(PowerBiMcpError):
    """Nenhuma das DLLs do ADOMD.NET (cliente de consulta DAX/MDX) foi
    encontrada nos locais conhecidos. Camada separada da do TOM
    (TomDllNotFoundError): TOM define estrutura, ADOMD.NET executa
    consultas -- são bibliotecas .NET independentes."""

    def __init__(self, searched_paths: list[str]) -> None:
        self.searched_paths = searched_paths
        paths = "\n  - ".join(searched_paths) or "(nenhum)"
        super().__init__(
            "Não foi possível localizar as DLLs do ADOMD.NET "
            "(Microsoft.AnalysisServices.AdomdClient.dll e dependências).\n"
            f"Locais verificados:\n  - {paths}\n"
            "Defina a variável de ambiente ADOMD_DLL_PATH apontando para o "
            "diretório que contém essas DLLs, ou rode scripts/setup_tom.py "
            "para baixá-las automaticamente."
        )


class NotADateColumnError(PowerBiMcpError):
    """A coluna informada como coluna de data não tem tipo DateTime --
    as funções de inteligência de tempo do DAX (TOTALYTD,
    SAMEPERIODLASTYEAR, DATEADD, ...) exigem uma coluna de data de
    verdade."""

    def __init__(self, table_name: str, column_name: str, data_type: str) -> None:
        self.table_name = table_name
        self.column_name = column_name
        self.data_type = data_type
        super().__init__(
            f"A coluna '{table_name}.{column_name}' é do tipo '{data_type}', "
            "não 'DateTime'. Informe uma coluna de data de verdade."
        )


class UnknownTimeIntelligenceVariantError(PowerBiMcpError):
    """Uma variante pedida a create_time_intelligence_measures não é
    uma das reconhecidas."""

    def __init__(self, variant: str, known_variants: list[str]) -> None:
        self.variant = variant
        self.known_variants = known_variants
        super().__init__(
            f"Variante '{variant}' não é reconhecida. Variantes "
            f"disponíveis: {', '.join(known_variants)}."
        )


class FieldParameterError(PowerBiMcpError):
    """`fields` e `display_names` de create_field_parameter têm
    tamanhos diferentes, ou `fields` está vazio."""


class ModelObjectNotFoundError(PowerBiMcpError):
    """Um objeto do modelo (tabela, coluna, medida, role, hierarquia,
    partição, permissão, relacionamento) esperado não foi encontrado ao
    consultar o TOM diretamente -- normalmente porque o modelo mudou por
    fora (outra conexão, ou uma leitura desatualizada) entre a validação
    de uma camada acima e o uso aqui. `operations.py` já valida a maioria
    dos casos de uso comuns com erros mais específicos (TableNotFoundError,
    ColumnNotFoundError, ...) antes de chamar o runtime; este erro é a
    rede de segurança para quem chama o TomRuntime diretamente
    (field_parameters.py, applier.py) ou para essa divergência de
    última hora -- substitui o `StopIteration` cru que os `next(...)`
    soltos levantavam antes (achado ao vivo: virava "Error executing
    tool X" sem nenhuma mensagem, porque StopIteration não carrega
    texto nenhum)."""

    def __init__(
        self, object_kind: str, object_name: str, known: list[str], *, parent: str | None = None,
    ) -> None:
        self.object_kind = object_kind
        self.object_name = object_name
        self.known = known
        self.parent = parent
        where = f" em '{parent}'" if parent else ""
        super().__init__(
            f"{object_kind.capitalize()} '{object_name}' não encontrado(a){where}. "
            f"Conhecidos: {', '.join(known) or '(nenhum)'}."
        )


class InvalidProfileRequestError(PowerBiMcpError):
    """Parâmetro do diagnóstico de medidas (profile_measures) fora do
    permitido (ex: `runs` fora de 1..10)."""


class PerspectiveAlreadyExistsError(PowerBiMcpError):
    """Já existe uma perspectiva com esse nome no modelo."""

    def __init__(self, name: str) -> None:
        self.name = name
        super().__init__(f"Já existe uma perspectiva chamada '{name}' no modelo. Escolha outro nome.")


class PerspectiveNotFoundError(PowerBiMcpError):
    """Perspectiva referenciada não existe no modelo."""

    def __init__(self, name: str, known: list[str]) -> None:
        self.name = name
        super().__init__(
            f"Perspectiva '{name}' não existe no modelo. Existentes: {', '.join(known) or '(nenhuma)'}."
        )


class InvalidPerspectiveError(PowerBiMcpError):
    """Perspectiva sem nome ou sem nenhuma tabela/campo."""


class InvalidBookmarkError(PowerBiMcpError):
    """Bookmark pedido de um jeito impossível (ex: o mesmo visual visível
    e escondido ao mesmo tempo)."""


class ModelOperationFailedError(PowerBiMcpError):
    """Uma operação TOM (ex.: SaveChanges, RequestRefresh) falhou no
    motor do Analysis Services -- a mensagem original do motor é
    preservada. Ver modeling/tom_errors.py:translate_dotnet_exception
    pra saber quais tipos .NET viram este erro."""

    def __init__(self, operation: str, original_message: str) -> None:
        self.operation = operation
        self.original_message = original_message
        super().__init__(
            f"A operação '{operation}' falhou no motor do Analysis Services.\n"
            f"Erro original: {original_message}"
        )


class ModelOutOfSyncError(PowerBiMcpError):
    """O modelo local ficou fora de sincronia com o servidor de um jeito
    que `Model.Sync()` não resolveu sozinho (OutOfSyncException do TOM)
    -- normalmente porque outra conexão mudou o mesmo objeto ao mesmo
    tempo. Não tenta resolver sozinho (poderia descartar mudança local
    não salva); reconectar com connect_to_desktop e tentar de novo é o
    caminho seguro."""

    def __init__(self, operation: str, original_message: str) -> None:
        self.operation = operation
        self.original_message = original_message
        super().__init__(
            f"O modelo ficou fora de sincronia durante '{operation}' -- "
            "provavelmente outra conexão (ex: a UI do Desktop) mudou o "
            "mesmo objeto ao mesmo tempo. Reconecte (connect_to_desktop) "
            f"e tente de novo.\nErro original: {original_message}"
        )


class StaleConnectionError(PowerBiMcpError):
    """A conexão XMLA com o Power BI Desktop expirou ou morreu -- o
    processo interno do Desktop (msmdsrv.exe) pode reiniciar sozinho e
    trocar de porta (observado ao vivo nesta sessão, duas vezes: a porta
    XMLA mudou entre uma chamada e outra sem nenhuma ação do usuário).
    Qualquer mudança de modelo ainda não persistida via save_changes/
    save_desktop foi perdida junto -- a mensagem avisa disso
    explicitamente, pra não deixar o agente (ou o usuário) achar que só
    precisa reconectar e seguir de onde parou."""

    def __init__(self, original_message: str, live_ports: tuple[int, ...] = ()) -> None:
        self.original_message = original_message
        self.live_ports = live_ports
        if live_ports:
            hint = (
                f"Uma instância do Power BI Desktop foi encontrada viva na "
                f"porta {live_ports[0]} agora -- chame "
                f"connect_to_desktop(port={live_ports[0]})."
            )
        else:
            hint = (
                "Nenhuma instância do Power BI Desktop foi encontrada aberta "
                "agora -- abra o Desktop e chame connect_to_desktop de novo."
            )
        super().__init__(
            "A conexão com o Power BI Desktop expirou. "
            "Qualquer mudança de modelo não salva (save_changes/"
            f"save_desktop) foi perdida. {hint}\n"
            f"Erro original: {original_message}"
        )


class ImplicitMeasuresMustBeDiscouragedError(PowerBiMcpError):
    """Criar um calculation group exige `DiscourageImplicitMeasures =
    true` no modelo (doc oficial: "in order to create calculation groups
    this property must be set to true") -- e isso muda o modelo INTEIRO.
    Por decisão do usuário, a tool nunca liga sozinha: exige opt-in
    explícito (`allow_discourage_implicit_measures=True`)."""

    def __init__(self) -> None:
        super().__init__(
            "Criar um calculation group exige ligar 'Discourage implicit "
            "measures' no modelo inteiro. Efeito colateral: dali pra frente "
            "o Desktop não deixa mais arrastar uma coluna como valor "
            "agregado (SUM/MÉDIA implícitos) -- visuais que já usam isso "
            "continuam funcionando -- e, com um calculation group no modelo, "
            "todas as medidas passam a ser reportadas como tipo 'variant'. "
            "Confirme com o usuário e chame de novo com "
            "allow_discourage_implicit_measures=True."
        )


class InvalidCalculationGroupError(PowerBiMcpError):
    """Definição de calculation group inválida (sem itens, item sem
    nome/expressão, nomes de item repetidos)."""


class CalculationGroupNotFoundError(PowerBiMcpError):
    """A tabela informada não existe ou não é um calculation group."""

    def __init__(self, table_name: str, known_groups: list[str]) -> None:
        self.table_name = table_name
        self.known_groups = known_groups
        super().__init__(
            f"'{table_name}' não é um calculation group do modelo. "
            f"Calculation groups existentes: {', '.join(known_groups) or '(nenhum)'}."
        )


class CalculationItemAlreadyExistsError(PowerBiMcpError):
    """Já existe um item com esse nome no calculation group."""

    def __init__(self, table_name: str, item_name: str) -> None:
        self.table_name = table_name
        self.item_name = item_name
        super().__init__(
            f"O calculation group '{table_name}' já tem um item chamado '{item_name}'."
        )


class CalculationItemNotFoundError(PowerBiMcpError):
    """O item não existe no calculation group."""

    def __init__(self, table_name: str, item_name: str, known_items: list[str]) -> None:
        self.table_name = table_name
        self.item_name = item_name
        self.known_items = known_items
        super().__init__(
            f"O calculation group '{table_name}' não tem item '{item_name}'. "
            f"Itens: {', '.join(known_items) or '(nenhum)'}."
        )


class UnknownAuditRuleError(PowerBiMcpError):
    """Um código de regra pedido a audit_model não existe."""

    def __init__(self, rule: str, known_rules: list[str]) -> None:
        self.rule = rule
        self.known_rules = known_rules
        super().__init__(
            f"Regra de auditoria '{rule}' não existe. Regras disponíveis: "
            f"{', '.join(known_rules)}."
        )


class QueryConnectionError(PowerBiMcpError):
    """Não foi possível abrir a conexão de consulta (ADOMD.NET) com o
    modelo -- a mensagem original do motor é preservada. Achado ao vivo
    (2026-09-26): sem isto, um erro no Open() que o tradutor de exceções
    não reconhecia (ex: EffectiveUserName que o Desktop local não
    consegue resolver) virava "Error executing tool X" sem mensagem."""

    def __init__(self, original_message: str) -> None:
        self.original_message = original_message
        super().__init__(
            f"Não foi possível abrir a conexão de consulta com o modelo.\n"
            f"Erro do motor: {original_message}"
        )


class InvalidRlsSimulationError(PowerBiMcpError):
    """Parâmetros inválidos pra evaluate_dax_as_role: nenhum role, ou um
    nome de role/usuário com caractere que quebraria (ou adulteraria) a
    string de conexão ADOMD (`;`, `"`, e `,` em nome de role -- a
    propriedade `Roles` é uma lista separada por vírgula)."""


class DaxQueryError(PowerBiMcpError):
    """A consulta DAX falhou ao executar contra o modelo (sintaxe
    inválida, referência a tabela/coluna/medida inexistente, etc.)."""

    def __init__(self, dax_query: str, original_message: str) -> None:
        self.dax_query = dax_query
        self.original_message = original_message
        super().__init__(
            f"Falha ao executar a consulta DAX:\n{dax_query}\n\n"
            f"Erro do motor de consulta: {original_message}"
        )


# --- Camada de visuais ----------------------------------------------------


class UnknownFieldError(PowerBiMcpError):
    """Um campo (tabela.coluna ou medida) referenciado num visual não
    corresponde a nada no ModelMetadata."""

    def __init__(self, entity: str, property: str, suggestions: list[str] | None = None) -> None:
        self.entity = entity
        self.property = property
        self.suggestions = suggestions or []
        msg = f"Campo '{entity}.{property}' não foi encontrado no modelo."
        if self.suggestions:
            msg += f" Você quis dizer: {', '.join(self.suggestions)}?"
        super().__init__(msg)


class InvalidVisualFormattingError(PowerBiMcpError):
    """Formatação pedida não existe pra esse tipo de visual, ou o valor
    não é válido (fora da lista/limite do schema oficial de tema -- ver
    visuals/formatting_spec.json)."""


class InvalidCustomVisualError(PowerBiMcpError):
    """O arquivo .pbiviz não existe, não é um pacote válido (zip com
    package.json + resources/<GUID>.pbiviz.json) ou tem caminho/GUID
    inseguro."""


class CustomVisualAlreadyExistsError(PowerBiMcpError):
    """Esse visual personalizado já está importado no relatório."""


class CustomVisualNotFoundError(PowerBiMcpError):
    """Visual personalizado não está importado no relatório."""


class CustomVisualInUseError(PowerBiMcpError):
    """Não dá pra remover o visual personalizado: há visuais usando ele."""


class InvalidVisualRoleError(PowerBiMcpError):
    """Um role recebeu um número ou tipo de campo incompatível com sua
    especificação no catálogo de visuais (arity/kind)."""


class UnknownVisualTypeError(PowerBiMcpError):
    """Tipo de visual não está no catálogo suportado."""

    def __init__(self, visual_type: str, known_types: list[str]) -> None:
        self.visual_type = visual_type
        self.known_types = known_types
        super().__init__(
            f"Tipo de visual '{visual_type}' não é suportado. "
            f"Tipos disponíveis: {', '.join(known_types)}."
        )


class ReportProjectNotFoundError(PowerBiMcpError):
    """O caminho informado não é ou não contém uma pasta de relatório
    PBIP/PBIR válida."""


class SemanticModelNotFoundError(PowerBiMcpError):
    """O caminho informado não é ou não contém uma pasta .SemanticModel
    com uma definição TMDL válida (definition/tables/*.tmdl)."""

    def __init__(self, pbip_path: str) -> None:
        self.pbip_path = pbip_path
        super().__init__(
            f"Não foi possível encontrar uma pasta .SemanticModel com "
            f"definição TMDL a partir de '{pbip_path}'. Informe o "
            "caminho do arquivo .pbip, da pasta do projeto, ou da própria "
            "pasta .SemanticModel."
        )


class InvalidPageNameError(PowerBiMcpError):
    """page_name não é um nome de objeto PBIR válido.

    page_name vira o nome de uma pasta em definition/pages/<page_name>/,
    então um valor com "..", "/", "\\", dois-pontos ou similar poderia
    escapar da pasta pretendida (path traversal). Além do risco de
    segurança, o PBIR também exige que nomes de objeto (diferente do
    display_name, que pode ter qualquer texto) usem só letras, dígitos,
    underscore ou hífen -- ver a seção "PBIR naming convention" em
    https://learn.microsoft.com/power-bi/developer/projects/projects-report
    """

    def __init__(self, page_name: str) -> None:
        self.page_name = page_name
        super().__init__(
            f"page_name inválido: '{page_name}'. Só letras, dígitos, "
            "underscore ('_') e hífen ('-') são permitidos, sem espaços, "
            "barras, dois-pontos ou '..'. Use display_name para um nome "
            "amigável com espaços/acentos."
        )


class PageNotFoundError(PowerBiMcpError):
    """Página referenciada não existe no relatório."""


class BookmarkAlreadyExistsError(PowerBiMcpError):
    """Já existe um bookmark com esse nome no relatório."""

    def __init__(self, bookmark_name: str) -> None:
        self.bookmark_name = bookmark_name
        super().__init__(
            f"Já existe um bookmark chamado '{bookmark_name}' neste relatório. "
            "Escolha outro nome."
        )


class BookmarkNotFoundError(PowerBiMcpError):
    """Bookmark referenciado não existe no relatório."""

    def __init__(self, bookmark_name: str) -> None:
        self.bookmark_name = bookmark_name
        super().__init__(f"Bookmark '{bookmark_name}' não existe neste relatório.")


class InvalidThemeColorError(PowerBiMcpError):
    """Uma cor de `data_colors` não está em hexadecimal válido."""

    def __init__(self, color: str) -> None:
        self.color = color
        super().__init__(
            f"Cor de tema inválida: '{color}'. Use hexadecimal com '#' "
            "(ex: '#2E86AB')."
        )


class ThemeNotFoundError(PowerBiMcpError):
    """Não há tema customizado aplicado neste relatório -- nada para
    remove_report_theme reverter."""


class PageAlreadyExistsError(PowerBiMcpError):
    """Já existe uma página com esse nome no relatório."""

    def __init__(self, page_name: str) -> None:
        self.page_name = page_name
        super().__init__(
            f"Já existe uma página chamada '{page_name}' neste relatório. "
            "Escolha outro nome."
        )


class DrillthroughFieldAlreadyExistsError(PowerBiMcpError):
    """A página já está configurada como destino de drillthrough para
    esse campo -- não há o que adicionar de novo."""

    def __init__(self, page_name: str, query_ref: str) -> None:
        self.page_name = page_name
        self.query_ref = query_ref
        super().__init__(
            f"A página '{page_name}' já é destino de drillthrough para "
            f"'{query_ref}'."
        )


class DrillthroughFieldNotFoundError(PowerBiMcpError):
    """A página não está configurada como destino de drillthrough para
    esse campo -- nada para remove_drillthrough_field reverter."""

    def __init__(self, page_name: str, query_ref: str) -> None:
        self.page_name = page_name
        self.query_ref = query_ref
        super().__init__(
            f"A página '{page_name}' não é destino de drillthrough para "
            f"'{query_ref}'."
        )


class InvalidFilterDefinitionError(PowerBiMcpError):
    """Os parâmetros de um filtro de página/relatório não formam um
    filtro válido (lista de valores vazia, `between` sem limite,
    operador desconhecido, tipo de coluna sem formato de literal
    conhecido, ou filtro com valor pedido sobre uma medida)."""


class FilterAlreadyExistsError(PowerBiMcpError):
    """Já existe um filtro de usuário (howCreated="User") nesse campo,
    nesse escopo -- remova antes de criar outro."""

    def __init__(self, scope: str, query_ref: str) -> None:
        self.scope = scope
        self.query_ref = query_ref
        where = "no relatório" if scope == "report" else f"na página '{scope}'"
        super().__init__(
            f"Já existe um filtro em '{query_ref}' {where}. Remova-o antes "
            "de criar outro (remove_page_filter/remove_report_filter)."
        )


class FilterNotFoundError(PowerBiMcpError):
    """Não há filtro de usuário (howCreated="User") nesse campo, nesse
    escopo -- nada pra remover."""

    def __init__(self, scope: str, query_ref: str) -> None:
        self.scope = scope
        self.query_ref = query_ref
        where = "no relatório" if scope == "report" else f"na página '{scope}'"
        super().__init__(f"Não há filtro em '{query_ref}' {where}.")


# --- Camada de orquestração ------------------------------------------------


class BlueprintValidationError(PowerBiMcpError):
    """O blueprint recebido em apply_dashboard_blueprint não passou a
    validação de shape (Pydantic) ou de referências cruzadas."""
