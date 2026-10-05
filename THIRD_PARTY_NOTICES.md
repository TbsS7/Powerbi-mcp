# Third-party notices / Avisos de terceiros

This repository vendors JSON schemas published by Microsoft, used only by the
test suite to validate the PBIR files the server writes (offline, no network).
They are redistributed unmodified under the MIT License reproduced below.

Este repositório inclui cópias de schemas JSON publicados pela Microsoft,
usados só pela suíte de testes para validar os arquivos PBIR que o servidor
grava. São redistribuídos sem modificação, sob a licença MIT abaixo.

| Files / Arquivos | Source / Origem |
|---|---|
| `tests/schemas/*.json` (except `reportThemeSchema.2.157.json`) | https://github.com/microsoft/json-schemas (`fabric/item/report/definition`) |
| `tests/schemas/reportThemeSchema.2.157.json` | https://github.com/microsoft/powerbi-desktop-samples (`Report Theme JSON Schema`) |

The Microsoft .NET libraries used at runtime (TOM / ADOMD.NET) are **not**
included; see README, "Licenciamento e obtenção do TOM e do ADOMD.NET".

The PBIR authoring documentation consulted during development
(https://github.com/microsoft/skills-for-fabric, MIT) is referenced, not
copied, in this repository.

---

MIT License

Copyright (c) Microsoft Corporation. All rights reserved.

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE
