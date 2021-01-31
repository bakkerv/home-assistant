"""Support for EnOcean light sources."""
from __future__ import annotations

import math

import voluptuous as vol

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    PLATFORM_SCHEMA,
    SUPPORT_BRIGHTNESS,
    LightEntity,
)
from homeassistant.const import CONF_ID, CONF_LIGHTS, CONF_NAME
from homeassistant.core import HomeAssistant
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType
from enocean.utils import to_hex_string
from .device import EnOceanEntity
from .const import DOMAIN

CONF_SENDER_ID = "sender_id"

DEFAULT_NAME = "EnOcean Light"
SUPPORT_ENOCEAN = SUPPORT_BRIGHTNESS

LIGHT_SCHEMA_DATA = {
    vol.Optional(CONF_ID, default=[]): vol.All(cv.ensure_list, [vol.Coerce(int)]),
    vol.Required(CONF_SENDER_ID): vol.All(cv.ensure_list, [vol.Coerce(int)]),
    vol.Optional(CONF_NAME, default=DEFAULT_NAME): cv.string,
}

LIGHT_SCHEMA = vol.Schema(LIGHT_SCHEMA_DATA)

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(LIGHT_SCHEMA_DATA)


def setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    add_entities: AddEntitiesCallback,
    discovery_info: DiscoveryInfoType | None = None,
) -> None:
    """Set up the EnOcean light platform."""
    add_entities([create_entity_from_config(config)])


async def async_setup_entry(
    hass,
    config_entry,
    async_add_entities,
):
    """Set up config entry."""

    # Add cover from config file
    config_data = config_entry.data
    entities = []
    if CONF_LIGHTS not in config_data:
        return
    for entity_info in config_data[CONF_LIGHTS].values():
        entity = create_entity_from_config(entity_info)
        entities.append(entity)

    async_add_entities(entities)


def create_entity_from_config(config):
    """Create light entity from configuration"""
    sender_id = config.get(CONF_SENDER_ID)
    dev_name = config.get(CONF_NAME)
    dev_id = config.get(CONF_ID)

    return EnOceanLight(sender_id, dev_id, dev_name)


class EnOceanLight(EnOceanEntity, LightEntity):
    """Representation of an EnOcean light source."""

    def __init__(self, sender_id, dev_id, dev_name):
        """Initialize the EnOcean light source."""
        super().__init__(dev_id, dev_name)
        self._on_state = False
        self._brightness = 50
        self._sender_id = sender_id

    @property
    def name(self):
        """Return the name of the device if any."""
        return self.dev_name

    @property
    def brightness(self):
        """Brightness of the light.

        This method is optional. Removing it indicates to Home Assistant
        that brightness is not supported for this light.
        """
        return self._brightness

    @property
    def is_on(self):
        """If light is on."""
        return self._on_state

    @property
    def supported_features(self):
        """Flag supported features."""
        return SUPPORT_ENOCEAN

    def turn_on(self, **kwargs):
        """Turn the light source on or sets a specific dimmer value."""
        if (brightness := kwargs.get(ATTR_BRIGHTNESS)) is not None:
            self._brightness = brightness

        bval = math.floor(self._brightness / 256.0 * 100.0)
        if bval == 0:
            bval = 1
        command = [0xA5, 0x02, bval, 0x01, 0x09]
        command.extend(self._sender_id)
        command.extend([0x00])
        self.send_command(command, [], 0x01)
        self._on_state = True

    def turn_off(self, **kwargs):
        """Turn the light source off."""
        command = [0xA5, 0x02, 0x00, 0x01, 0x09]
        command.extend(self._sender_id)
        command.extend([0x00])
        self.send_command(command, [], 0x01)
        self._on_state = False

    def value_changed(self, packet):
        """Update the internal state of this device.

        Dimmer devices like Eltako FUD61 send telegram in different RORGs.
        We only care about the 4BS (0xA5).
        """
        if packet.data[0] == 0xA5 and packet.data[1] == 0x02:
            val = packet.data[2]
            self._brightness = math.floor(val / 100.0 * 256.0)
            self._on_state = bool(val != 0)
            self.schedule_update_ha_state()

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
        return f"light-{to_hex_string(self.dev_id)}"
