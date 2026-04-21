"""Mapeo de prefijo de servicio -> dominio (en ingles) para naming de adapters.

El CLI y los prompts usan este mapping para generar los names correctos de
ports, adapters, services, etc. segun el dominio del servicio legacy.

Ejemplos:
  WSClientes0007  -> Customer (CustomerOutputPort, CustomerBancsAdapter, etc.)
  WSReglas0010    -> Rules    (RulesOutputPort, RulesBancsAdapter, etc.)
  WSTecnicos0036  -> Technical (TechnicalOutputPort, TechnicalBancsAdapter, etc.)
  WSCuentas0012   -> Account  (AccountOutputPort, ...)
  ORQClientes0023 -> Customer (mismo dominio que WSClientes)

El check 1.4 del checklist usa este mapping para verificar que haya
1 solo output port del dominio principal del servicio.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Domain:
    """Representa un dominio de negocio del banco."""

    pascal: str  # PascalCase para nombres de clases
    lower: str  # lowercase para paquetes / paths
    es_singular: str  # singular en espaniol (descriptivo)


# Mapeo prefijo -> dominio. Singular en ingles segun convencion del banco.
SERVICE_PREFIX_TO_DOMAIN: dict[str, Domain] = {
    # Servicios de clientes
    "wsclientes": Domain("Customer", "customer", "cliente"),
    "orqclientes": Domain("Customer", "customer", "cliente"),
    # Servicios de cuentas
    "wscuentas": Domain("Account", "account", "cuenta"),
    "orqcuentas": Domain("Account", "account", "cuenta"),
    # Reglas de negocio
    "wsreglas": Domain("Rules", "rules", "regla"),
    "orqreglas": Domain("Rules", "rules", "regla"),
    # Servicios tecnicos / utilities
    "wstecnicos": Domain("Technical", "technical", "tecnico"),
    "orqtecnicos": Domain("Technical", "technical", "tecnico"),
    # Tarjetas
    "wstarjetas": Domain("Card", "card", "tarjeta"),
    "orqtarjetas": Domain("Card", "card", "tarjeta"),
    # Productos
    "wsproductos": Domain("Product", "product", "producto"),
    "orqproductos": Domain("Product", "product", "producto"),
    # Transferencias
    "wstransferencias": Domain("Transfer", "transfer", "transferencia"),
    "orqtransferencias": Domain("Transfer", "transfer", "transferencia"),
    # Pagos
    "wspagos": Domain("Payment", "payment", "pago"),
    "orqpagos": Domain("Payment", "payment", "pago"),
    # Notificaciones
    "wsnotificaciones": Domain("Notification", "notification", "notificacion"),
    "orqnotificaciones": Domain("Notification", "notification", "notificacion"),
    # Seguridad / autorizaciones
    "wsseguridad": Domain("Security", "security", "seguridad"),
    "wsautorizaciones": Domain("Authorization", "authorization", "autorizacion"),
}

# Mapeo prefijo de UMP -> dominio del adapter que va a representarlos.
# IMPORTANTE: este es el mapping que define los adapters reales del servicio.
# Un mismo WS/ORQ puede invocar UMPs de varios dominios y necesita 1 adapter por dominio.
#
# Ejemplo: WSClientes0007 invoca UMPClientes0002 + UMPSeguridad0001 + UMPCuentas0010
# -> 3 output ports/adapters: Customer + Security + Account.
UMP_PREFIX_TO_DOMAIN: dict[str, Domain] = {
    "umpclientes": Domain("Customer", "customer", "cliente"),
    "umpcuentas": Domain("Account", "account", "cuenta"),
    "umpseguridad": Domain("Security", "security", "seguridad"),
    "umpreglas": Domain("Rules", "rules", "regla"),
    "umptecnicos": Domain("Technical", "technical", "tecnico"),
    "umptarjetas": Domain("Card", "card", "tarjeta"),
    "umpproductos": Domain("Product", "product", "producto"),
    "umptransferencias": Domain("Transfer", "transfer", "transferencia"),
    "umppagos": Domain("Payment", "payment", "pago"),
    "umpnotificaciones": Domain("Notification", "notification", "notificacion"),
    "umpautorizaciones": Domain("Authorization", "authorization", "autorizacion"),
    "umpcanales": Domain("Channel", "channel", "canal"),
    "umpcontratos": Domain("Contract", "contract", "contrato"),
    "umpfirmas": Domain("Signature", "signature", "firma"),
    "umpdocumentos": Domain("Document", "document", "documento"),
}

# Dominio fallback cuando el prefijo no esta mapeado.
UNKNOWN_DOMAIN = Domain("Generic", "generic", "generico")


def _split_service(service: str) -> tuple[str, str]:
    """`WSClientes0010` -> (`wsclientes`, `0010`)."""
    svc_lower = service.lower()
    m = re.match(r"^([a-z]+)(\d{4})$", svc_lower)
    if not m:
        return (svc_lower, "")
    return (m.group(1), m.group(2))


def get_domain(service: str) -> Domain:
    """Retorna el Domain del servicio (basado en su prefijo WS/ORQ).

    NOTA: este es el dominio "principal" del servicio. Pero los adapters reales
    se determinan por los UMPs invocados — usar `domains_for_umps()` para eso.
    """
    prefix, _ = _split_service(service)
    return SERVICE_PREFIX_TO_DOMAIN.get(prefix, UNKNOWN_DOMAIN)


def get_ump_domain(ump_name: str) -> Domain:
    """Retorna el Domain de un UMP segun su prefijo.

    Ej: `UMPClientes0002` -> Customer
        `UMPSeguridad0001` -> Security
        `UMPCuentas0010` -> Account
    """
    prefix, _ = _split_service(ump_name)
    return UMP_PREFIX_TO_DOMAIN.get(prefix, UNKNOWN_DOMAIN)


def domains_for_umps(ump_names: list[str]) -> list[Domain]:
    """Lista de dominios distintos requeridos segun los UMPs invocados.

    Retorna la lista deduplicada y ordenada. Cada Domain en la lista debe
    convertirse en 1 output port + 1 adapter en el codigo del servicio.

    Ej: ['UMPClientes0002', 'UMPClientes0020', 'UMPSeguridad0001']
        -> [Customer, Security]  (2 ports/adapters necesarios)
    """
    seen: set[str] = set()
    domains: list[Domain] = []
    for ump in sorted(ump_names):
        d = get_ump_domain(ump)
        if d.pascal not in seen:
            seen.add(d.pascal)
            domains.append(d)
    return domains


def umps_grouped_by_domain(ump_names: list[str]) -> dict[str, list[str]]:
    """Agrupa los UMPs por dominio.

    Util para generar los metodos de cada port: cada UMP del mismo dominio
    se vuelve un metodo del port correspondiente.

    Ej: ['UMPClientes0002', 'UMPClientes0020', 'UMPSeguridad0001']
        -> {'Customer': ['UMPClientes0002', 'UMPClientes0020'],
            'Security': ['UMPSeguridad0001']}
    """
    grouped: dict[str, list[str]] = {}
    for ump in sorted(ump_names):
        d = get_ump_domain(ump)
        grouped.setdefault(d.pascal, []).append(ump)
    return grouped


def expected_port_names(service: str) -> list[str]:
    """Retorna nombres de output port esperados para el dominio del servicio.

    Ej: WSClientes0007 -> [`CustomerOutputPort`, `CustomerBancsOutputPort`,
                           `CustomerBancsPort`, `CustomerCorePort`].
    El checklist Check 1.4 usa esta lista para validar el dominio del port.
    """
    d = get_domain(service)
    return [
        f"{d.pascal}OutputPort",
        f"{d.pascal}BancsOutputPort",
        f"{d.pascal}BancsPort",
        f"{d.pascal}CorePort",
        f"{d.pascal}{d.pascal}OutputPort",  # ej. CustomerCustomerOutputPort (raro pero posible)
    ]


def expected_adapter_names(service: str) -> list[str]:
    """Retorna nombres de adapter esperados."""
    d = get_domain(service)
    return [
        f"{d.pascal}BancsAdapter",
        f"{d.pascal}CoreAdapter",
        f"{d.pascal}Adapter",
    ]


def all_known_prefixes() -> list[str]:
    """Util para tests / debugging."""
    return sorted(SERVICE_PREFIX_TO_DOMAIN.keys())
