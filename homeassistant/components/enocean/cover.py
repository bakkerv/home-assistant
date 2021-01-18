"""Support for EnOcean Covers."""
import logging
from typing import Any

from enocean.protocol.constants import RORG
from enocean.protocol.packet import RadioPacket
import voluptuous as vol

from homeassistant.components import enocean
from homeassistant.components.cover import (
    ATTR_POSITION,
    PLATFORM_SCHEMA,
    SUPPORT_CLOSE,
    SUPPORT_OPEN,
    SUPPORT_SET_POSITION,
    SUPPORT_STOP,
    CoverEntity,
)
from homeassistant.const import CONF_ID, CONF_NAME
import homeassistant.helpers.config_validation as cv
from .const import COVER_ALL_CHANNELS

from .device import EnOceanEntity


_LOGGER = logging.getLogger(__name__)

CONF_SENDER_ID = "sender_id"
CONF_USE_VLD = "use_vld"
CONF_CHANNEL = "channel"

DEFAULT_NAME = "EnOcean Cover"
DEFAULT_USE_VLD = False
SUPPORT_ENOCEAN = SUPPORT_CLOSE | SUPPORT_OPEN | SUPPORT_SET_POSITION | SUPPORT_STOP
VLD_SUPPORT_ENOCEAN = SUPPORT_SET_POSITION | SUPPORT_STOP

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {
        vol.Optional(CONF_ID, default=[]): vol.All(cv.ensure_list, [vol.Coerce(int)]),
        vol.Required(CONF_SENDER_ID): vol.All(cv.ensure_list, [vol.Coerce(int)]),
        vol.Optional(CONF_NAME, default=DEFAULT_NAME): cv.string,
        vol.Optional(CONF_USE_VLD, default=DEFAULT_USE_VLD): cv.boolean,
    }
)

STATE_NO_STATE = 0
STATE_STOPPED = 1
STATE_OPENING = 2
STATE_CLOSING = 3


def setup_platform(hass, config, add_entities, discovery_info=None):
    """Set up the EnOcean cover platform."""
    sender_id = config.get(CONF_SENDER_ID)
    dev_name = config.get(CONF_NAME)
    dev_id = config.get(CONF_ID)
    use_vld = config.get(CONF_USE_VLD)
    channel = config.get(CONF_CHANNEL)

    if use_vld:
        add_entities([EnOceanVldCover(sender_id, dev_id, dev_name, channel)])
    else:
        add_entities([EnOceanCover(sender_id, dev_id, dev_name)])


class EnOceanCover(EnOceanEntity, CoverEntity):
    """Representation of an EnOcean cover source."""

    def __init__(self, sender_id, dev_id, dev_name):
        """Initialize the EnOcean cover source."""
        super().__init__(dev_id, dev_name)
        self.sender_id = sender_id
        self.cover_state = STATE_NO_STATE
        self.closed = False
        self.current_position = None

    @property
    def name(self):
        """Return the name of the device if any."""
        return self.dev_name

    @property
    def supported_features(self):
        """Flag supported features."""
        return SUPPORT_ENOCEAN

    def value_changed(self, packet):
        """Update the internal state of this device."""
        if packet.data[0] == 0xA5:
            packet.parse_eep(0x11, 0x03)
            if "PVF" in packet.parsed:
                # Position data available
                self.current_position = packet.parsed["BSP"]["raw_value"]
            if "EP" in packet.parsed:
                ep = packet.parsed["EP"]["raw_value"]
                if ep == 2:
                    self.closed = False
                if ep == 3:
                    self.closed = True
            if "ST" in packet.parsed:
                self.cover_state = packet.parsed["ST"]["raw_value"]
            self.schedule_update_ha_state()

    @property
    def current_cover_position(self):
        """Return current position of cover. None is unknown, 0 is closed, 100 is fully open."""
        if self.current_position is None:
            self.request_current_state()
            return 100
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
    def is_closed(self):
        """Return if the cover is closed or not."""
        return self.closed

    def open_cover(self, **kwargs: Any) -> None:
        """Open the cover."""
        packet = RadioPacket.create(
            rorg=RORG.BS4,
            rorg_func=0x38,
            rorg_type=0x08,
            sender=self.sender_id,
            destination=self.dev_id,
            command=7,  # Blind
            COM=7,
            FUNC=2,  # Blinds open
            LRNB=1,  # Data telegram
            SSF=1,  # No send new status
            PAF=0,  # No position and angle flag
            SMF=0,  # No service mode
        )
        self.send_packet(packet)

    def close_cover(self, **kwargs: Any) -> None:
        """Close cover."""
        packet = RadioPacket.create(
            rorg=RORG.BS4,
            rorg_func=0x38,
            rorg_type=0x08,
            sender=self.sender_id,
            destination=self.dev_id,
            command=7,  # Blind
            COM=7,
            FUNC=3,  # Blinds close
            LRNB=1,  # Data telegram
            SSF=1,  # No Send new status
            PAF=0,  # No position and angle flag
            SMF=0,  # No service mode
        )
        self.send_packet(packet)

    def set_cover_position(self, **kwargs):
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
            FUNC=4,  # Drive to position
            LRNB=1,  # Data telegram
            SSF=1,  # No Send new status
            PAF=1,  # No position and angle flag
            SMF=0,  # No service mode
            P1=100 - pos,  # Set position
            P2=0,  # No angle
        )
        self.send_packet(packet)

    def stop_cover(self, **kwargs):
        """Stop the cover."""
        packet = RadioPacket.create(
            rorg=RORG.BS4,
            rorg_func=0x38,
            rorg_type=0x08,
            sender=self.sender_id,
            destination=self.dev_id,
            COM=7,
            command=7,  # Blind
            FUNC=1,  # Blinds stop
            LRNB=1,  # Data telegram
            SSF=1,  # Send new status
            PAF=0,  # No position and angle flag
            SMF=0,  # No service mode
        )
        self.send_packet(packet)

    def request_current_state(self):
        """Request current state."""

        packet = RadioPacket.create(
            rorg=RORG.BS4,
            rorg_func=0x38,
            rorg_type=0x08,
            sender=self.sender_id,
            destination=self.dev_id,
            command=7,  # Blind
            COM=7,
            FUNC=0,  # Request status
            LRNB=1,  # Data telegram
            SSF=0,  # Send new status
            PAF=0,  # No position and angle flag
            SMF=0,  # No service mode
        )
        _LOGGER.debug("Requesting current state")
        self.send_packet(packet)


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
        if self.current_position is None:
            self.request_current_state()
            return None
        return 100 - self.current_position

    def set_cover_position(self, **kwargs):
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
        self.send_packet(packet)
        self.target_position = pos

    def stop_cover(self, **kwargs):
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
        self.send_packet(packet)
        self.target_position = None

    def request_current_state(self):
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
        self.send_packet(packet)

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

    def open_cover(self, **kwargs: Any) -> None:
        """Open the cover."""
        self.set_cover_position(position=100)

    def close_cover(self, **kwargs: Any) -> None:
        """Close cover."""
        self.set_cover_position(position=0)
