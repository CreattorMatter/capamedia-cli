"""Tests para core/was_extractor.py."""

from __future__ import annotations

from pathlib import Path

from capamedia_cli.core.was_extractor import (
    WasConfig,
    extract_was_config,
    render_was_config_markdown,
    render_was_config_prompt_appendix,
)


IBM_WEB_BND = """<?xml version="1.0" encoding="UTF-8"?>
<web-bnd xmlns="http://websphere.ibm.com/xml/ns/javaee">
    <virtual-host name="VHClientes" />
</web-bnd>
"""

IBM_WEB_EXT = """<?xml version="1.0" encoding="UTF-8"?>
<web-ext xmlns="http://websphere.ibm.com/xml/ns/javaee">
    <reload-interval value="3"/>
    <context-root uri="WSClientes0010" />
    <enable-directory-browsing value="false"/>
</web-ext>
"""

WEB_XML = """<?xml version="1.0" encoding="UTF-8"?>
<web-app version="3.0" xmlns="http://java.sun.com/xml/ns/javaee">
    <servlet>
        <servlet-name>WSClientes0010Request</servlet-name>
        <servlet-class>com.pichincha.clientes.wsclientes0010.soap.WSClientes0010</servlet-class>
    </servlet>
    <servlet-mapping>
        <servlet-name>WSClientes0010Request</servlet-name>
        <url-pattern>/soap/WSClientes0010Request</url-pattern>
    </servlet-mapping>
    <security-constraint>
        <web-resource-collection>
            <web-resource-name>restrict</web-resource-name>
            <url-pattern>/*</url-pattern>
            <http-method>TRACE</http-method>
            <http-method>PUT</http-method>
            <http-method>OPTIONS</http-method>
            <http-method>DELETE</http-method>
            <http-method>GET</http-method>
        </web-resource-collection>
        <auth-constraint/>
    </security-constraint>
</web-app>
"""


def _make_was_legacy(tmp_path: Path) -> Path:
    webinf = tmp_path / "src" / "main" / "webapp" / "WEB-INF"
    webinf.mkdir(parents=True)
    (webinf / "ibm-web-bnd.xml").write_text(IBM_WEB_BND, encoding="utf-8")
    (webinf / "ibm-web-ext.xml").write_text(IBM_WEB_EXT, encoding="utf-8")
    (webinf / "web.xml").write_text(WEB_XML, encoding="utf-8")
    return tmp_path


def test_extract_was_config_happy_path(tmp_path: Path) -> None:
    legacy = _make_was_legacy(tmp_path)
    cfg = extract_was_config(legacy)

    assert cfg.virtual_host == "VHClientes"
    assert cfg.context_root == "WSClientes0010"
    assert cfg.reload_interval == 3
    assert cfg.url_patterns == ["/soap/WSClientes0010Request", "/*"]
    assert cfg.servlet_classes == [
        "com.pichincha.clientes.wsclientes0010.soap.WSClientes0010"
    ]
    assert len(cfg.security_constraints) == 1
    sc = cfg.security_constraints[0]
    assert "TRACE" in sc["http_methods"]
    assert "/*" in sc["url_patterns"]
    assert not cfg.is_empty


def test_extract_was_config_empty_when_no_was(tmp_path: Path) -> None:
    (tmp_path / "some_file.txt").write_text("not a WAS", encoding="utf-8")
    cfg = extract_was_config(tmp_path)
    assert cfg.is_empty is True
    assert cfg.virtual_host is None
    assert cfg.context_root is None


def test_extract_ignores_target_dir(tmp_path: Path) -> None:
    """target/ tiene copies buildeadas del WEB-INF — preferimos el src."""
    src = tmp_path / "src" / "main" / "webapp" / "WEB-INF"
    target = tmp_path / "target" / "app" / "WEB-INF"
    src.mkdir(parents=True)
    target.mkdir(parents=True)
    # src: VHClientes
    (src / "ibm-web-bnd.xml").write_text(IBM_WEB_BND, encoding="utf-8")
    # target: un host distinto a proposito
    (target / "ibm-web-bnd.xml").write_text(
        IBM_WEB_BND.replace("VHClientes", "default_host"),
        encoding="utf-8",
    )
    cfg = extract_was_config(tmp_path)
    # Debe preferir src, no target
    assert cfg.virtual_host == "VHClientes"


def test_needs_human_review_flags_virtualhost(tmp_path: Path) -> None:
    cfg = WasConfig(virtual_host="VHClientes")
    warns = cfg.needs_human_review()
    assert any("virtual-host 'VHClientes'" in w for w in warns)


def test_needs_human_review_default_host_no_warn() -> None:
    cfg = WasConfig(virtual_host="default_host")
    warns = cfg.needs_human_review()
    # default_host no genera warning (es el valor generico de WAS)
    assert not any("virtual-host" in w for w in warns)


def test_render_markdown_includes_all_fields(tmp_path: Path) -> None:
    legacy = _make_was_legacy(tmp_path)
    cfg = extract_was_config(legacy)
    md = render_was_config_markdown(cfg, "WSClientes0010")
    assert "VHClientes" in md
    assert "WSClientes0010" in md
    assert "/soap/WSClientes0010Request" in md
    assert "TRACE" in md
    assert "Warnings para el reviewer humano" in md


def test_render_markdown_empty() -> None:
    cfg = WasConfig()
    md = render_was_config_markdown(cfg, "svc")
    assert md == ""


def test_render_prompt_appendix(tmp_path: Path) -> None:
    legacy = _make_was_legacy(tmp_path)
    cfg = extract_was_config(legacy)
    appendix = render_was_config_prompt_appendix(cfg, "WSClientes0010")
    assert "WAS config (EXACTA" in appendix
    assert "VHClientes" in appendix
    assert "context-path=/WSClientes0010" in appendix
    assert "no inventar" in appendix.lower()


def test_extract_partial_only_webxml(tmp_path: Path) -> None:
    """Solo web.xml sin los bindings IBM — aun extrae url-patterns."""
    webinf = tmp_path / "WEB-INF"
    webinf.mkdir(parents=True)
    (webinf / "web.xml").write_text(WEB_XML, encoding="utf-8")
    cfg = extract_was_config(tmp_path)
    assert cfg.url_patterns == ["/soap/WSClientes0010Request", "/*"]
    assert cfg.virtual_host is None
    assert cfg.context_root is None
    assert not cfg.is_empty  # web.xml solo ya cuenta


def test_extract_multiple_url_patterns(tmp_path: Path) -> None:
    webinf = tmp_path / "WEB-INF"
    webinf.mkdir(parents=True)
    multi = WEB_XML.replace(
        "<url-pattern>/soap/WSClientes0010Request</url-pattern>",
        "<url-pattern>/a</url-pattern><url-pattern>/b</url-pattern>",
    )
    (webinf / "web.xml").write_text(multi, encoding="utf-8")
    cfg = extract_was_config(tmp_path)
    assert "/a" in cfg.url_patterns
    assert "/b" in cfg.url_patterns
