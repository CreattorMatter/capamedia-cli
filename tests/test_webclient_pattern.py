"""Tests del Check 7.9 — WebClient oficial para downstream WS (LT-3b / §4.17).

Caso real que motivo el check: ORQClientes0023 (2026-07) construia sus
WebClients con `HttpClient.create()` sin ConnectionProvider, ReadTimeoutHandler
en vez de responseTimeout, timeouts globales compartidos y las URLs bajo
`services.<svc>.base-url` — sin bloque `webclient.<svc>` en application.yml.
El patron oficial del banco (doc lib-event-logs, seccion WebFlux) exige
Builder-bean por downstream + ConnectionProvider + prefix `webclient`.
"""

from __future__ import annotations

from pathlib import Path

from capamedia_cli.core.checklist_rules import CheckContext, run_block_7

_WEBCLIENT_YML_BLOCK = (
    "webclient:\n"
    "  wsclientes0024:\n"
    "    url: ${CCC_WSCLIENTES0024_URL}\n"
    "    timeout: ${CCC_WSCLIENTES0024_TIMEOUT}\n"
    "    read-timeout: ${CCC_WSCLIENTES0024_READ_TIMEOUT}\n"
    "    max-connections: ${CCC_WSCLIENTES0024_MAX_CONNECTIONS}\n"
    "    pending-acquire-max-count: ${CCC_WSCLIENTES0024_PENDING_ACQUIRE_MAX_COUNT}\n"
)

_OFFICIAL_HELPER = """\
package com.pichincha.sp.infrastructure.output.config;
import reactor.netty.http.client.HttpClient;
import reactor.netty.resources.ConnectionProvider;
public class WebClientConfig {
    public static HttpClient createHttpClient(HttpClientProperty p) {
        return HttpClient.create(createConnectionProvider(p))
                .responseTimeout(p.readTimeout());
    }
    private static ConnectionProvider createConnectionProvider(HttpClientProperty p) {
        return ConnectionProvider.builder("custom").build();
    }
}
"""

_OFFICIAL_CONFIG = """\
package com.pichincha.sp.infrastructure.output.config;
import org.springframework.web.reactive.function.client.WebClient;
public class WSClientes0024WebClientConfig {
    public WebClient.Builder wsclientes0024WebClientBuilder(WebClientProperty p) {
        return WebClient.builder().baseUrl(p.wsclientes0024().url());
    }
    public WebClient wsclientes0024WebClient(WebClient.Builder b) {
        return b.build();
    }
}
"""

_LEGACY_CONFIG = """\
package com.pichincha.sp.infrastructure.config;
import io.netty.handler.timeout.ReadTimeoutHandler;
import org.springframework.web.reactive.function.client.WebClient;
import reactor.netty.http.client.HttpClient;
public class WebClientsConfig {
    private WebClient.Builder buildWebClient(String baseUrl) {
        HttpClient httpClient = HttpClient.create()
                .doOnConnected(conn -> conn.addHandlerLast(new ReadTimeoutHandler(5000)));
        return WebClient.builder().baseUrl(baseUrl);
    }
}
"""


def _by_id(results, check_id: str):
    return next((r for r in results if r.id == check_id), None)


def _make_project(
    tmp_path: Path,
    *,
    webflux: bool = True,
    java_files: dict[str, str] | None = None,
    app_yml_extra: str = "",
) -> Path:
    root = tmp_path / "migrated"
    res = root / "src" / "main" / "resources"
    res.mkdir(parents=True)
    (res / "application.yml").write_text(
        "spring:\n  application:\n    name: foo\n" + app_yml_extra, encoding="utf-8"
    )
    starter = "webflux" if webflux else "web"
    (root / "build.gradle").write_text(
        "plugins { id 'org.springframework.boot' version '3.5.15' }\n"
        "dependencies {\n"
        f"    implementation 'org.springframework.boot:spring-boot-starter-{starter}'\n"
        "}\n",
        encoding="utf-8",
    )
    java_root = root / "src" / "main" / "java" / "com" / "pichincha" / "sp"
    for rel, content in (java_files or {}).items():
        f = java_root / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(content, encoding="utf-8")
    return root


def test_79_absent_without_manual_webclient(tmp_path: Path) -> None:
    """WebFlux sin WebClient.builder( manual (ej. BANCS-only via lib-bnc) ->
    el check no aplica."""
    root = _make_project(tmp_path, java_files={"Application.java": "class A {}"})
    assert _by_id(run_block_7(CheckContext(migrated_path=root, legacy_path=None)), "7.9") is None


def test_79_absent_for_mvc(tmp_path: Path) -> None:
    """Sin webflux el check no aplica aunque exista WebClient.builder(."""
    root = _make_project(
        tmp_path, webflux=False, java_files={"config/C.java": _LEGACY_CONFIG}
    )
    assert _by_id(run_block_7(CheckContext(migrated_path=root, legacy_path=None)), "7.9") is None


def test_79_flags_the_orqclientes0023_legacy_pattern(tmp_path: Path) -> None:
    """El patron legacy completo -> FAIL MEDIUM con los 3 sintomas."""
    root = _make_project(tmp_path, java_files={"config/WebClientsConfig.java": _LEGACY_CONFIG})

    check = _by_id(run_block_7(CheckContext(migrated_path=root, legacy_path=None)), "7.9")

    assert check is not None
    assert check.status == "fail"
    assert check.severity == "medium"
    assert "ConnectionProvider" in check.detail
    assert "ReadTimeoutHandler" in check.detail
    assert "webclient" in check.detail


def test_79_passes_official_pattern(tmp_path: Path) -> None:
    root = _make_project(
        tmp_path,
        java_files={
            "infrastructure/output/config/WebClientConfig.java": _OFFICIAL_HELPER,
            "infrastructure/output/config/WSClientes0024WebClientConfig.java": _OFFICIAL_CONFIG,
        },
        app_yml_extra=_WEBCLIENT_YML_BLOCK,
    )

    check = _by_id(run_block_7(CheckContext(migrated_path=root, legacy_path=None)), "7.9")

    assert check is not None
    assert check.status == "pass"


def test_79_fails_when_only_yml_block_missing(tmp_path: Path) -> None:
    """Codigo oficial pero sin bloque `webclient:` en application.yml -> FAIL
    citando solo ese sintoma (era el gap concreto de ORQClientes0023)."""
    root = _make_project(
        tmp_path,
        java_files={
            "infrastructure/output/config/WebClientConfig.java": _OFFICIAL_HELPER,
            "infrastructure/output/config/WSClientes0024WebClientConfig.java": _OFFICIAL_CONFIG,
        },
    )

    check = _by_id(run_block_7(CheckContext(migrated_path=root, legacy_path=None)), "7.9")

    assert check.status == "fail"
    assert "webclient" in check.detail
    assert "ConnectionProvider" not in check.detail
    assert "ReadTimeoutHandler" not in check.detail


def test_79_fails_on_readtimeouthandler_even_with_pool(tmp_path: Path) -> None:
    """ConnectionProvider presente pero ReadTimeoutHandler tambien -> FAIL
    nombrando el archivo con el patron legacy."""
    root = _make_project(
        tmp_path,
        java_files={
            "infrastructure/output/config/WebClientConfig.java": _OFFICIAL_HELPER,
            "config/LegacyConfig.java": _LEGACY_CONFIG,
        },
        app_yml_extra=_WEBCLIENT_YML_BLOCK,
    )

    check = _by_id(run_block_7(CheckContext(migrated_path=root, legacy_path=None)), "7.9")

    assert check.status == "fail"
    assert "ReadTimeoutHandler" in check.detail
    assert "LegacyConfig.java" in check.detail


def test_79_fails_on_global_timeouts_block_without_per_service_entries(tmp_path: Path) -> None:
    """Bloque `webclient:` con timeouts globales (legacy) pero sin la entrada
    `webclient.<svc>:` de cada bean -> FAIL nombrando los downstreams. Es el
    gap exacto de ORQClientes0023."""
    root = _make_project(
        tmp_path,
        java_files={
            "infrastructure/output/config/WebClientConfig.java": _OFFICIAL_HELPER,
            "infrastructure/output/config/WSClientes0024WebClientConfig.java": _OFFICIAL_CONFIG,
        },
        app_yml_extra=(
            "webclient:\n"
            "  connect-timeout: ${CCC_WEBCLIENT_CONNECT_TIMEOUT}\n"
            "  read-timeout: ${CCC_WEBCLIENT_READ_TIMEOUT}\n"
        ),
    )

    check = _by_id(run_block_7(CheckContext(migrated_path=root, legacy_path=None)), "7.9")

    assert check.status == "fail"
    assert "webclient.<svc>" in check.detail
    assert "wsclientes0024" in check.detail
