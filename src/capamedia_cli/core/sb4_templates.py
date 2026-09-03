"""Plantillas Java del Cambio C (Spring Boot 4 / probes / ruido de Actuator).

`TraceLoggerManagementPathConfig`: `BeanPostProcessor` que envuelve el extractor
de `lib-trace-logger` (`ServletRequestInformationExtractor` en MVC,
`ReactiveRequestInformationExtractor` en WebFlux) para que las sondas de
management (liveness / readiness / prometheus) pasen sin capturar. Motivo:
`RequestInformationContextHolder` es un `@Component` singleton; cada sonda pisa
el contexto del request de negocio y el trace `@BpTraceable` termina reportando
`requestUri=/actuator/health/readiness` (hallazgo TO 2026-08-25 §1.2).

Compila igual con `lib-trace-logger:1.4.0` (SB3) y `lib-trace-logger-sb4:1.2.0`
(SB4): los FQCN de los extractores no cambian. Fuente: canonical
`bank-official-rules.md` Regla 9e.3 y doc BPTPSRE-SpringBoot4-probes-actuator-logs
§4. Verificado en WSPagos0017 (MVC) y ORQPagos0011/0008, ORQProductos1001,
WSProductos0178 (WebFlux): build verde en los 5.

El placeholder `__PKG__` se reemplaza por el paquete base del proyecto
(`com.pichincha.sp` por defecto). Lo consume `autofix.fix_add_trace_logger_management_config`.
"""

from __future__ import annotations

MGMT_CONFIG_MVC = """package __PKG__.infrastructure.config;

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

MGMT_CONFIG_WEBFLUX = """package __PKG__.infrastructure.config;

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

MGMT_CONFIG_TEST_MVC = """package __PKG__.infrastructure.config;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;

import com.pichincha.common.trace.logger.extractor.request.information.servlet.ServletRequestInformationExtractor;
import jakarta.servlet.Filter;
import jakarta.servlet.FilterChain;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.mock.env.MockEnvironment;
import org.springframework.mock.web.MockHttpServletRequest;
import org.springframework.mock.web.MockHttpServletResponse;

@ExtendWith(MockitoExtension.class)
class TraceLoggerManagementPathConfigTest {

  private TraceLoggerManagementPathConfig config;
  private ServletRequestInformationExtractor delegate;
  private FilterChain chain;
  private MockHttpServletResponse response;

  @BeforeEach
  void setUp() {
    config = new TraceLoggerManagementPathConfig();
    config.setEnvironment(new MockEnvironment());
    delegate = mock(ServletRequestInformationExtractor.class);
    chain = mock(FilterChain.class);
    response = new MockHttpServletResponse();
  }

  private Filter wrap() {
    return (Filter) config.postProcessAfterInitialization(delegate, "servletRequestInformationExtractor");
  }

  @Test
  void givenPrometheusProbe_whenDoFilter_thenSkipsDelegate() throws Exception {
    MockHttpServletRequest request = new MockHttpServletRequest("GET", "/actuator/prometheus");

    wrap().doFilter(request, response, chain);

    verify(chain).doFilter(request, response);
    verify(delegate, never()).doFilter(any(), any(), any());
  }

  @Test
  void givenLivenessProbe_whenDoFilter_thenSkipsDelegate() throws Exception {
    MockHttpServletRequest request = new MockHttpServletRequest("GET", "/actuator/health/liveness");

    wrap().doFilter(request, response, chain);

    verify(chain).doFilter(request, response);
    verify(delegate, never()).doFilter(any(), any(), any());
  }

  @Test
  void givenReadinessProbe_whenDoFilter_thenSkipsDelegate() throws Exception {
    MockHttpServletRequest request = new MockHttpServletRequest("GET", "/actuator/health/readiness");

    wrap().doFilter(request, response, chain);

    verify(chain).doFilter(request, response);
    verify(delegate, never()).doFilter(any(), any(), any());
  }

  @Test
  void givenBusinessRequest_whenDoFilter_thenDelegates() throws Exception {
    MockHttpServletRequest request = new MockHttpServletRequest("POST", "/IntegrationBus/soap/Servicio");

    wrap().doFilter(request, response, chain);

    verify(delegate).doFilter(request, response, chain);
    verify(chain, never()).doFilter(any(), any());
  }

  @Test
  void givenCustomBasePath_whenManagementRequest_thenSkipsDelegate() throws Exception {
    config.setEnvironment(
        new MockEnvironment().withProperty("management.endpoints.web.base-path", "/management"));
    MockHttpServletRequest request = new MockHttpServletRequest("GET", "/management/health");

    wrap().doFilter(request, response, chain);

    verify(chain).doFilter(request, response);
    verify(delegate, never()).doFilter(any(), any(), any());
  }

  @Test
  void givenBlankBasePath_whenBusinessRequest_thenFallsBackToActuatorAndDelegates() throws Exception {
    config.setEnvironment(new MockEnvironment().withProperty("management.endpoints.web.base-path", ""));
    MockHttpServletRequest request = new MockHttpServletRequest("POST", "/IntegrationBus/soap/Servicio");

    wrap().doFilter(request, response, chain);

    verify(delegate).doFilter(request, response, chain);
  }

  @Test
  void givenUnrelatedBean_whenPostProcess_thenReturnsSameInstance() {
    Filter other = mock(Filter.class);

    Object result = config.postProcessAfterInitialization(other, "otherFilter");

    assertThat(result).isSameAs(other);
  }

  @Test
  void givenContextPath_whenManagementRequest_thenSkipsDelegate() throws Exception {
    MockHttpServletRequest request = new MockHttpServletRequest("GET", "/svc/actuator/health");
    request.setContextPath("/svc");

    wrap().doFilter(request, response, chain);

    verify(chain).doFilter(request, response);
    verify(delegate, never()).doFilter(any(), any(), any());
  }
}
"""

MGMT_CONFIG_TEST_WEBFLUX = """package __PKG__.infrastructure.config;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import com.pichincha.common.trace.logger.extractor.request.information.reactive.ReactiveRequestInformationExtractor;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.mock.env.MockEnvironment;
import org.springframework.mock.http.server.reactive.MockServerHttpRequest;
import org.springframework.mock.web.server.MockServerWebExchange;
import org.springframework.web.server.WebFilter;
import org.springframework.web.server.WebFilterChain;
import reactor.core.publisher.Mono;
import reactor.test.StepVerifier;

@ExtendWith(MockitoExtension.class)
class TraceLoggerManagementPathConfigTest {

  private TraceLoggerManagementPathConfig config;
  private ReactiveRequestInformationExtractor delegate;
  private WebFilterChain chain;

  @BeforeEach
  void setUp() {
    config = new TraceLoggerManagementPathConfig();
    config.setEnvironment(new MockEnvironment());
    delegate = mock(ReactiveRequestInformationExtractor.class);
    chain = mock(WebFilterChain.class);
    when(chain.filter(any())).thenReturn(Mono.empty());
  }

  private WebFilter wrap() {
    return (WebFilter) config.postProcessAfterInitialization(delegate, "reactiveRequestInformationExtractor");
  }

  private static MockServerWebExchange exchange(String path) {
    return MockServerWebExchange.from(MockServerHttpRequest.get(path).build());
  }

  @Test
  void givenPrometheusProbe_whenFilter_thenSkipsDelegate() {
    MockServerWebExchange exchange = exchange("/actuator/prometheus");

    StepVerifier.create(wrap().filter(exchange, chain)).verifyComplete();

    verify(chain).filter(exchange);
    verify(delegate, never()).filter(any(), any());
  }

  @Test
  void givenLivenessProbe_whenFilter_thenSkipsDelegate() {
    MockServerWebExchange exchange = exchange("/actuator/health/liveness");

    StepVerifier.create(wrap().filter(exchange, chain)).verifyComplete();

    verify(chain).filter(exchange);
    verify(delegate, never()).filter(any(), any());
  }

  @Test
  void givenReadinessProbe_whenFilter_thenSkipsDelegate() {
    MockServerWebExchange exchange = exchange("/actuator/health/readiness");

    StepVerifier.create(wrap().filter(exchange, chain)).verifyComplete();

    verify(chain).filter(exchange);
    verify(delegate, never()).filter(any(), any());
  }

  @Test
  void givenBusinessRequest_whenFilter_thenDelegates() {
    MockServerWebExchange exchange = exchange("/IntegrationBus/soap/Servicio");
    when(delegate.filter(exchange, chain)).thenReturn(Mono.empty());

    StepVerifier.create(wrap().filter(exchange, chain)).verifyComplete();

    verify(delegate).filter(exchange, chain);
    verify(chain, never()).filter(any());
  }

  @Test
  void givenCustomBasePath_whenManagementRequest_thenSkipsDelegate() {
    config.setEnvironment(
        new MockEnvironment().withProperty("management.endpoints.web.base-path", "/management"));
    MockServerWebExchange exchange = exchange("/management/health");

    StepVerifier.create(wrap().filter(exchange, chain)).verifyComplete();

    verify(chain).filter(exchange);
    verify(delegate, never()).filter(any(), any());
  }

  @Test
  void givenBlankBasePath_whenBusinessRequest_thenFallsBackToActuatorAndDelegates() {
    config.setEnvironment(new MockEnvironment().withProperty("management.endpoints.web.base-path", ""));
    MockServerWebExchange exchange = exchange("/IntegrationBus/soap/Servicio");
    when(delegate.filter(exchange, chain)).thenReturn(Mono.empty());

    StepVerifier.create(wrap().filter(exchange, chain)).verifyComplete();

    verify(delegate).filter(exchange, chain);
  }

  @Test
  void givenUnrelatedBean_whenPostProcess_thenReturnsSameInstance() {
    WebFilter other = mock(WebFilter.class);

    Object result = config.postProcessAfterInitialization(other, "otherFilter");

    assertThat(result).isSameAs(other);
  }
}
"""
