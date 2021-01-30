"""Support for EnOcean devices."""
from typing import Optional
import voluptuous as vol
import asyncio


from homeassistant.config_entries import SOURCE_IMPORT, ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant import config_entries, core
from homeassistant.const import CONF_COVERS, CONF_DEVICE
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.typing import ConfigType

from .const import DATA_ENOCEAN, DOMAIN, ENOCEAN_DONGLE
from .dongle import EnOceanDongle
from .cover import ENOCEAN_COVER_SCHEMA

PLATFORMS = ["cover", "sensor", "switch"]


def _ensure_cover(value):
    if value is None:
        return ENOCEAN_COVER_SCHEMA({})
    return ENOCEAN_COVER_SCHEMA(value)


CONFIG_SCHEMA = vol.Schema(
    {
        DOMAIN: vol.Schema(
            {
                vol.Required(CONF_DEVICE): cv.string,
                vol.Optional(CONF_COVERS): {cv.string, _ensure_cover},
            }
        )
    },
    extra=vol.ALLOW_EXTRA,
)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the EnOcean component."""
    # support for text-based configuration (legacy)
    if DOMAIN not in config:
        return True

    if hass.config_entries.async_entries(DOMAIN):
        # We can only have one dongle. If there is already one in the config,
        # there is no need to import the yaml based config.
        return True

    hass.async_create_task(
        hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_IMPORT}, data=config[DOMAIN]
        )
    )

    return True


async def async_setup_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Set up an EnOcean dongle for the given entry."""
    enocean_data = hass.data.setdefault(DATA_ENOCEAN, {})
    # usb_dongle = EnOceanDongle(hass, config_entry.data[CONF_DEVICE])
    # await usb_dongle.async_setup()
    # enocean_data[ENOCEAN_DONGLE] = usb_dongle

    for platform in PLATFORMS:
        hass.async_create_task(
            hass.config_entries.async_forward_entry_setup(config_entry, platform)
        )

    return True


async def async_unload_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Unload EnOcean config entry."""

    unload_ok = all(
        await asyncio.gather(
            *[
                hass.config_entries.async_forward_entry_unload(config_entry, platform)
                for platform in PLATFORMS
            ]
        )
    )

    enocean_dongle = hass.data[DATA_ENOCEAN].get(ENOCEAN_DONGLE, None)
    if enocean_dongle:
        enocean_dongle.unload()
    hass.data.pop(DATA_ENOCEAN)

    return unload_ok
