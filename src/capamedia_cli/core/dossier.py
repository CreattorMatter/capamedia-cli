"""Deep-scan: recolecta evidencia de un servicio en Azure DevOps y arma
`DOSSIER_<svc>.md` + resumen inyectable al FABRICS_PROMPT.

Objetivo: cero alucinaciones. Si el servicio referencia un ConfigMap/Helm/
variable en produccion, queremos el valor real, no uno inventado por la AI.

Query set por servicio (minimo viable):
1. Nombre del servicio literal -> ConfigMaps, Helm values, application.yml
2. WSDL namespace -> clients que importan al servicio (reverse deps)
3. TX codes conocidos del servicio -> referencias cruzadas en otros repos
4. UMPs del servicio -> orquestadores consumidores
5. Variables CE_* / CCC_* relacionadas -> valores reales de config
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from .azure_search import (
    ALL_PROJECTS,
    AzureCodeSearch,
    AzureSearchError,
    SearchHit,
)


@dataclass
class DossierSection:
    """Una seccion del dossier: un grupo de hits bajo un titulo."""

    title: str
    query: str
    hits: list[SearchHit] = field(default_factory=list)
    warning: str | None = None  # si no se pudo buscar (auth, red, etc.)


@dataclass
class Dossier:
    """Dossier completo de un servicio."""

    service: str
    sections: list[DossierSection] = field(default_factory=list)
    ce_vars: set[str] = field(default_factory=set)
    ccc_vars: set[str] = field(default_factory=set)

    @property
    def total_hits(self) -> int:
        return sum(len(s.hits) for s in self.sections)

    @property
    def has_any_evidence(self) -> bool:
        return self.total_hits > 0 or bool(self.ce_vars or self.ccc_vars)


CE_VAR_PATTERN = re.compile(r"\bCE_[A-Z0-9_]+\b")
CCC_VAR_PATTERN = re.compile(r"\bCCC_[A-Z0-9_]+\b")


def build_dossier(
    service: str,
    client: AzureCodeSearch,
    *,
    wsdl_namespace: str | None = None,
    tx_codes: list[str] | None = None,
    umps: list[str] | None = None,
    projects: list[str] | None = None,
    per_query_limit: int = 30,
) -> Dossier:
    """Arma un dossier ejecutando las queries contra Azure Code Search.

    `projects` default = los 4 conocidos. Pasar un subset para acelerar.
    """
    if projects is None:
        projects = list(ALL_PROJECTS)

    dossier = Dossier(service=service)

    def _run(title: str, query: str) -> DossierSection:
        section = DossierSection(title=title, query=query)
        try:
            resp = client.search(query, projects=projects, top=per_query_limit)
            section.hits = resp.hits
        except AzureSearchError as exc:
            section.warning = f"busqueda fallo: {exc}"
        # Extraer CE_* / CCC_* del contenido de los matches
        for hit in section.hits:
            for snippet in hit.matches:
                dossier.ce_vars.update(CE_VAR_PATTERN.findall(snippet))
                dossier.ccc_vars.update(CCC_VAR_PATTERN.findall(snippet))
        return section

    # 1. Nombre literal del servicio (ConfigMaps, Helm, application.yml)
    dossier.sections.append(
        _run(
            f"Referencias al servicio `{service}` en todos los proyectos",
            service,
        )
    )

    # 2. WSDL namespace (reverse deps: quien importa este servicio)
    if wsdl_namespace:
        dossier.sections.append(
            _run(
                f"Otros clients que importan namespace `{wsdl_namespace}`",
                wsdl_namespace,
            )
        )

    # 3. TX codes del servicio (referencias cruzadas)
    if tx_codes:
        for tx in tx_codes[:10]:  # cap razonable
            dossier.sections.append(
                _run(f"TX {tx} (cross-references)", tx)
            )

    # 4. UMPs del servicio (orquestadores consumidores)
    if umps:
        for ump in umps[:10]:
            dossier.sections.append(
                _run(f"UMP {ump} referenciada por otros servicios", ump)
            )

    return dossier


# ---------------------------------------------------------------------------
# Render
# ---------------------------------------------------------------------------


def render_dossier_markdown(dossier: Dossier) -> str:
    """Renderiza el dossier completo como markdown para `DOSSIER_<svc>.md`."""
    lines: list[str] = []
    lines.append(f"# Dossier deep-scan — `{dossier.service}`")
    lines.append("")
    lines.append(
        "_Generado por `capamedia clone --deep-scan`. Usa Azure DevOps Code "
        "Search para recolectar evidencia real que la AI necesita para migrar "
        "sin alucinar valores._"
    )
    lines.append("")
    lines.append("## Resumen")
    lines.append("")
    lines.append(f"- **Total hits:** {dossier.total_hits}")
    lines.append(f"- **CE_* vars detectadas:** {len(dossier.ce_vars)}")
    lines.append(f"- **CCC_* vars detectadas:** {len(dossier.ccc_vars)}")
    lines.append("")

    if dossier.ce_vars:
        lines.append("### Variables CE_* detectadas")
        for v in sorted(dossier.ce_vars):
            lines.append(f"- `{v}`")
        lines.append("")

    if dossier.ccc_vars:
        lines.append("### Variables CCC_* detectadas")
        for v in sorted(dossier.ccc_vars):
            lines.append(f"- `{v}`")
        lines.append("")

    for section in dossier.sections:
        lines.append(f"## {section.title}")
        lines.append("")
        lines.append(f"_Query: `{section.query}`_")
        lines.append("")
        if section.warning:
            lines.append(f"> ⚠ {section.warning}")
            lines.append("")
            continue
        if not section.hits:
            lines.append("_Sin hits._")
            lines.append("")
            continue
        lines.append("| Proyecto | Repo | Archivo | Branch | Snippet |")
        lines.append("|---|---|---|---|---|")
        for hit in section.hits[:30]:
            snippet = (hit.matches[0] if hit.matches else "").replace("|", "\\|")[:120]
            lines.append(
                f"| {hit.project} | {hit.repo} | `{hit.file_path}` | "
                f"{hit.branch} | `{snippet}` |"
            )
        if len(section.hits) > 30:
            lines.append(f"| ... | ... | ... | ... | {len(section.hits) - 30} mas |")
        lines.append("")

    return "\n".join(lines)


def render_dossier_prompt_appendix(dossier: Dossier) -> str:
    """Version compacta para inyectar al FABRICS_PROMPT. Cap razonable en tamano."""
    if not dossier.has_any_evidence:
        return (
            "\n\n## Deep-scan: sin evidencia externa\n\n"
            f"_El deep-scan de Azure DevOps no encontro configuracion externa "
            f"para `{dossier.service}`. La AI debe reportar "
            f"NEEDS_HUMAN_CONFIG si detecta referencias a ConfigMaps, "
            f"Helm values o variables que no esten en el legacy._\n"
        )

    lines: list[str] = []
    lines.append("")
    lines.append("## Deep-scan: evidencia externa real (NO alucinar)")
    lines.append("")
    lines.append(
        "_El deep-scan recolecto la siguiente evidencia de Azure DevOps. "
        "Esta es la fuente de verdad para valores de config/variables. "
        "No inventes valores que existan aqui._"
    )
    lines.append("")

    if dossier.ce_vars:
        lines.append("### Variables CE_* del servicio")
        for v in sorted(dossier.ce_vars)[:30]:
            lines.append(f"- `{v}`")
        lines.append("")

    if dossier.ccc_vars:
        lines.append("### Variables CCC_* del servicio")
        for v in sorted(dossier.ccc_vars)[:30]:
            lines.append(f"- `{v}`")
        lines.append("")

    lines.append("### Repos que referencian al servicio (top)")
    repos_seen: set[str] = set()
    for section in dossier.sections:
        for hit in section.hits:
            key = f"{hit.project}/{hit.repo}"
            if key not in repos_seen:
                repos_seen.add(key)
                lines.append(
                    f"- `{key}` en `{hit.file_path}` "
                    f"({len(hit.matches)} match)"
                )
            if len(repos_seen) >= 20:
                break
        if len(repos_seen) >= 20:
            break
    lines.append("")

    lines.append(
        "**Regla**: si migras este servicio y ves referencias a ConfigMaps/"
        "variables que NO estan en la lista de arriba pero SI en el legacy, "
        "REPORTA `NEEDS_HUMAN_CONFIG` en el output estructurado — no "
        "inventes el valor."
    )
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Integration helpers
# ---------------------------------------------------------------------------


def write_dossier(
    workspace: Path,
    dossier: Dossier,
) -> Path:
    """Escribe `DOSSIER_<svc>.md` en el workspace."""
    target = workspace / f"DOSSIER_{dossier.service}.md"
    target.write_text(render_dossier_markdown(dossier), encoding="utf-8")
    return target
