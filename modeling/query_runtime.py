"""Segunda (e última) fronteira com .NET/pythonnet deste projeto --
separada de modeling/tom_runtime.py de propósito: TOM
(Microsoft.AnalysisServices.Tabular) define a ESTRUTURA do modelo
(tabelas, medidas, relacionamentos) e nunca executa uma consulta;
ADOMD.NET (Microsoft.AnalysisServices.AdomdClient) executa DAX/MDX e
devolve valores reais, mas não sabe criar/alterar nada. São bibliotecas
.NET independentes -- por isso duas fronteiras, não uma.

Mesma disciplina de tom_runtime.py: só este arquivo importa `clr` ou
referencia `Microsoft.AnalysisServices.AdomdClient.*` diretamente,
sempre dentro de função (nunca no nível do módulo), para que o arquivo
seja importável (e resolve_adomd_dll_dir testável) sem pythonnet
instalado.

`connect()` e `execute()` foram validados com uma conexão real (Power
BI Desktop via Microsoft Store + DLLs de scripts/setup_tom.py):
`EVALUATE ROW(...)` e `SUMMARIZECOLUMNS(...)` com `TOPN` devolveram
valores agregados reais -- ver README, seção "Validação real". Não têm
cobertura de teste *automatizado* nesta máquina (não há como simular
ADOMD.NET real em CI sem o Power BI Desktop instalado), mas a suíte
automatizada cobre toda a lógica ao redor (resolução de DLL) via
funções puras e o FakeQueryRuntime.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Protocol

from errors import AdomdDllNotFoundError, DaxQueryError, QueryConnectionError

REQUIRED_DLLS: tuple[str, ...] = (
    "Microsoft.AnalysisServices.AdomdClient.dll",
    "Microsoft.AnalysisServices.Runtime.Core.dll",
    "Microsoft.AnalysisServices.Runtime.Windows.dll",
)


class QueryRuntime(Protocol):
    """Interface Python pura para uma conexão ADOMD.NET aberta,
    capaz de executar uma consulta DAX e devolver linhas já em tipos
    Python nativos."""

    def execute(
        self, dax_query: str, max_rows: int | None = None
    ) -> tuple[list[dict[str, Any]], bool]: ...

    def clear_cache(self, database_id: str) -> None: ...

    def close(self) -> None: ...


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _candidate_dll_dirs() -> list[Path]:
    """Locais conhecidos onde as DLLs do ADOMD.NET podem estar
    instaladas, em ordem de prioridade (depois de ADOMD_DLL_PATH,
    tratado separado em resolve_adomd_dll_dir)."""
    program_files = Path(os.environ.get("PROGRAMFILES", r"C:\Program Files"))
    program_files_x86 = Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)"))

    return [
        # pasta gerada por scripts/setup_tom.py -- checada primeiro
        # porque, se existe, foi colocada lá deliberadamente para este
        # projeto (e o script já confere o SHA-512 contra a Microsoft).
        _project_root() / ".tom-dlls" / "dlls",
        program_files / "Microsoft Power BI Desktop" / "bin",
        program_files_x86 / "Tabular Editor",
        program_files / "Tabular Editor",
        program_files_x86 / "Tabular Editor 3",
        program_files / "Tabular Editor 3",
    ]


def _has_required_dlls(directory: Path) -> bool:
    return directory.is_dir() and all((directory / dll).is_file() for dll in REQUIRED_DLLS)


def resolve_adomd_dll_dir(extra_candidates: list[Path] | None = None) -> Path:
    """Encontra um diretório contendo as DLLs do ADOMD.NET.

    Ordem de prioridade: `ADOMD_DLL_PATH` (variável de ambiente)
    primeiro, depois `extra_candidates` (usado pelos testes para
    injetar diretórios fake), depois os locais de instalação conhecidos
    (`_candidate_dll_dirs`).

    Raises:
        AdomdDllNotFoundError: nenhum candidato continha as DLLs.
    """
    searched: list[Path] = []

    env_path = os.environ.get("ADOMD_DLL_PATH")
    if env_path:
        env_dir = Path(env_path)
        searched.append(env_dir)
        if _has_required_dlls(env_dir):
            return env_dir

    for candidate in (extra_candidates or []) + _candidate_dll_dirs():
        searched.append(candidate)
        if _has_required_dlls(candidate):
            return candidate

    raise AdomdDllNotFoundError(searched_paths=[str(p) for p in searched])


def build_connection_string(
    port: int,
    database_name: str,
    roles: list[str] | None = None,
) -> str:
    """String de conexão ADOMD pro Desktop local. Sem `roles`, idêntica
    à de sempre.

    `roles` -- doc oficial "Connection string properties (Analysis
    Services)": `Roles` é "a comma-delimited list of predefined roles
    ... An administrator using this property connects using the
    permissions conveyed by the role" (quem abre o Desktop é
    administrador do modelo local, então isso é exatamente a simulação
    de RLS -- confirmado ao vivo). Valor entre aspas duplas; `;`, `"` e
    `,` num nome de role são recusados -- defesa em profundidade contra
    injeção na string de conexão, além da validação em modeling/query.py.

    `EffectiveUserName` (simular um usuário específico) foi testado ao
    vivo e não funciona no Desktop local sem domínio corporativo (o
    motor tenta resolver como conta Windows: "not a properly formed
    account name" / "domain isn't available") -- removido.
    """
    parts = [f"Data Source=localhost:{port}", f"Catalog={database_name}"]
    if roles:
        for role in roles:
            if any(ch in role for ch in ';",'):
                raise ValueError(f"Nome de role inseguro pra string de conexão: {role!r}")
        parts.append(f'Roles="{",".join(roles)}"')
    return ";".join(parts)


def connect(
    port: int,
    database_name: str,
    roles: list[str] | None = None,
) -> QueryRuntime:
    """Abre uma conexão ADOMD.NET com o endpoint XMLA local de uma
    instância do Power BI Desktop, para executar consultas contra um
    banco específico.

    Diferente de tom_runtime.connect: aqui `database_name` é obrigatório
    (a string de conexão do ADOMD precisa do catálogo explícito) -- em
    modeling/query.py, evaluate_dax sempre o obtém da conexão TOM ativa.

    Raises:
        AdomdDllNotFoundError: se as DLLs do ADOMD.NET não puderem ser
            localizadas (propagado por resolve_adomd_dll_dir).
    """
    dll_dir = resolve_adomd_dll_dir()

    import sys

    if str(dll_dir) not in sys.path:
        sys.path.append(str(dll_dir))

    import pythonnet  # noqa: PLC0415 - import tardio deliberado, ver docstring do módulo
    from modeling.tom_runtime import _dotnet_runtime_name  # noqa: PLC0415

    pythonnet.load(_dotnet_runtime_name())  # idempotente -- ver tom_runtime.connect

    import clr  # noqa: PLC0415 - import tardio deliberado, ver docstring do módulo

    for dll_name in REQUIRED_DLLS:
        clr.AddReference(str(dll_dir / dll_name))

    from Microsoft.AnalysisServices.AdomdClient import AdomdConnection  # type: ignore[import-not-found]

    connection = AdomdConnection(
        build_connection_string(port, database_name, roles=roles)
    )
    try:
        connection.Open()
    except Exception as exc:  # noqa: BLE001 - ver translate_open_error
        raise translate_open_error(exc) from exc
    return _PythonnetQueryRuntime(connection=connection)


def translate_open_error(exc: Exception) -> Exception:
    """Erro ao abrir a conexão de consulta -> erro do projeto, SEMPRE com
    a mensagem do motor. Conexão morta vira StaleConnectionError (pelo
    tradutor de modeling/tom_errors.py); qualquer outra coisa vira
    QueryConnectionError -- antes, o que o tradutor não reconhecia
    escapava cru e virava "Error executing tool X" sem mensagem (achado
    ao vivo com EffectiveUserName, 2026-09-26)."""
    from modeling.tom_errors import translate_dotnet_exception  # noqa: PLC0415

    translated = translate_dotnet_exception(type(exc).__name__, str(exc), operation="query_connect")
    if translated is not None:
        return translated
    return QueryConnectionError(str(exc))


class _PythonnetQueryRuntime:
    """Implementação real do QueryRuntime Protocol sobre uma
    AdomdConnection (.NET) viva. Ver docstring do módulo: sem cobertura
    de teste automatizado nesta máquina."""

    def __init__(self, connection: object) -> None:
        self._connection = connection

    def execute(
        self, dax_query: str, max_rows: int | None = None
    ) -> tuple[list[dict[str, Any]], bool]:
        from Microsoft.AnalysisServices.AdomdClient import AdomdCommand  # type: ignore[import-not-found]

        command = AdomdCommand(dax_query, self._connection)
        try:
            reader = command.ExecuteReader()
            try:
                column_names = [reader.GetName(i) for i in range(reader.FieldCount)]
                rows: list[dict[str, Any]] = []
                truncated = False
                while reader.Read():
                    if max_rows is not None and len(rows) >= max_rows:
                        truncated = True
                        break
                    rows.append(
                        {
                            name: _convert_value(reader.GetValue(i))
                            for i, name in enumerate(column_names)
                        }
                    )
            finally:
                # achado ao vivo (bug 1.2): GetName/Read/GetValue rodavam
                # FORA deste try antes -- um AdomdException no meio da
                # leitura de linhas (ex.: conexão morrendo no meio da
                # consulta) escapava crua em vez de virar DaxQueryError.
                reader.Close()
        except Exception as exc:  # noqa: BLE001 - mensagem do motor de consulta é o que importa aqui
            raise DaxQueryError(dax_query=dax_query, original_message=str(exc)) from exc
        return rows, truncated

    def clear_cache(self, database_id: str) -> None:
        """Esvazia o cache do motor pro banco (comando XMLA oficial
        ClearCache com <Object><DatabaseID> -- Microsoft Learn). Não muda
        nada no modelo, só faz a próxima consulta rodar "a frio".
        CONFIRMADO AO VIVO (2026-09-29): enviado pela própria conexão
        ADOMD com o namespace do engine XMLA, e no Desktop o ID do banco
        é igual ao nome."""
        from xml.sax.saxutils import escape

        from Microsoft.AnalysisServices.AdomdClient import AdomdCommand  # type: ignore[import-not-found]

        xmla = (
            '<ClearCache xmlns="http://schemas.microsoft.com/analysisservices/2003/engine">'
            f"<Object><DatabaseID>{escape(database_id)}</DatabaseID></Object></ClearCache>"
        )
        try:
            AdomdCommand(xmla, self._connection).ExecuteNonQuery()
        except Exception as exc:  # noqa: BLE001 - mensagem do motor é o que importa
            raise DaxQueryError(dax_query=xmla, original_message=str(exc)) from exc

    def close(self) -> None:
        self._connection.Close()  # type: ignore[attr-defined]


def _convert_value(value: object) -> Any:
    """Normaliza um valor .NET devolvido por AdomdDataReader para um
    tipo Python nativo serializável. pythonnet já converte a maioria dos
    tipos primitivos (int, float, str, bool) automaticamente -- o que
    resta tratar aqui são os que não têm equivalente Python direto:
    DBNull (célula vazia/blank do DAX) e DateTime (colunas de data)."""
    if value is None:
        return None
    type_name = type(value).__name__
    if type_name == "DBNull":
        return None
    if type_name == "DateTime":
        return value.ToString("o")  # type: ignore[attr-defined]  # ISO 8601
    if type_name == "Decimal":
        return float(value)  # type: ignore[arg-type]
    return value
