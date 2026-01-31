import logging
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, NAME, MANUFACTURER, DID, STATUS, TYPE, SYSTEM
from .coordinator import ApexDataUpdateCoordinator

logger = logging.getLogger(__name__)


class ApexEntity(CoordinatorEntity):
    def __init__(self, entity_type: str, entity: dict, coordinator: ApexDataUpdateCoordinator, unique_id_suffix: str | None = None,):
        super().__init__(coordinator)

        base_id = f"{coordinator.hostname}_{entity[NAME]}".lower().replace("-", "_")
        if unique_id_suffix:
            base_id = f"{base_id}_{unique_id_suffix}"
        self._device_id = self._attr_unique_id = base_id

        base_name = f"{coordinator.hostname.capitalize()} {entity[NAME]}"
        if unique_id_suffix:
            base_name = f"{base_name} {unique_id_suffix.replace('_', ' ').title()}"
        self._attr_name = base_name

        logger.debug(
            f"{entity_type}.{self._device_id} = (NAME: {entity[NAME]}, DID: {entity[DID]}, TYPE: {entity[TYPE]})"
        )

        self.coordinator_context = object()


    async def async_added_to_hass(self) -> None:
        """When entity is added to hass."""
        await super().async_added_to_hass()
        self._handle_coordinator_update()

    @property
    def device_id(self):
        return self._device_id

    @property
    def device_info(self):
        if self._device_id is None:
            return None

        return {
            "identifiers": {(DOMAIN, self.coordinator.deviceip)},
            NAME: self.coordinator.hostname.capitalize(),
            "hw_version": self.coordinator.data[STATUS][SYSTEM]["hardware"],
            "sw_version": self.coordinator.data[STATUS][SYSTEM]["software"],
            "manufacturer": MANUFACTURER
        }
