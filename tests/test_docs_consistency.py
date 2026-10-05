"""Guarda contra documentação desatualizada: a tabela "Ferramentas
disponíveis" do README precisa listar toda tool registrada em server.py.

Motivo (limpeza da Fase 3, 2026-09-24): a tabela tinha deixado de fora
10 das 67 tools, e o docstring de server.py dizia "47 ferramentas" -- a
contagem manual sempre desatualiza. Este teste quebra no momento em que
alguém registra uma tool nova sem documentar.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _registered_tools() -> list[str]:
    server = (ROOT / "server.py").read_text(encoding="utf-8")
    return re.findall(r"@mcp\.tool\(\)[\s\S]*?\ndef (\w+)\(", server)


def _readme_tool_table_names() -> set[str]:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    section = readme.split("## Ferramentas disponíveis", 1)[1].split("\n## ", 1)[0]
    rows = [line for line in section.splitlines() if line.startswith("| ")]
    return {name for row in rows for name in re.findall(r"`(\w+)`", row)}


def test_found_registered_tools():
    # sanidade do próprio regex: se isto cair pra zero, o teste abaixo
    # passaria sem checar nada
    assert len(_registered_tools()) > 50


def test_readme_table_lists_every_registered_tool():
    missing = [t for t in _registered_tools() if t not in _readme_tool_table_names()]
    assert missing == [], f"Tools registradas fora da tabela do README: {missing}"


def test_capacidades_lists_every_registered_tool():
    capacidades = (ROOT / "CAPACIDADES.md").read_text(encoding="utf-8")
    listed = set(re.findall(r"`(\w+)`", capacidades))
    missing = [t for t in _registered_tools() if t not in listed]
    assert missing == [], f"Tools registradas fora do CAPACIDADES.md: {missing}"


def test_capacidades_tool_count_matches():
    capacidades = (ROOT / "CAPACIDADES.md").read_text(encoding="utf-8")
    match = re.search(r"\*\*(\d+) ferramentas\*\*", capacidades)
    assert match, "CAPACIDADES.md precisa declarar '**N ferramentas**'"
    assert int(match.group(1)) == len(_registered_tools())
