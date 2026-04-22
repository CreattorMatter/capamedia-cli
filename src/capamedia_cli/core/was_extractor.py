"""Extrae configuracion crítica de los WAS legacy (IBM WebSphere).

Los WAS del banco tienen 5 valores que la AI debe **preservar EXACTO** en el
migrado, o rompe clientes:

1. `virtual-host` de `ibm-web-bnd.xml` — ej `VHClientes`, `VHTecnicos`, `default_host`
2. `context-root` de `ibm-web-ext.xml` — ej `WSClientes0010`
3. `url-pattern` de `web.xml` servlet-mapping — ej `/soap/WSClientes0010Request`
4. `servlet-class` de `web.xml` — el entry point SOAP
5. `security-constraint` de `web.xml` — HTTP methods permitidos (POST-only tipico)

Todo WAS del batch-24 tiene los 3 archivos. El extractor es confiable.

Uso:
    from capamedia_cli.core.was_extractor import extract_was_config
    cfg = extract_was_config(legacy_root)
    if cfg:
        print(cfg.virtual_host, cfg.context_root, cfg.url_patterns)
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class WasConfig:
    """Configuracion WAS critica extraida del legacy."""

    virtual_host: str | None = None           # ibm-web-bnd.xml
    context_root: str | None = None           # ibm-web-ext.xml
    url_patterns: list[str] = field(default_factory=list)          # web.xml servlet-mapping
    servlet_classes: list[str] = field(default_factory=list)       # web.xml servlet-class
    security_constraints: list[dict] = field(default_factory=list) # web.xml security-constraint
    reload_interval: int | None = None        # ibm-web-ext.xml
    source_files: list[str] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return (
            self.virtual_host is None
            and self.context_root is None
            and not self.url_patterns
            and not self.security_constraints
        )

    def needs_human_review(self) -> list[str]:
        """Devuelve warnings para el reviewer humano."""
        warnings: list[str] = []
        if self.virtual_host and self.virtual_host != "default_host":
            warnings.append(
                f"WAS usa virtual-host '{self.virtual_host}' - al migrar a "
                f"OpenShift asegurar que el Route tenga el host correcto."
            )
        if self.context_root:
            warnings.append(
                f"WAS usa context-root='{self.context_root}' - en Spring Boot "
                f"setear `server.servlet.context-path=/{self.context_root}` o "
                f"equivalente."
            )
        for up in self.url_patterns:
            if up and up != "/":
                warnings.append(
                    f"WAS usa URL pattern '{up}' - preservarlo en @PostMapping / "
                    f"@RequestMapping o romperemos clientes existentes."
                )
        has_deny = any(
            "TRACE" in str(sc.get("http_methods", []))
            for sc in self.security_constraints
        )
        if has_deny:
            warnings.append(
                "WAS tiene security-constraint denegando TRACE/PUT/OPTIONS/DELETE/GET "
                "- replicar con filter o @RequestMapping(method=POST) explicito."
            )
        return warnings


# ─────────────────────────────────────────────────────────────────────────────
# Parsers
# ─────────────────────────────────────────────────────────────────────────────

_XMLNS_IBM = "{http://websphere.ibm.com/xml/ns/javaee}"
_XMLNS_JAVAEE = "{http://java.sun.com/xml/ns/javaee}"


def _strip_ns(tag: str) -> str:
    """Quita el namespace de un tag XML."""
    return tag.split("}", 1)[1] if "}" in tag else tag


def _parse_ibm_web_bnd(path: Path) -> tuple[str | None]:
    """Extrae `virtual-host name=` de ibm-web-bnd.xml."""
    try:
        txt = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return (None,)
    m = re.search(r'<virtual-host\s+name="([^"]+)"', txt)
    return (m.group(1) if m else None,)


def _parse_ibm_web_ext(path: Path) -> tuple[str | None, int | None]:
    """Extrae context-root y reload-interval de ibm-web-ext.xml."""
    try:
        txt = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return (None, None)
    m_ctx = re.search(r'<context-root\s+uri="([^"]+)"', txt)
    m_rel = re.search(r'<reload-interval\s+value="(\d+)"', txt)
    return (
        m_ctx.group(1) if m_ctx else None,
        int(m_rel.group(1)) if m_rel else None,
    )


def _parse_web_xml(path: Path) -> tuple[list[str], list[str], list[dict]]:
    """Extrae url-patterns, servlet-classes y security-constraints de web.xml."""
    url_patterns: list[str] = []
    servlet_classes: list[str] = []
    constraints: list[dict] = []
    try:
        txt = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return url_patterns, servlet_classes, constraints

    # url-patterns
    for m in re.finditer(r'<url-pattern>([^<]+)</url-pattern>', txt):
        url_patterns.append(m.group(1).strip())
    # servlet-classes
    for m in re.finditer(r'<servlet-class>([^<]+)</servlet-class>', txt):
        servlet_classes.append(m.group(1).strip())
    # security-constraints (bloques completos)
    for m in re.finditer(
        r'<security-constraint>(.*?)</security-constraint>',
        txt, re.DOTALL
    ):
        block = m.group(1)
        sc_urls = re.findall(r'<url-pattern>([^<]+)</url-pattern>', block)
        sc_methods = re.findall(r'<http-method>([^<]+)</http-method>', block)
        sc_roles = re.findall(r'<role-name>([^<]+)</role-name>', block)
        sc_transport = re.findall(r'<transport-guarantee>([^<]+)</transport-guarantee>', block)
        constraints.append({
            "url_patterns": sc_urls,
            "http_methods": sc_methods,
            "roles": sc_roles,
            "transport": sc_transport[0] if sc_transport else None,
        })
    return url_patterns, servlet_classes, constraints


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

def extract_was_config(legacy_root: Path) -> WasConfig:
    """Busca ibm-web-bnd.xml + ibm-web-ext.xml + web.xml bajo `legacy_root` y
    devuelve `WasConfig` con los 5 valores criticos. Si no es WAS, retorna
    `WasConfig()` vacio (is_empty=True).
    """
    cfg = WasConfig()

    # Prefer el primer WEB-INF que encontremos (evitar target/ ya buildeados)
    def _find(pattern: str) -> Path | None:
        matches = [
            p for p in legacy_root.rglob(pattern)
            if "target" not in p.parts  # ignora builds
        ]
        return matches[0] if matches else None

    bnd_path = _find("ibm-web-bnd.xml")
    ext_path = _find("ibm-web-ext.xml")
    web_path = _find("web.xml")

    if bnd_path:
        (cfg.virtual_host,) = _parse_ibm_web_bnd(bnd_path)
        cfg.source_files.append(str(bnd_path.relative_to(legacy_root)))

    if ext_path:
        cfg.context_root, cfg.reload_interval = _parse_ibm_web_ext(ext_path)
        cfg.source_files.append(str(ext_path.relative_to(legacy_root)))

    if web_path:
        ups, svcs, scs = _parse_web_xml(web_path)
        cfg.url_patterns = ups
        cfg.servlet_classes = svcs
        cfg.security_constraints = scs
        cfg.source_files.append(str(web_path.relative_to(legacy_root)))

    return cfg


def render_was_config_markdown(cfg: WasConfig, service_name: str) -> str:
    """Renderiza la config WAS para incluir en COMPLEXITY o DOSSIER."""
    if cfg.is_empty:
        return ""
    lines: list[str] = []
    lines.append(f"## WAS config extraida ({service_name})")
    lines.append("")
    lines.append(
        "_Valores crítiticos que la AI DEBE preservar al migrar a Spring Boot. "
        "Ignorarlos rompe clientes existentes._"
    )
    lines.append("")
    lines.append(f"- **virtual-host:** `{cfg.virtual_host or '(no definido)'}`")
    lines.append(f"- **context-root:** `{cfg.context_root or '(no definido)'}`")
    if cfg.reload_interval is not None:
        lines.append(f"- **reload-interval:** `{cfg.reload_interval}s` (solo WAS, N/A en Spring Boot)")
    lines.append("")
    if cfg.url_patterns:
        lines.append("### URL patterns (servlet-mapping)")
        for up in cfg.url_patterns:
            lines.append(f"- `{up}`")
        lines.append("")
    if cfg.servlet_classes:
        lines.append("### Servlet classes (entry points)")
        for sc in cfg.servlet_classes:
            lines.append(f"- `{sc}`")
        lines.append("")
    if cfg.security_constraints:
        lines.append("### Security constraints")
        for sc in cfg.security_constraints:
            urls = ", ".join(sc.get("url_patterns", []))
            methods = ", ".join(sc.get("http_methods", [])) or "(todos)"
            roles = ", ".join(sc.get("roles", [])) or "(sin rol)"
            transport = sc.get("transport") or "(any)"
            lines.append(
                f"- URL=`{urls}` HTTP=`{methods}` ROLE=`{roles}` TRANSPORT=`{transport}`"
            )
        lines.append("")
    warnings = cfg.needs_human_review()
    if warnings:
        lines.append("### Warnings para el reviewer humano")
        for w in warnings:
            lines.append(f"- {w}")
        lines.append("")
    lines.append("### Archivos fuente")
    for f in cfg.source_files:
        lines.append(f"- `{f}`")
    lines.append("")
    return "\n".join(lines)


def render_was_config_prompt_appendix(cfg: WasConfig, service_name: str) -> str:
    """Version compacta para inyectar al FABRICS_PROMPT / batch migrate prompt."""
    if cfg.is_empty:
        return ""
    lines: list[str] = []
    lines.append("")
    lines.append(f"## WAS config (EXACTA — no inventar)")
    lines.append("")
    lines.append(
        "Estos 5 valores salen del legacy WAS y DEBEN preservarse EXACTOS en el "
        "migrado. Cualquier cambio rompe clientes existentes."
    )
    lines.append("")
    if cfg.virtual_host:
        lines.append(f"- **virtual-host**: `{cfg.virtual_host}` → en OpenShift Route, setear `host:`")
    if cfg.context_root:
        lines.append(
            f"- **context-root**: `{cfg.context_root}` → en Spring Boot setear "
            f"`server.servlet.context-path=/{cfg.context_root}`"
        )
    for up in cfg.url_patterns:
        lines.append(f"- **url-pattern**: `{up}` → `@PostMapping(\"{up}\")` o equivalente")
    for sc in cfg.security_constraints:
        methods = sc.get("http_methods", [])
        if methods:
            lines.append(
                f"- **security-constraint**: deny `{', '.join(methods)}` "
                f"para URL `{', '.join(sc.get('url_patterns', []))}` → "
                f"filter o `@RequestMapping(method=POST)` explicito"
            )
    lines.append("")
    lines.append(
        "**Regla dura**: si migrás este WAS y cambiás cualquiera de estos valores, "
        "el PR se rechaza. Los URLs son contrato con clientes en producción."
    )
    lines.append("")
    return "\n".join(lines)
