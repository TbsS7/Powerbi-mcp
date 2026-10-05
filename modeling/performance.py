"""Diagnóstico de medidas DAX lentas: mede o tempo de cada medida e
aponta padrões que o guia oficial da Microsoft diz serem lentos.

Só leitura -- não muda nada no modelo. A medição usa a mesma conexão
ADOMD de evaluate_dax (modeling/query.py):

- uma consulta de aquecimento antes de tudo: achado ao vivo
  (2026-09-29) -- a 1a consulta numa conexão nova custou ~50ms só de
  "acordar" a conexão, contra 4-9ms das seguintes; sem isso, a 1a
  medida sempre pareceria lenta;
- por medida: (opcional) limpa o cache do motor (ClearCache, ver
  query_runtime.clear_cache) e mede uma execução "a frio" -- o que o
  usuário sente ao abrir o relatório --, depois `runs` execuções "a
  quente" (mediana);
- a consulta é `ROW` (valor total) ou, com `group_by`,
  `SUMMARIZECOLUMNS` por uma coluna (o que um gráfico faz).

O tempo é medido deste lado (relógio de parede em volta da consulta,
inclui a ida e volta da conexão) -- não separa motor de fórmulas x
motor de armazenamento (isso exige um trace do servidor, fora do
escopo). Serve pra COMPARAR medidas entre si, não como número absoluto.

Dicas (dax_hints): análise de texto da expressão, baseada nas regras do
guia oficial "DAX best practices" (Microsoft Learn). É heurística --
aponta o padrão, não prova que ele é o culpado (ex: FILTER às vezes é
necessário, quando compara com uma medida).
"""

from __future__ import annotations

import re
import statistics
import time
from typing import Any

from errors import DaxQueryError, InvalidProfileRequestError, ModelObjectNotFoundError
from modeling import connection, query_runtime

_clock = time.perf_counter  # substituível nos testes
_WARMUP_QUERY = "EVALUATE {1}"
_MAX_RUNS = 10

_DOCS = "https://learn.microsoft.com/en-us/dax/best-practices/"


def profile_measures(
    measures: list[str] | None = None,
    group_by: str | None = None,
    runs: int = 3,
    cold_cache: bool = True,
) -> dict[str, Any]:
    """Mede cada medida (todas do modelo, ou `measures` -- "Tabela.Medida"
    ou só "Medida") e devolve da mais lenta pra mais rápida, com dicas."""
    if not 1 <= runs <= _MAX_RUNS:
        raise InvalidProfileRequestError(f"runs = {runs} fora do permitido (1 a {_MAX_RUNS}).")

    runtime = connection.get_active_runtime()
    runtime.refresh_metadata()
    all_measures = runtime.list_measures()
    selected = _select_measures(all_measures, measures)
    group_column = _resolve_column(runtime.list_tables(), group_by) if group_by else None

    query_conn = query_runtime.connect(port=runtime.port, database_name=runtime.database_name)
    results = []
    try:
        query_conn.execute(_WARMUP_QUERY)
        for measure in selected:
            dax = _measure_query(measure.table_name, measure.name, group_column)
            entry: dict[str, Any] = {
                "measure": f"{measure.table_name}.{measure.name}",
                "cold_ms": None,
                "warm_ms": None,
                "rows": None,
                "error": None,
                "hints": dax_hints(measure.dax_expression or ""),
            }
            try:
                if cold_cache:
                    query_conn.clear_cache(runtime.database_name)
                    entry["cold_ms"], entry["rows"] = _timed(query_conn, dax)
                warm = []
                for _ in range(runs):
                    elapsed, entry["rows"] = _timed(query_conn, dax)
                    warm.append(elapsed)
                entry["warm_ms"] = round(statistics.median(warm), 1)
            except DaxQueryError as exc:
                entry["error"] = exc.original_message
            results.append(entry)
    finally:
        query_conn.close()

    results.sort(key=lambda m: (m["error"] is not None, -(m["cold_ms"] or m["warm_ms"] or 0)))
    return {
        "measures": results,
        "group_by": group_by,
        "runs": runs,
        "cold_cache": cold_cache,
        "note": (
            "Tempos em milissegundos, medidos deste lado (incluem a ida e volta da conexão) -- "
            "use pra comparar medidas entre si. cold_ms = com cache limpo (o que o usuário sente "
            "ao abrir o relatório); warm_ms = mediana com cache. As dicas são padrões apontados "
            "pelo guia oficial de boas práticas de DAX, não prova de que são a causa."
        ),
    }


def _select_measures(all_measures, requested: list[str] | None):
    if requested is None:
        return list(all_measures)
    known = [f"{m.table_name}.{m.name}" for m in all_measures]
    selected = []
    for name in requested:
        matches = [m for m in all_measures if f"{m.table_name}.{m.name}" == name]
        if not matches:
            matches = [m for m in all_measures if m.name == name]
        if len(matches) != 1:
            raise ModelObjectNotFoundError("medida", name, known=known)
        selected.append(matches[0])
    return selected


def _resolve_column(tables, query_ref: str) -> tuple[str, str]:
    for table in tables:
        for column in table.columns:
            if f"{table.name}.{column.name}" == query_ref:
                return table.name, column.name
    known = [f"{t.name}.{c.name}" for t in tables for c in t.columns]
    raise ModelObjectNotFoundError("coluna", query_ref, known=known)


def _measure_query(table_name: str, measure_name: str, group_column: tuple[str, str] | None) -> str:
    measure_ref = f"{_table(table_name)}{_bracket(measure_name)}"
    if group_column is None:
        return f'EVALUATE ROW("Valor", {measure_ref})'
    column_ref = f"{_table(group_column[0])}{_bracket(group_column[1])}"
    return f'EVALUATE SUMMARIZECOLUMNS({column_ref}, "Valor", {measure_ref})'


def _table(name: str) -> str:
    return "'" + name.replace("'", "''") + "'"


def _bracket(name: str) -> str:
    return "[" + name.replace("]", "]]") + "]"


def _timed(query_conn, dax: str) -> tuple[float, int]:
    start = _clock()
    rows, _ = query_conn.execute(dax)
    return round((_clock() - start) * 1000, 1), len(rows)


# --- dicas estáticas (guia oficial "DAX best practices") ------------------------


_STRING = re.compile(r'"(?:[^"]|"")*"')
_LINE_COMMENT = re.compile(r"(--|//)[^\n]*")
_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)


def dax_hints(dax_expression: str) -> list[dict[str, str]]:
    """Padrões da expressão que o guia oficial da Microsoft aponta como
    lentos, cada um com a mensagem e o link da doc."""
    code = _BLOCK_COMMENT.sub(" ", _STRING.sub('""', dax_expression))
    code = _LINE_COMMENT.sub(" ", code)
    hints = []

    if re.search(r"\b(IFERROR|ISERROR)\s*\(", code, re.IGNORECASE):
        hints.append(_hint(
            "FUNCOES_DE_ERRO",
            "Usa IFERROR/ISERROR -- o guia oficial diz que podem degradar muito a performance "
            "(mais leituras no motor de armazenamento). Prefira DIVIDE, IF com teste, ou tratar o "
            "dado na origem.",
            "dax-error-functions",
        ))
    if re.search(r"\bCALCULATE(TABLE)?\s*\(", code, re.IGNORECASE) and re.search(r"\bFILTER\s*\(", code, re.IGNORECASE):
        hints.append(_hint(
            "FILTER_COMO_FILTRO",
            "Usa FILTER dentro de CALCULATE -- se o filtro for só coluna = valor, uma expressão "
            "booleana (ex: KEEPFILTERS('Produto'[Cor] = \"Red\")) é mais eficiente. FILTER só é "
            "necessário pra comparar com medida ou outra coluna.",
            "dax-avoid-avoid-filter-as-filter-argument",
        ))
    if re.search(r"\bIF\s*\(\s*ISBLANK\s*\(", code, re.IGNORECASE) or _divide_with_alternate(code):
        hints.append(_hint(
            "BLANK_VIRA_VALOR",
            "Troca BLANK por um valor (IF(ISBLANK(...), 0, ...) ou DIVIDE com 3o argumento) -- "
            "isso faz o visual calcular todas as combinações (inclusive as vazias) e deixa o "
            "relatório mais lento. O guia recomenda devolver BLANK.",
            "dax-avoid-converting-blank",
        ))
    if re.search(r"\bCOUNT\s*\(", code, re.IGNORECASE):
        hints.append(_hint(
            "COUNT_EM_VEZ_DE_COUNTROWS",
            "Usa COUNT(coluna) -- pra contar linhas, COUNTROWS(tabela) é mais eficiente segundo o "
            "guia oficial (e não depende de a coluna ter vazios).",
            "dax-countrows",
        ))
    if _has_repeated_calculate(code):
        hints.append(_hint(
            "EXPRESSAO_REPETIDA",
            "Repete a mesma expressão CALCULATE(...) -- guardar numa variável (VAR ... RETURN) "
            "evita calcular duas vezes; no exemplo do guia oficial, cai pra cerca de metade do "
            "tempo.",
            "dax-variables",
        ))
    return hints


def _hint(code: str, message: str, doc_page: str) -> dict[str, str]:
    return {"code": code, "message": message, "doc": _DOCS + doc_page}


def _call_bodies(code: str, function: str) -> list[str]:
    """Conteúdo entre os parênteses de cada chamada de `function`."""
    bodies = []
    for match in re.finditer(rf"\b{function}\s*\(", code, re.IGNORECASE):
        depth, start = 1, match.end()
        for i in range(start, len(code)):
            if code[i] == "(":
                depth += 1
            elif code[i] == ")":
                depth -= 1
                if depth == 0:
                    bodies.append(code[start:i])
                    break
    return bodies


def _top_level_args(body: str) -> int:
    depth, count = 0, 1
    for ch in body:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif ch == "," and depth == 0:
            count += 1
    return count


def _divide_with_alternate(code: str) -> bool:
    return any(_top_level_args(body) >= 3 for body in _call_bodies(code, "DIVIDE"))


def _has_repeated_calculate(code: str) -> bool:
    normalized = [re.sub(r"\s+", "", body).upper() for body in _call_bodies(code, "CALCULATE")]
    return len(normalized) != len(set(normalized))
