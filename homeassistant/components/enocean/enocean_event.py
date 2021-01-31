"""Support for EnOcean buttons"""
from __future__ import annotations
from homeassistant.core import HomeAssistant
from enocean.utils import to_hex_string
import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_DEVICE_CLASS, CONF_ID, CONF_NAME
from homeassistant.core import HomeAssistant
import homeassistant.helpers.config_validation as cv

from .const import CONF_EVENTS, DATA_ENOCEAN, DOMAIN, SIGNAL_RECEIVE_MESSAGE
from .device import EnOceanEntity

DEFAULT_NAME = "EnOcean button"
EVENT_BUTTON_PRESSED = "button_pressed"

EVENT_SCHEMA_DATA = {
    vol.Required(CONF_ID): vol.All(cv.ensure_list, [vol.Coerce(int)]),
    vol.Optional(CONF_NAME, default=DEFAULT_NAME): cv.string,
}

EVENT_SCHEMA = vol.Schema(EVENT_SCHEMA_DATA)

async def async_setup_events(hass: HomeAssistant, configEntry: ConfigEntry):
    if not CONF_EVENTS in configEntry.data:
        return
    hass.data[DATA_ENOCEAN][CONF_EVENTS] = dict()
    for config in configEntry.data[CONF_EVENTS].values():
        new_event = create_entity_from_config(config, hass, configEntry.entry_id)
        hass.async_create_task(new_event.async_update_device_registry())


def create_entity_from_config(config, hass, config_entry_id):
    dev_id = config.get(CONF_ID)
    dev_name = config.get(CONF_NAME)

    return EnOceanEvent(dev_id, dev_name, hass, config_entry_id)


class EnOceanEvent(EnOceanEntity):
    """Representation of EnOcean button sensors such as wall switches.

    Supported EEPs (EnOcean Equipment Profiles):
    - F6-02-01 (Light and Blind Control - Application Style 2)
    - F6-02-02 (Light and Blind Control - Application Style 1)
    """

    def __init__(self, dev_id, dev_name, hass, config_entry_id):
        """Initialize the EnOcean event."""
        super().__init__(dev_id, dev_name)
        self.which = -1
        self.onoff = -1
        self.config_entry_id = config_entry_id
        self.device_entry_id = None
        self.hass = hass
        self.disconnect_dispatcher = None

    @property
    def name(self):
        """Return the default name for the sensor."""
        return self.dev_name

    @property
    def should_poll(self):
        """No polling needed."""
        return False

    def value_changed(self, packet):
        """Fire an event with the data that have changed.

        This method is called when there is an incoming packet associated
        with this platform.

        Example packet data:
        - 2nd button pressed
            ['0xf6', '0x10', '0x00', '0x2d', '0xcf', '0x45', '0x30']
        - button released
            ['0xf6', '0x00', '0x00', '0x2d', '0xcf', '0x45', '0x20']
        """
        # Energy Bow
        pushed = None

        if packet.data[6] == 0x30:
            pushed = 1
        elif packet.data[6] == 0x20:
            pushed = 0

        # self.schedule_update_ha_state()

        action = packet.data[1]
        if action == 0x70:
            self.which = 0
            self.onoff = 0
        elif action == 0x50:
            self.which = 0
            self.onoff = 1
        elif action == 0x30:
            self.which = 1
            self.onoff = 0
        elif action == 0x10:
            self.which = 1
            self.onoff = 1
        elif action == 0x37:
            self.which = 10
            self.onoff = 0
        elif action == 0x15:
            self.which = 10
            self.onoff = 1
        self.hass.bus.fire(
            EVENT_BUTTON_PRESSED,
            {
                "id": self.dev_id,
                "id_as_hex": to_hex_string(self.dev_id),
                "pushed": pushed,
                "which": self.which,
                "onoff": self.onoff,
                "name": self.name,
            },
        )

    @property
    def device_info(self):
        return {
            "identifiers": {
                # Serial numbers are unique identifiers within a specific domain
                (DOMAIN, self.unique_id)
            },
            "name": self.name,
        }

    @property
    def unique_id(self):
        return f"event-{to_hex_string(self.dev_id)}"

    def disconnect(self):
        if self.disconnect_dispatcher != None:
            self.disconnect_dispatcher()
            self.disconnect_dispatcher = None

    async def async_update_device_registry(self):
        """Update device registry."""
        device_registry = await self.hass.helpers.device_registry.async_get_registry()

        entry = device_registry.async_get_or_create(
            config_entry_id=self.config_entry_id, **self.device_info
        )
        self.device_entry_id = entry.id
        self.disconnect_dispatcher = (
            self.hass.helpers.dispatcher.async_dispatcher_connect(
                SIGNAL_RECEIVE_MESSAGE, self._message_received_callback
            )
        )
        self.hass.data[DATA_ENOCEAN][CONF_EVENTS][self.device_entry_id] = self
