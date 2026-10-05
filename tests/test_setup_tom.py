"""Teste de scripts.setup_tom.verify_sha512 -- a única lógica pura do
script de setup das DLLs do TOM (o resto é I/O: download, extração,
cópia de arquivo)."""

from __future__ import annotations

import base64
import hashlib

from scripts.setup_tom import verify_sha512


def test_accepts_matching_digest():
    data = b"conteudo de exemplo"
    digest_b64 = base64.b64encode(hashlib.sha512(data).digest()).decode("ascii")
    assert verify_sha512(data, digest_b64) is True


def test_rejects_mismatched_digest():
    data = b"conteudo de exemplo"
    wrong_digest_b64 = base64.b64encode(hashlib.sha512(b"outro conteudo").digest()).decode("ascii")
    assert verify_sha512(data, wrong_digest_b64) is False


def test_rejects_tampered_data():
    original = b"conteudo original"
    digest_b64 = base64.b64encode(hashlib.sha512(original).digest()).decode("ascii")
    tampered = b"conteudo alterado"
    assert verify_sha512(tampered, digest_b64) is False
