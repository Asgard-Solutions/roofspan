"""Generic Supplier Connector abstraction (Slice 3).

A Supplier's `integration_provider` selects a connector. Connectors advertise capabilities so the UI
can decide which workflow to show — instead of matching on the supplier display name. ABC's existing,
working implementation is wrapped (not rewritten) by AbcSupplyConnector.
"""
from __future__ import annotations

from enum import Enum


class Capability(str, Enum):
    catalog_search = "catalog_search"
    live_pricing = "live_pricing"
    branch_availability = "branch_availability"
    online_order_submission = "online_order_submission"
    order_status = "order_status"
    order_cancel = "order_cancel"
    account_discovery = "account_discovery"


class SupplierConnector:
    provider: str = "generic"
    capabilities: set[Capability] = set()

    def has(self, cap: Capability) -> bool:
        return cap in self.capabilities

    def capability_list(self) -> list[str]:
        return sorted(c.value for c in self.capabilities)


class AbcSupplyConnector(SupplierConnector):
    """Wraps the existing ABC integration (routers/abc_supply.py + integrations/abc_supply/*). This class
    only DECLARES capabilities and routes; the underlying OAuth/catalog/pricing/order code is unchanged."""
    provider = "abc_supply"
    capabilities = {
        Capability.account_discovery, Capability.catalog_search, Capability.live_pricing,
        Capability.branch_availability, Capability.online_order_submission,
        Capability.order_status, Capability.order_cancel,
    }


class ManualSupplierConnector(SupplierConnector):
    """Manual/offline supplier: stored catalog mappings + stored (non-live) pricing, manual ordering."""
    provider = "manual"
    capabilities = set()  # no live capabilities; everything is stored/manual


_REGISTRY = {
    AbcSupplyConnector.provider: AbcSupplyConnector,
    ManualSupplierConnector.provider: ManualSupplierConnector,
}


def get_connector(integration_provider: str | None) -> SupplierConnector:
    cls = _REGISTRY.get(integration_provider or "manual", ManualSupplierConnector)
    return cls()


def capabilities_for(integration_provider: str | None) -> list[str]:
    return get_connector(integration_provider).capability_list()
