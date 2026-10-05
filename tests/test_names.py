"""Testes de visuals.names: validação de page_name antes de virar
componente de caminho de arquivo.

Bloqueia path traversal (.., /, \\), caracteres especiais e nomes
reservados do Windows -- ver errors.InvalidPageNameError.
"""

from __future__ import annotations

import pytest

from errors import InvalidPageNameError
from visuals.names import validate_page_name


@pytest.mark.parametrize(
    "page_name",
    ["Pagina1", "Visao_Geral", "visao-geral-2024", "A", "a1_b2-c3"],
)
def test_accepts_valid_names(page_name: str):
    validate_page_name(page_name)  # não deve levantar


@pytest.mark.parametrize(
    "page_name",
    [
        "../../../etc/passwd",
        "..\\..\\Windows\\System32",
        "..",
        ".",
        "pages/../../outra",
        "/etc/passwd",
        "C:\\Windows\\System32",
        "pagina 1",  # espaço não é permitido (use display_name)
        "página",  # acento não é permitido
        "pagina.json",
        "pagina:alternate",
        "",
        "a" * 101,  # excede o limite de tamanho
    ],
)
def test_rejects_unsafe_or_invalid_names(page_name: str):
    with pytest.raises(InvalidPageNameError):
        validate_page_name(page_name)


@pytest.mark.parametrize("reserved", ["CON", "con", "PRN", "AUX", "NUL", "COM1", "LPT1"])
def test_rejects_reserved_windows_device_names(reserved: str):
    with pytest.raises(InvalidPageNameError):
        validate_page_name(reserved)
