#!/usr/bin/env python3
"""Baixa e instala localmente as DLLs cliente do Tabular Object Model
(TOM) e do ADOMD.NET, necessárias para as camadas de modelagem
(connect_to_desktop, create_table, create_measure, create_relationship)
e de consulta (evaluate_dax).

Uso:
    python scripts/setup_tom.py

Baixa os pacotes NuGet oficiais `Microsoft.AnalysisServices.NetCore.retail.amd64`
(TOM: estrutura do modelo) e
`Microsoft.AnalysisServices.AdomdClient.NetCore.retail.amd64` (ADOMD.NET:
execução de consultas DAX/MDX) direto do nuget.org, confere o SHA-512 de
cada um contra o valor publicado pela Microsoft (protege contra um
arquivo adulterado/substituído no meio do caminho), extrai as DLLs
`netcoreapp3.0` de ambos para `.tom-dlls/dlls/` na raiz do projeto (a
mesma pasta -- nenhum nome de arquivo colide entre os dois pacotes), e
valida chamando modeling.tom_runtime.resolve_tom_dll_dir() e
modeling.query_runtime.resolve_adomd_dll_dir().

`.tom-dlls/` está no .gitignore -- essas DLLs são da Microsoft, sob
licença própria (ver README, seção "Licenciamento e obtenção do TOM"),
e não devem ir para o repositório.

A variante NetCore foi escolhida deliberadamente para os dois pacotes:
modeling/tom_runtime.py carrega o runtime .NET via
`pythonnet.load("coreclr")` (configurável por PYTHONNET_RUNTIME) para
casar com ela -- ver a docstring de _dotnet_runtime_name nesse arquivo
para o porquê. modeling/query_runtime.py reaproveita a mesma escolha.
"""

from __future__ import annotations

import base64
import hashlib
import shutil
import sys
import tempfile
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class _Package:
    name: str
    version: str
    # Publicado pela própria Microsoft no header x-ms-meta-SHA512 do
    # blob no nuget.org (conferido em setembro de 2026). Se a versão do
    # pacote for atualizada, atualize este valor junto -- é o que torna
    # a verificação abaixo significativa.
    expected_sha512_b64: str

    @property
    def url(self) -> str:
        return (
            f"https://api.nuget.org/v3-flatcontainer/{self.name}/{self.version}/"
            f"{self.name}.{self.version}.nupkg"
        )


PACKAGES: tuple[_Package, ...] = (
    _Package(
        name="microsoft.analysisservices.netcore.retail.amd64",
        version="19.84.1",
        expected_sha512_b64=(
            "wW9L0RrISTA5P0pWKfB3oLNS0XBfxt632Beo9w1RpN+YflivMUasrT8imTiTcdL3FuIS4bOXtY+m7wdlwVRdOw=="
        ),
    ),
    _Package(
        name="microsoft.analysisservices.adomdclient.netcore.retail.amd64",
        version="19.84.1",
        expected_sha512_b64=(
            "LzsjUBZyZ6EzMoy9z350YAqYtxL06yQo8ltI3Np9d+PTTtAYtVw6qKjeWBNXgWFDOkuheRJ1LxHlh0MqsPAQpw=="
        ),
    ),
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEST_DIR = PROJECT_ROOT / ".tom-dlls" / "dlls"
LIB_SUBPATH = ("lib", "netcoreapp3.0")


def verify_sha512(data: bytes, expected_base64: str) -> bool:
    """Confere `data` contra um digest SHA-512 em base64. Função pura,
    sem I/O -- é a parte deste script que vale a pena poder testar
    isoladamente."""
    digest_b64 = base64.b64encode(hashlib.sha512(data).digest()).decode("ascii")
    return digest_b64 == expected_base64


def _install_package(package: _Package) -> int:
    print(f"Baixando {package.name} {package.version} de {package.url}...")
    with tempfile.TemporaryDirectory(prefix="powerbi_mcp_setup_tom_") as tmp:
        tmp_path = Path(tmp)
        nupkg_path = tmp_path / "package.nupkg"
        try:
            urllib.request.urlretrieve(package.url, nupkg_path)  # noqa: S310
        except OSError as exc:
            print(f"ERRO ao baixar o pacote: {exc}")
            return 1

        data = nupkg_path.read_bytes()
        if not verify_sha512(data, package.expected_sha512_b64):
            got = base64.b64encode(hashlib.sha512(data).digest()).decode("ascii")
            print(
                "ERRO: o SHA-512 do arquivo baixado não bate com o "
                "publicado pela Microsoft para esta versão.\n"
                f"  esperado: {package.expected_sha512_b64}\n"
                f"  obtido:   {got}\n"
                "Abortando -- não instalando um arquivo que não pôde ser "
                "verificado."
            )
            return 1
        print("SHA-512 confirmado contra o publicado pela Microsoft.")

        extract_dir = tmp_path / "extracted"
        with zipfile.ZipFile(nupkg_path) as zf:
            zf.extractall(extract_dir)  # noqa: S202 -- conteúdo já verificado por hash acima

        lib_dir = extract_dir.joinpath(*LIB_SUBPATH)
        if not lib_dir.is_dir():
            print(f"ERRO: pasta esperada não encontrada dentro do pacote: {lib_dir}")
            return 1

        DEST_DIR.mkdir(parents=True, exist_ok=True)
        dlls = sorted(lib_dir.glob("*.dll"))
        copied = 0
        for dll in dlls:
            dest = DEST_DIR / dll.name
            if dest.is_file():
                # Alguns arquivos são dependências compartilhadas entre
                # o pacote do TOM e o do ADOMD.NET (ex.:
                # Microsoft.AnalysisServices.Runtime.*.dll). Se já
                # existem (de uma instalação anterior, já verificada por
                # hash) e algum processo os tem carregados agora --
                # Power BI Desktop, tipicamente --, sobrescrever falha
                # com PermissionError no Windows. Manter o que já está
                # lá é seguro: o conteúdo já foi confirmado por hash na
                # instalação que o colocou ali.
                continue
            shutil.copy2(dll, dest)
            copied += 1
        print(f"{copied} DLL(s) nova(s) copiada(s) para {DEST_DIR} ({len(dlls)} no pacote)")
    return 0


def main() -> int:
    for package in PACKAGES:
        status = _install_package(package)
        if status != 0:
            return status

    sys.path.insert(0, str(PROJECT_ROOT))
    print("Validando resolução (modeling.tom_runtime.resolve_tom_dll_dir)...")
    from modeling.tom_runtime import resolve_tom_dll_dir  # noqa: E402

    try:
        resolved_tom = resolve_tom_dll_dir()
    except Exception as exc:  # noqa: BLE001 -- queremos reportar qualquer falha de forma clara aqui
        print(f"ERRO: DLLs copiadas, mas resolve_tom_dll_dir() ainda falhou: {exc}")
        return 1
    print(f"OK -- resolve_tom_dll_dir() encontrou: {resolved_tom}")

    print("Validando resolução (modeling.query_runtime.resolve_adomd_dll_dir)...")
    from modeling.query_runtime import resolve_adomd_dll_dir  # noqa: E402

    try:
        resolved_adomd = resolve_adomd_dll_dir()
    except Exception as exc:  # noqa: BLE001
        print(f"ERRO: DLLs copiadas, mas resolve_adomd_dll_dir() ainda falhou: {exc}")
        return 1
    print(f"OK -- resolve_adomd_dll_dir() encontrou: {resolved_adomd}")

    print(
        "\nPronto. connect_to_desktop, evaluate_dax e as demais tools de "
        "modelagem já devem funcionar sem precisar definir TOM_DLL_PATH ou "
        "ADOMD_DLL_PATH manualmente."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
