"""Support for EnOcean switches."""
from __future__ import annotations

import voluptuous as vol
from enocean.protocol.constants import RORG
from enocean.protocol.packet import RadioPacket
from enocean.utils import to_hex_string


from homeassistant.components.switch import PLATFORM_SCHEMA, SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.const import CONF_ID, CONF_NAME, CONF_SWITCHES
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType

from .device import EnOceanEntity
from .const import SWITCH_ALL_CHANNELS, DOMAIN

CONF_CHANNEL = "channel"
CONF_SENDER_ID = "sender_id"
DEFAULT_NAME = "EnOcean Switch"

SWITCH_SCHEMA_DATA = {
    vol.Required(CONF_ID): vol.All(cv.ensure_list, [vol.Coerce(int)]),
    vol.Optional(CONF_NAME, default=DEFAULT_NAME): cv.string,
    vol.Optional(CONF_CHANNEL, default=SWITCH_ALL_CHANNELS): vol.All(
        int, vol.Range(min=0, max=31)
    ),  # Default all channels
    vol.Required(CONF_SENDER_ID): vol.All(cv.ensure_list, [vol.Coerce(int)]),
}

SWITCH_SCHEMA = vol.Schema(SWITCH_SCHEMA_DATA)

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(SWITCH_SCHEMA_DATA)


def setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    add_entities: AddEntitiesCallback,
    discovery_info: DiscoveryInfoType | None = None,
) -> None:
    """Set up the EnOcean switch platform."""
    add_entities([create_entity_from_config(config)])


async def async_setup_entry(
    hass,
    config_entry,
    async_add_entities,
):
    """Set up config entry."""
    # Add switch from config file
    config_data = config_entry.data
    entities = []
    if CONF_SWITCHES not in config_data:
        return
    for entity_info in config_data[CONF_SWITCHES].values():
        entity = create_entity_from_config(entity_info)
        entities.append(entity)

    async_add_entities(entities)


def create_entity_from_config(config):
    """Create Enocean Switch from config"""
    channel = config.get(CONF_CHANNEL)
    dev_id = config.get(CONF_ID)
    dev_name = config.get(CONF_NAME)
    sender_id = config.get(CONF_SENDER_ID)

    return EnOceanSwitch(dev_id, dev_name, channel, sender_id)


class EnOceanSwitch(EnOceanEntity, SwitchEntity):
    """Representation of an EnOcean switch device."""

    def __init__(self, dev_id, dev_name, channel, sender_id):
        """Initialize the EnOcean switch device."""
        super().__init__(dev_id, dev_name)
        self._light = None
        self._on_state = False
        self._on_state2 = False
        self.channel = channel
        self.sender_id = sender_id

    @property
    def is_on(self):
        """Return whether the switch is on or off."""
        return self._on_state

    @property
    def name(self):
        """Return the device name."""
        return self.dev_name

    def turn_on(self, **kwargs):
        """"Turn on the switch."""
        packet = RadioPacket.create(
            rorg=RORG.VLD,
            rorg_func=0x01,
            rorg_type=0x01,
            sender=self.sender_id,
            destination=self.dev_id,
            command=1,  # Change actuator
            DV=0,  # Switch to new output value (no dimming value)
            IO=self.channel,  # The configured channel
            OV=0x64,  # ON (or 100%)
        )
        self.send_packet(packet)
        self._on_state = True

    def turn_off(self, **kwargs):
        """Turn off the switch."""
        packet = RadioPacket.create(
            rorg=RORG.VLD,
            rorg_func=0x01,
            rorg_type=0x01,
            sender=self.sender_id,
            destination=self.dev_id,
            command=1,  # Change actuator
            DV=0,  # Switch to new output value (no dimming value)
            IO=0x1E,  # The configured channel
            OV=0x0,  # OF (or 0%)
        )
        self.send_packet(packet)
        self._on_state = False

    def value_changed(self, packet):
        """Update the internal state of the switch."""
        if packet.data[0] == 0xA5:
            # power meter telegram, turn on if > 10 watts
            packet.parse_eep(0x12, 0x01)
            if packet.parsed["DT"]["raw_value"] == 1:
                raw_val = packet.parsed["MR"]["raw_value"]
                divisor = packet.parsed["DIV"]["raw_value"]
                watts = raw_val / (10 ** divisor)
                if watts > 1:
                    self._on_state = True
                    self.schedule_update_ha_state()
        elif packet.data[0] == 0xD2:
            # actuator status telegram
            packet.parse_eep(0x01, 0x01)
            if packet.parsed["CMD"]["raw_value"] == 4:
                channel = packet.parsed["IO"]["raw_value"]
                output = packet.parsed["OV"]["raw_value"]
                if (
                    channel == self.channel or self.channel == SWITCH_ALL_CHANNELS
                ):  # my channel or all channels
                    self._on_state = output > 0
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
        return "{0}-{1}".format("switch", to_hex_string(self.dev_id))
