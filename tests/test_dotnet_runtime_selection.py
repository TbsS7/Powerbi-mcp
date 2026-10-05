"""Testes de modeling.tom_runtime._dotnet_runtime_name: qual runtime
.NET o pythonnet deve carregar antes do primeiro `import clr`.

Achado testando contra um Power BI Desktop real: pythonnet carrega
.NET Framework por padrão no Windows, mas as DLLs do TOM que este
projeto usa (baixadas via scripts/setup_tom.py) são a variante
NetCore -- carregar um assembly .NET Core dentro do .NET Framework
produz TypeLoadException em assemblies de fachada como
System.ComponentModel.Primitives. `pythonnet.load("coreclr")` antes do
`import clr` resolve -- confirmado com uma conexão real.
"""

from __future__ import annotations

from modeling.tom_runtime import _dotnet_runtime_name


def test_defaults_to_coreclr_matching_the_downloaded_netcore_dlls(monkeypatch):
    monkeypatch.delenv("PYTHONNET_RUNTIME", raising=False)
    assert _dotnet_runtime_name() == "coreclr"


def test_respects_pythonnet_runtime_env_var_override(monkeypatch):
    monkeypatch.setenv("PYTHONNET_RUNTIME", "netfx")
    assert _dotnet_runtime_name() == "netfx"
