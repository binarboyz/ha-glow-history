"""Status sensors showing how fresh the imported data is."""

from __future__ import annotations

from datetime import datetime

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.const import EntityCategory
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, FUELS
from .coordinator import GlowHistoryCoordinator


async def async_setup_entry(hass, entry, async_add_entities) -> None:
    """Add status sensors."""
    coordinator: GlowHistoryCoordinator = entry.runtime_data
    entities: list[SensorEntity] = [
        DataUntilSensor(coordinator, entry.entry_id, fuel) for fuel in FUELS
    ]
    entities.append(LastImportSensor(coordinator, entry.entry_id))
    async_add_entities(entities)


class _Base(CoordinatorEntity[GlowHistoryCoordinator], SensorEntity):
    _attr_has_entity_name = True
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: GlowHistoryCoordinator, entry_id: str) -> None:
        super().__init__(coordinator)
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry_id)},
            name="Glow History Import",
            manufacturer="Hildebrand Glow (unofficial)",
            entry_type=DeviceEntryType.SERVICE,
        )


class DataUntilSensor(_Base):
    """End of the newest half-hour of usage Glowmarkt has delivered."""

    def __init__(self, coordinator: GlowHistoryCoordinator, entry_id: str, fuel: str) -> None:
        super().__init__(coordinator, entry_id)
        self._fuel = fuel
        self._attr_name = f"{fuel.capitalize()} data available up to"
        self._attr_unique_id = f"{entry_id}_{fuel}_data_until"
        self._attr_icon = "mdi:lightning-bolt" if fuel == "electricity" else "mdi:fire"

    @property
    def native_value(self) -> datetime | None:
        return (self.coordinator.data or {}).get(self._fuel)


class LastImportSensor(_Base):
    """When the last successful import finished."""

    _attr_name = "Last import"
    _attr_icon = "mdi:database-import"

    def __init__(self, coordinator: GlowHistoryCoordinator, entry_id: str) -> None:
        super().__init__(coordinator, entry_id)
        self._attr_unique_id = f"{entry_id}_last_import"

    @property
    def native_value(self) -> datetime | None:
        return self.coordinator.last_import
