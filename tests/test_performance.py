"""Testes de modeling.performance: diagnóstico de medidas DAX lentas.

O relógio (`performance._clock`) é substituído por uma sequência
controlada, e query_runtime.connect devolve um FakeQueryRuntime -- nada
aqui toca .NET nem depende da velocidade da máquina.

Fontes das dicas: guia oficial "DAX best practices" (Microsoft Learn) --
error functions, avoid converting BLANKs, avoid FILTER as filter
argument, COUNTROWS instead of COUNT, use variables. Limpeza de cache:
comando XMLA oficial ClearCache com <Object><DatabaseID> (Microsoft
Learn); confirmado ao vivo em 2026-09-29 que no Desktop o ID do banco é
igual ao nome e que o ClearCache pela conexão ADOMD funciona.
"""

from __future__ import annotations

import itertools

import pytest

from errors import InvalidProfileRequestError, ModelObjectNotFoundError
from modeling import connection, performance, query_runtime
from modeling.metadata import ColumnInfo, TableInfo
from tests.fakes.fake_query import FakeQueryRuntime
from tests.fakes.fake_tom import FakeTomRuntime

_WARMUP = "EVALUATE {1}"


@pytest.fixture
def fake_tom() -> FakeTomRuntime:
    runtime = FakeTomRuntime(database_name="Vendas", port=51999)
    runtime.add_table(TableInfo(name="Vendas", columns=(
        ColumnInfo(name="Valor", data_type="Double"), ColumnInfo(name="Regiao", data_type="String"),
    )))
    runtime.create_measure("Vendas", "Rapida", "SUM(Vendas[Valor])", None)
    runtime.create_measure("Vendas", "Lenta", "IFERROR(SUM(Vendas[Valor]) / COUNT(Vendas[Valor]), 0)", None)
    connection.set_active_runtime(runtime)
    return runtime


def _clock_ticks(durations_ms: list[float]):
    """Cada consulta medida consome 2 leituras do relógio (antes/depois)."""
    values = []
    now = 0.0
    for duration in durations_ms:
        values.extend([now, now + duration / 1000])
        now += 10
    return itertools.chain(values, itertools.repeat(now)).__next__


def _install(monkeypatch, fake_query: FakeQueryRuntime, durations_ms: list[float]) -> None:
    monkeypatch.setattr(query_runtime, "connect", lambda port, database_name: fake_query)
    monkeypatch.setattr(performance, "_clock", _clock_ticks(durations_ms))


def test_ranks_measures_slowest_first_with_cold_and_warm_times(monkeypatch, fake_tom):
    fake_query = FakeQueryRuntime()
    # ordem de medição = ordem do modelo (Rapida, Lenta); por medida:
    # 1 fria + 2 quentes
    _install(monkeypatch, fake_query, [10, 4, 6, 300, 120, 100])

    result = performance.profile_measures(runs=2)

    names = [m["measure"] for m in result["measures"]]
    assert names == ["Vendas.Lenta", "Vendas.Rapida"]
    lenta = result["measures"][0]
    assert lenta["cold_ms"] == 300
    assert lenta["warm_ms"] == 110  # mediana de 120 e 100
    rapida = result["measures"][1]
    assert (rapida["cold_ms"], rapida["warm_ms"]) == (10, 5)


def test_warmup_runs_first_and_cache_is_cleared_before_each_cold_run(monkeypatch, fake_tom):
    fake_query = FakeQueryRuntime()
    _install(monkeypatch, fake_query, [1] * 20)

    performance.profile_measures(runs=1)

    kinds = [(c[0], c[1].get("dax_query") or c[1].get("database_id")) for c in fake_query.calls]
    assert kinds[0] == ("execute", _WARMUP)
    # cada medida: clear_cache -> fria -> quente
    assert [k[0] for k in kinds[1:]] == ["clear_cache", "execute", "execute"] * 2 + ["close"]
    assert kinds[1] == ("clear_cache", "Vendas")


def test_without_cold_cache_nothing_is_cleared(monkeypatch, fake_tom):
    fake_query = FakeQueryRuntime()
    _install(monkeypatch, fake_query, [1] * 20)

    result = performance.profile_measures(runs=2, cold_cache=False)

    assert not [c for c in fake_query.calls if c[0] == "clear_cache"]
    assert all(m["cold_ms"] is None for m in result["measures"])


def test_query_without_group_by_uses_row(monkeypatch, fake_tom):
    fake_query = FakeQueryRuntime()
    _install(monkeypatch, fake_query, [1] * 20)

    performance.profile_measures(measures=["Vendas.Rapida"], runs=1)

    queries = {c[1]["dax_query"] for c in fake_query.calls if c[0] == "execute"} - {_WARMUP}
    assert queries == {"EVALUATE ROW(\"Valor\", 'Vendas'[Rapida])"}


def test_group_by_uses_summarizecolumns_and_reports_rows(monkeypatch, fake_tom):
    dax = "EVALUATE SUMMARIZECOLUMNS('Vendas'[Regiao], \"Valor\", 'Vendas'[Rapida])"
    fake_query = FakeQueryRuntime(rows_by_query={dax: [{"a": 1}, {"a": 2}, {"a": 3}]})
    _install(monkeypatch, fake_query, [1] * 20)

    result = performance.profile_measures(measures=["Rapida"], group_by="Vendas.Regiao", runs=1)

    assert result["measures"][0]["rows"] == 3
    assert result["group_by"] == "Vendas.Regiao"


def test_failing_measure_is_reported_and_others_still_run(monkeypatch, fake_tom):
    bad = "EVALUATE ROW(\"Valor\", 'Vendas'[Lenta])"
    fake_query = FakeQueryRuntime(errors_by_query={bad: "divisão inválida"})
    _install(monkeypatch, fake_query, [1] * 20)

    result = performance.profile_measures(runs=1)

    by_name = {m["measure"]: m for m in result["measures"]}
    assert "divisão inválida" in by_name["Vendas.Lenta"]["error"]
    assert by_name["Vendas.Rapida"]["error"] is None
    assert result["measures"][-1]["measure"] == "Vendas.Lenta"  # com erro vai pro fim
    assert fake_query.calls[-1][0] == "close"


def test_names_with_quotes_and_brackets_are_escaped(monkeypatch, fake_tom):
    fake_tom.add_table(TableInfo(name="Dim D'Ávila", columns=(ColumnInfo(name="X", data_type="Double"),)))
    fake_tom.create_measure("Dim D'Ávila", "Margem [%]", "1", None)
    fake_query = FakeQueryRuntime()
    _install(monkeypatch, fake_query, [1] * 20)

    performance.profile_measures(measures=["Dim D'Ávila.Margem [%]"], runs=1)

    queries = {c[1]["dax_query"] for c in fake_query.calls if c[0] == "execute"} - {_WARMUP}
    assert queries == {"EVALUATE ROW(\"Valor\", 'Dim D''Ávila'[Margem [%]]])"}


def test_unknown_measure_or_column_is_rejected_before_connecting(monkeypatch, fake_tom):
    fake_query = FakeQueryRuntime()
    _install(monkeypatch, fake_query, [1] * 20)

    with pytest.raises(ModelObjectNotFoundError):
        performance.profile_measures(measures=["Vendas.NaoExiste"])
    with pytest.raises(ModelObjectNotFoundError):
        performance.profile_measures(group_by="Vendas.NaoExiste")
    assert fake_query.calls == []


@pytest.mark.parametrize("runs", [0, 11])
def test_runs_out_of_range_is_rejected(fake_tom, runs):
    with pytest.raises(InvalidProfileRequestError):
        performance.profile_measures(runs=runs)


def test_profile_is_read_only(monkeypatch, fake_tom):
    before = list(fake_tom.written_calls())
    _install(monkeypatch, FakeQueryRuntime(), [1] * 20)

    performance.profile_measures(runs=1)

    assert fake_tom.written_calls() == before


# --- dicas estáticas (guia oficial de boas práticas de DAX) -----------------------


def _codes(dax: str) -> set[str]:
    return {h["code"] for h in performance.dax_hints(dax)}


def test_hint_error_functions():
    assert "FUNCOES_DE_ERRO" in _codes("IFERROR([A] / [B], 0)")
    assert "FUNCOES_DE_ERRO" in _codes("IF(ISERROR([A]), 0, [A])")


def test_hint_filter_as_filter_argument():
    assert "FILTER_COMO_FILTRO" in _codes("CALCULATE([Vendas], FILTER('Produto', 'Produto'[Cor] = \"Red\"))")
    assert "FILTER_COMO_FILTRO" not in _codes("CALCULATE([Vendas], KEEPFILTERS('Produto'[Cor] = \"Red\"))")


def test_hint_blank_to_value():
    assert "BLANK_VIRA_VALOR" in _codes("IF(ISBLANK([Vendas]), 0, [Vendas])")
    assert "BLANK_VIRA_VALOR" in _codes("DIVIDE([Lucro], [Vendas], 0)")
    assert "BLANK_VIRA_VALOR" not in _codes("DIVIDE([Lucro], [Vendas])")


def test_hint_count_instead_of_countrows():
    assert "COUNT_EM_VEZ_DE_COUNTROWS" in _codes("COUNT(Vendas[Pedido])")
    assert "COUNT_EM_VEZ_DE_COUNTROWS" not in _codes("COUNTROWS(Vendas) + COUNTA(Vendas[X]) + COUNTX(Vendas, 1)")


def test_hint_repeated_expression_without_variable():
    repeated = (
        "DIVIDE([Vendas] - CALCULATE([Vendas], SAMEPERIODLASTYEAR('Data'[Data])), "
        "CALCULATE([Vendas], SAMEPERIODLASTYEAR('Data'[Data])))"
    )
    assert "EXPRESSAO_REPETIDA" in _codes(repeated)
    with_var = "VAR PY = CALCULATE([Vendas], SAMEPERIODLASTYEAR('Data'[Data])) RETURN DIVIDE([Vendas] - PY, PY)"
    assert "EXPRESSAO_REPETIDA" not in _codes(with_var)


def test_hints_ignore_text_inside_strings_and_comments():
    assert _codes('"IFERROR( não é código" -- COUNT(x)\n+ SUM(T[C])') == set()


def test_clean_measure_has_no_hints():
    assert performance.dax_hints("SUM(Vendas[Valor])") == []


def test_every_hint_cites_the_official_doc():
    dax = "IFERROR(COUNT(T[C]), 0) + CALCULATE([M], FILTER(T, T[C] = 1)) + IF(ISBLANK([M]), 0, [M])"
    for hint in performance.dax_hints(dax):
        assert hint["doc"].startswith("https://learn.microsoft.com/")
        assert hint["message"]
