"""Plantillas Java de `TraceLoggerManagementPathConfig`.

Los extractores del `lib-trace-logger` vuelcan cada request en un
`RequestInformationContextHolder` que es un `@Component` **singleton**: las
sondas de liveness/readiness/prometheus pisan el contexto del request de negocio
y un trace `@BpTraceable` termina reportando `requestUri=/actuator/...` (hallazgo
del TO, 2026-08-25). Bajar `logging.level` no sirve y un filtro adicional tampoco
puede impedir que el filtro de la libreria corra: hay que **reemplazar el bean**
con un `BeanPostProcessor`.

Fuente: `BPTPSRE-SpringBoot4-probes-actuator-logs` §4. El texto es identico al de
`prompts/doublecheck.md` Paso 1.10 — `test_java_templates_match_doublecheck_prompt`
lo verifica para que el codigo que genera el autofix y el que lee el agente no
puedan divergir.

La variante se elige **por el starter de `build.gradle`**, no por el tipo de
servicio: `spring-boot-starter-webflux` -> reactiva (ORQ, BUS con invocaBancs y
BUS sin BANCS de 1 operacion); `spring-boot-starter-web`/`-web-services` ->
servlet (WAS y todo SOAP). Compila igual con `lib-trace-logger:1.4.0` y con
`lib-trace-logger-sb4:1.2.0`: los FQCN de los extractores no cambiaron.

`__PKG__` se reemplaza por el paquete base del proyecto.
"""

from __future__ import annotations

TRACE_LOGGER_MGMT_CONFIG_CLASS = "TraceLoggerManagementPathConfig"

TRACE_LOGGER_MGMT_WEBFLUX = """\
package __PKG__.infrastructure.config;

import com.pichincha.common.trace.logger.extractor.request.information.reactive.ReactiveRequestInformationExtractor;
import org.springframework.beans.factory.config.BeanPostProcessor;
import org.springframework.context.EnvironmentAware;
import org.springframework.core.env.Environment;
import org.springframework.lang.NonNull;
import org.springframework.stereotype.Component;
import org.springframework.web.server.ServerWebExchange;
import org.springframework.web.server.WebFilter;
import org.springframework.web.server.WebFilterChain;
import reactor.core.publisher.Mono;

@Component
public class TraceLoggerManagementPathConfig implements BeanPostProcessor, EnvironmentAware {

  private static final String BASE_PATH_PROPERTY = "management.endpoints.web.base-path";
  private static final String DEFAULT_BASE_PATH = "/actuator";

  private String managementBasePath = DEFAULT_BASE_PATH;

  @Override
  public void setEnvironment(Environment environment) {
    String basePath = environment.getProperty(BASE_PATH_PROPERTY, DEFAULT_BASE_PATH);
    this.managementBasePath = basePath.isBlank() ? DEFAULT_BASE_PATH : basePath;
  }

  @Override
  public Object postProcessAfterInitialization(Object bean, String beanName) {
    if (bean instanceof ReactiveRequestInformationExtractor delegate) {
      return new ManagementPathAwareExtractor(delegate, managementBasePath);
    }
    return bean;
  }

  // El extractor de lib-trace-logger vuelca cada request en un RequestInformationContextHolder
  // singleton: las sondas de liveness/readiness/prometheus pisan el contexto del request de
  // negocio y ademas bufferean su body. Se las deja pasar sin capturar.
  private record ManagementPathAwareExtractor(WebFilter delegate, String managementBasePath)
      implements WebFilter {

    @NonNull
    @Override
    public Mono<Void> filter(@NonNull ServerWebExchange exchange, @NonNull WebFilterChain chain) {
      if (isManagementPath(exchange)) {
        return chain.filter(exchange);
      }
      return delegate.filter(exchange, chain);
    }

    private boolean isManagementPath(ServerWebExchange exchange) {
      return exchange
          .getRequest()
          .getPath()
          .pathWithinApplication()
          .value()
          .startsWith(managementBasePath);
    }
  }
}
"""

TRACE_LOGGER_MGMT_SERVLET = """\
package __PKG__.infrastructure.config;

import com.pichincha.common.trace.logger.extractor.request.information.servlet.ServletRequestInformationExtractor;
import jakarta.servlet.Filter;
import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.ServletRequest;
import jakarta.servlet.ServletResponse;
import jakarta.servlet.http.HttpServletRequest;
import java.io.IOException;
import org.springframework.beans.factory.config.BeanPostProcessor;
import org.springframework.context.EnvironmentAware;
import org.springframework.core.env.Environment;
import org.springframework.stereotype.Component;

@Component
public class TraceLoggerManagementPathConfig implements BeanPostProcessor, EnvironmentAware {

  private static final String BASE_PATH_PROPERTY = "management.endpoints.web.base-path";
  private static final String DEFAULT_BASE_PATH = "/actuator";

  private String managementBasePath = DEFAULT_BASE_PATH;

  @Override
  public void setEnvironment(Environment environment) {
    String basePath = environment.getProperty(BASE_PATH_PROPERTY, DEFAULT_BASE_PATH);
    this.managementBasePath = basePath.isBlank() ? DEFAULT_BASE_PATH : basePath;
  }

  @Override
  public Object postProcessAfterInitialization(Object bean, String beanName) {
    if (bean instanceof ServletRequestInformationExtractor delegate) {
      return new ManagementPathAwareExtractor(delegate, managementBasePath);
    }
    return bean;
  }

  // El extractor de lib-trace-logger vuelca cada request en un RequestInformationContextHolder
  // singleton: las sondas de liveness/readiness/prometheus pisan el contexto del request de
  // negocio y ademas cachean su body en memoria. Se las deja pasar sin capturar.
  private record ManagementPathAwareExtractor(Filter delegate, String managementBasePath)
      implements Filter {

    @Override
    public void doFilter(ServletRequest request, ServletResponse response, FilterChain chain)
        throws IOException, ServletException {
      if (request instanceof HttpServletRequest httpRequest && isManagementPath(httpRequest)) {
        chain.doFilter(request, response);
        return;
      }
      delegate.doFilter(request, response, chain);
    }

    private boolean isManagementPath(HttpServletRequest request) {
      return pathWithinApplication(request).startsWith(managementBasePath);
    }

    private String pathWithinApplication(HttpServletRequest request) {
      String uri = request.getRequestURI();
      String contextPath = request.getContextPath();
      if (contextPath == null || contextPath.isEmpty() || !uri.startsWith(contextPath)) {
        return uri;
      }
      return uri.substring(contextPath.length());
    }
  }
}
"""


def trace_logger_mgmt_template(uses_webflux: bool, base_package: str) -> str:
    """Codigo de la clase para el stack del proyecto, con el paquete resuelto."""
    template = TRACE_LOGGER_MGMT_WEBFLUX if uses_webflux else TRACE_LOGGER_MGMT_SERVLET
    return template.replace("__PKG__", base_package)
