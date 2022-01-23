"""Support for EnOcean Covers."""
import logging
from typing import Any

from enocean.protocol.constants import RORG
from enocean.protocol.packet import RadioPacket
from enocean.utils import to_hex_string
import voluptuous as vol

from homeassistant.components import enocean
from homeassistant.components.cover import (
    ATTR_POSITION,
    ATTR_TILT_POSITION,
    PLATFORM_SCHEMA,
    SUPPORT_CLOSE,
    SUPPORT_OPEN,
    SUPPORT_SET_POSITION,
    SUPPORT_SET_TILT_POSITION,
    SUPPORT_STOP,
    CoverEntity,
)
from homeassistant.const import CONF_COVERS, CONF_ID, CONF_NAME
import homeassistant.helpers.config_validation as cv

from .device import EnOceanEntity

_LOGGER = logging.getLogger(__name__)

CONF_SENDER_ID = "sender_id"
CONF_USE_VLD = "use_vld"
CONF_CHANNEL = "channel"
CONF_TILT_SUPPORT = "tilt"

DEFAULT_NAME = "EnOcean Cover"
DEFAULT_USE_VLD = False
DEFAULT_TILT_SUPPORT = False
SUPPORT_ENOCEAN = SUPPORT_CLOSE | SUPPORT_OPEN | SUPPORT_SET_POSITION | SUPPORT_STOP
VLD_SUPPORT_ENOCEAN = SUPPORT_SET_POSITION | SUPPORT_STOP


ENOCEAN_COVER_SCHEMA_DATA = {
    vol.Optional(CONF_ID, default=[]): vol.All(cv.ensure_list, [vol.Coerce(int)]),
    vol.Required(CONF_SENDER_ID): vol.All(cv.ensure_list, [vol.Coerce(int)]),
    vol.Optional(CONF_NAME, default=DEFAULT_NAME): cv.string,
    vol.Optional(CONF_USE_VLD, default=DEFAULT_USE_VLD): cv.boolean,
    vol.Optional(CONF_TILT_SUPPORT, default=DEFAULT_TILT_SUPPORT): cv.boolean,
}

ENOCEAN_COVER_SCHEMA = vol.Schema(ENOCEAN_COVER_SCHEMA_DATA)


PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(ENOCEAN_COVER_SCHEMA_DATA)

STATE_NO_STATE = 0
STATE_STOPPED = 1
STATE_OPENING = 2
STATE_CLOSING = 3

A5_FUNCTION_STATUS_REQUEST = 0
A5_FUNCTION_BLIND_STOP = 1
A5_FUNCTION_BLIND_OPEN = 2
A5_FUNCTION_BLIND_CLOSE = 3
A5_FUNCTION_TO_POSITION = 4


async def async_setup_entry(
    hass,
    config_entry,
    async_add_entities,
):
    """Set up config entry."""

    # Add cover from config file
    config_data = config_entry.data
    entities = []
    if CONF_COVERS not in config_data:
        return
    for entity_info in config_data[CONF_COVERS].values():
        entity = create_entity_from_config(entity_info)
        entities.append(entity)

    async_add_entities(entities)


def create_entity_from_config(config):
    """Create cover entity from configuration."""
    sender_id = config.get(CONF_SENDER_ID)
    dev_name = config.get(CONF_NAME)
    dev_id = config.get(CONF_ID)
    use_vld = config.get(CONF_USE_VLD)
    channel = config.get(CONF_CHANNEL)
    tilt_support = config.get(CONF_TILT_SUPPORT)

    if use_vld:
        return EnOceanVldCover(sender_id, dev_id, dev_name, channel)
    else:
        return EnOceanCover(sender_id, dev_id, dev_name, tilt_support)


def setup_platform(hass, config, add_entities, discovery_info=None):
    """Set up the EnOcean cover platform."""
    return add_entities([create_entity_from_config(config)])


class EnOceanCover(EnOceanEntity, CoverEntity):
    """Representation of an EnOcean cover source."""

    def __init__(self, sender_id, dev_id, dev_name, tilt_support=False):
        """Initialize the EnOcean cover source."""
        super().__init__(dev_id, dev_name)
        self.sender_id = sender_id
        self.cover_state = STATE_NO_STATE
        self.closed = None
        self.current_position = None
        self.tilt_support = tilt_support
        self.tilt = None

    @property
    def name(self):
        """Return the name of the device if any."""
        return self.dev_name

    @property
    def supported_features(self):
        """Flag supported features."""
        if self.tilt_support:
            return SUPPORT_ENOCEAN | SUPPORT_SET_TILT_POSITION
        return SUPPORT_ENOCEAN

    def value_changed(self, packet):
        """Update the internal state of this device."""
        if packet.data[0] == 0xA5:
            packet.parse_eep(0x11, 0x03)
            if "PVF" in packet.parsed and packet.parsed["PVF"]["raw_value"] == 1:
                # Position data available
                mode_of_position = 0  # normal mode as default
                if "MOTP" in packet.parsed:
                    mode_of_position = packet.parsed["MOTP"]["raw_value"]
                if mode_of_position == 0:  # Normal mode
                    self.current_position = packet.parsed["BSP"]["raw_value"]
                else:
                    self.current_position = 100 - packet.parsed["BSP"]["raw_value"]
                _LOGGER.debug(
                    "Updated position %d %d %d",
                    mode_of_position,
                    packet.parsed["BSP"]["raw_value"],
                    self.current_position,
                )
            if "AVF" in packet.parsed and packet.parsed["AVF"]["raw_value"] == 1:
                angle_sign = packet.parsed["AS"]["raw_value"]  # 0 positive, 1 negative
                # Angle 0 - 180
                angle_value = packet.parsed["AV"]["value"]
                self.tilt = self.angle_to_tilt(
                    angle_value * 1 if angle_sign == 0 else -1
                )
            if "EP" in packet.parsed:
                end_position = packet.parsed["EP"]["raw_value"]  # EP = End Position
                if end_position == 2:
                    self.closed = False
                if end_position == 3:
                    self.closed = True
            if "ST" in packet.parsed:
                self.cover_state = packet.parsed["ST"]["raw_value"]
            self.schedule_update_ha_state()

    def angle_to_tilt(self, angle):
        """Transform an angle between -180 and 180 to an tile value (0--100)."""
        # -180 == shut, 180 == open
        # HA: 0 == closed, 100 == open
        if angle < -180 or angle > 180:
            return 0
        return int((angle + 180) / 3.6)

    def tilt_to_angle(self, tilt):
        """Transform an tilt value (0--100) to an angle between -180 and 180."""
        if tilt is None or tilt > 100 or tilt < 0:
            return 0
        return int((tilt * 3.6) - 180)

    def encode_angle(self, tilt: int) -> int:
        """Encode the tilt."""
        angle = self.tilt_to_angle(tilt)
        # angle -180 .. 180
        first_bit = 0x0 if angle >= 0 else 0x80
        return first_bit | (abs(angle) >> 1)

    @property
    def current_cover_position(self):
        """Return current position of cover. None is unknown, 0 is closed, 100 is fully open."""
        if self.current_position is None:
            return None
        return 100 - self.current_position

    @property
    def is_opening(self):
        """Return if the cover is opening or not."""
        return self.cover_state == STATE_OPENING

    @property
    def is_closing(self):
        """Return if the cover is closing or not."""
        return self.cover_state == STATE_CLOSING

    @property
    def current_cover_tilt_position(self):
        """Return current cover tilt position."""
        return self.tilt

    @property
    def is_closed(self):
        """Return if the cover is closed or not."""
        return self.closed

    async def async_open_cover(self, **kwargs: Any) -> None:
        """Open the cover."""
        packet = RadioPacket.create(
            rorg=RORG.BS4,
            rorg_func=0x38,
            rorg_type=0x08,
            sender=self.sender_id,
            destination=self.dev_id,
            command=7,  # Blind
            COM=7,
            FUNC=A5_FUNCTION_BLIND_OPEN,  # Blinds open
            LRNB=1,  # Data telegram
            SSF=1,  # No send new status
            PAF=0,  # No position and angle flag
            SMF=0,  # No service mode
        )
        await self.async_send_packet(packet)

    async def async_close_cover(self, **kwargs: Any) -> None:
        """Close cover."""
        packet = RadioPacket.create(
            rorg=RORG.BS4,
            rorg_func=0x38,
            rorg_type=0x08,
            sender=self.sender_id,
            destination=self.dev_id,
            command=7,  # Blind
            COM=7,
            FUNC=A5_FUNCTION_BLIND_CLOSE,  # Blinds close
            LRNB=1,  # Data telegram
            SSF=1,  # No Send new status
            PAF=0,  # No position and angle flag
            SMF=0,  # No service mode
        )
        self.send_packet(packet)

    async def async_set_cover_position(self, **kwargs):
        """Move the cover to a specific position."""
        pos = kwargs[ATTR_POSITION]
        if pos < 0 or pos > 100:
            return
        packet = RadioPacket.create(
            rorg=RORG.BS4,
            rorg_func=0x38,
            rorg_type=0x08,
            sender=self.sender_id,
            destination=self.dev_id,
            command=7,  # Blind
            COM=7,
            FUNC=A5_FUNCTION_TO_POSITION,  # Drive to position
            LRNB=1,  # Data telegram
            SSF=1,  # No Send new status
            PAF=1,  # No position and angle flag
            SMF=0,  # No service mode
            P1=100 - pos,  # Set position
            P2=self.encode_angle(self.tilt),  # angle
        )
        await self.async_send_packet(packet)

    async def async_set_cover_tilt_position(self, **kwargs):
        """Move the cover tilt to a specific position."""
        tilt = kwargs[ATTR_TILT_POSITION]
        if tilt < 0 or tilt > 100:
            return
        packet = RadioPacket.create(
            rorg=RORG.BS4,
            rorg_func=0x38,
            rorg_type=0x08,
            sender=self.sender_id,
            destination=self.dev_id,
            command=7,  # Blind
            COM=7,
            FUNC=A5_FUNCTION_TO_POSITION,  # Drive to position
            LRNB=1,  # Data telegram
            SSF=1,  # No Send new status
            PAF=1,  # No position and angle flag
            SMF=0,  # No service mode
            P1=100 - self.current_cover_position
            if self.current_cover_position
            else 0,  # Set position
            P2=self.encode_angle(self.tilt),  # angle
        )
        await self.async_send_packet(packet)

    async def async_stop_cover(self, **kwargs):
        """Stop the cover."""
        packet = RadioPacket.create(
            rorg=RORG.BS4,
            rorg_func=0x38,
            rorg_type=0x08,
            sender=self.sender_id,
            destination=self.dev_id,
            COM=7,
            command=7,  # Blind
            FUNC=A5_FUNCTION_BLIND_STOP,  # Blinds stop
            LRNB=1,  # Data telegram
            SSF=1,  # Send new status
            PAF=0,  # No position and angle flag
            SMF=0,  # No service mode
        )
        await self.async_send_packet(packet)

    async def async_update(self):
        """Update state."""
        await self.async_request_current_state()

    async def async_request_current_state(self):
        """Request current state."""

        packet = RadioPacket.create(
            rorg=RORG.BS4,
            rorg_func=0x38,
            rorg_type=0x08,
            sender=self.sender_id,
            destination=self.dev_id,
            command=7,  # Blind
            COM=7,
            FUNC=A5_FUNCTION_STATUS_REQUEST,  # Request status
            LRNB=1,  # Data telegram
            SSF=0,  # Send new status
            PAF=0,  # No position and angle flag
            SMF=0,  # No service mode
        )
        _LOGGER.debug("Requesting current state")
        await self.async_send_packet(packet)

    @property
    def device_info(self):
        """Provide device info."""
        return {
            "identifiers": {
                # Serial numbers are unique identifiers within a specific domain
                (enocean.DOMAIN, self.unique_id)
            },
            "name": self.name,
        }

    @property
    def unique_id(self):
        """Provide unique identifier."""
        return f"cover-{to_hex_string(self.dev_id)}"


class EnOceanVldCover(EnOceanEntity, CoverEntity):
    """Representation of an EnOcean cover source."""

    def __init__(self, sender_id, dev_id, dev_name, channel):
        """Initialize the EnOcean cover source."""
        super().__init__(dev_id, dev_name)
        self.sender_id = sender_id
        self.current_position = None
        self.target_position = None
        self.channel = channel

    @property
    def name(self):
        """Return the name of the device if any."""
        return self.dev_name

    @property
    def supported_features(self):
        """Flag supported features."""
        return SUPPORT_ENOCEAN

    @property
    def is_closed(self):
        """Return if the cover is closed or not."""
        if self.current_cover_position is None:
            return None
        return self.current_cover_position == 0

    def value_changed(self, packet):
        """Update the internal state of this device."""
        if packet.data[0] == 0xD2:
            packet.parse_eep(0x05, 0x00)
            if "POS" in packet.parsed:
                # Position data available
                self.current_position = packet.parsed["POS"]["raw_value"]
            self.schedule_update_ha_state()

    @property
    def current_cover_position(self):
        """Return current position of cover. None is unknown, 0 is closed, 100 is fully open."""
        # Within protocol, 0 = up, 100 = down
        if self.current_position is None:
            return None
        return 100 - self.current_position

    async def async_set_cover_position(self, **kwargs):
        """Move the cover to a specific position."""
        pos = kwargs[ATTR_POSITION]
        if pos < 0 or pos > 100:
            return
        packet = RadioPacket.create(
            rorg=RORG.VLD,
            rorg_func=0x05,
            rorg_type=0x00,
            sender=self.sender_id,
            destination=self.dev_id,
            command=1,  # Set position & angle
            POS=100 - pos,  # Set position
            ANG=127,  # No angle change
            REPO=0,  # Go directly to position/angle
            LOCK=0,  # No change
            CHN=0,  # set channel, fixed to channel 1
        )
        await self.async_send_packet(packet)
        self.target_position = pos

    async def async_stop_cover(self, **kwargs):
        """Stop the cover."""
        packet = RadioPacket.create(
            rorg=RORG.VLD,
            rorg_func=0x05,
            rorg_type=0x00,
            sender=self.sender_id,
            destination=self.dev_id,
            command=2,  # Stop
            CHN=0,  # set channel, fixed to channel 1
        )
        await self.async_send_packet(packet)
        self.target_position = None

    async def async_request_current_state(self):
        """Request current state."""

        packet = RadioPacket.create(
            rorg=RORG.VLD,
            rorg_func=0x05,
            rorg_type=0x00,
            sender=self.sender_id,
            destination=self.dev_id,
            command=3,  # Query Position & Angle
            CHN=0,  # set channel, fixed to channel 1
        )
        _LOGGER.debug("Requesting current state")
        await self.async_send_packet(packet)

    @property
    def is_opening(self):
        """Return if the cover is opening or not."""
        if self.current_cover_position is None:
            return None
        if self.target_position is None:
            return False
        return self.current_cover_position < self.target_position

    @property
    def is_closing(self):
        """Return if the cover is closing or not."""
        if self.current_cover_position is None:
            return None
        if self.target_position is None:
            return False
        return self.current_cover_position > self.target_position

    async def async_open_cover(self, **kwargs: Any) -> None:
        """Open the cover."""
        await self.async_set_cover_position(position=100)

    async def async_close_cover(self, **kwargs: Any) -> None:
        """Close cover."""
        await self.async_set_cover_position(position=0)

    @property
    def device_info(self):
        """Return device information."""
        return {
            "identifiers": {
                # Serial numbers are unique identifiers within a specific domain
                (enocean.DOMAIN, self.unique_id)
            },
            "name": self.name,
        }

    @property
    def unique_id(self):
        """Return unique identifier."""
        return f"cover-{to_hex_string(self.dev_id)}"

    async def async_update(self):
        """Update state."""
        await self.async_request_current_state()
