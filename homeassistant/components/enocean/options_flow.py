from homeassistant.components.command_line.cover import COVER_SCHEMA
from homeassistant.const import (
    CONF_COVERS,
    CONF_DEVICE,
    CONF_ID,
    CONF_LIGHTS,
    CONF_NAME,
    CONF_SENSORS,
    CONF_SWITCHES,
)
from homeassistant import config_entries, exceptions
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import callback
from enocean.utils import from_hex_string, to_hex_string
import copy


from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry
from homeassistant.helpers.device_registry import (
    async_entries_for_config_entry,
    async_get_registry as async_get_device_registry,
)
from homeassistant.helpers.entity_registry import (
    async_entries_for_device,
    async_get_registry as async_get_entity_registry,
)
import voluptuous as vol
import logging

from .const import DOMAIN
from .cover import (
    ENOCEAN_COVER_SCHEMA_DATA,
    ENOCEAN_COVER_SCHEMA,
    CONF_SENDER_ID,
    CONF_USE_VLD,
)
from .sensor import (
    CONF_DEVICE_CLASS,
    CONF_MIN_TEMP,
    CONF_MAX_TEMP,
    CONF_RANGE_FROM,
    CONF_RANGE_TO,
    SENSOR_TYPES,
    SENSOR_SCHEMA,
)

from .switch import CONF_CHANNEL, SWITCH_SCHEMA, SWITCH_ALL_CHANNELS
from .light import LIGHT_SCHEMA

_LOGGER = logging.getLogger(__name__)


ADD_KEY = "add_selection"
EDIT_KEY = "edit_selection"
REMOVE_KEY = "remove_selection"

CONF_ALL_CHANNELS = "all_channels"

PLATFORM_LIGHT = "light"
PLATFORM_SENSOR = "sensor"
PLATFORM_COVER = "cover"
PLATFORM_SWITCH = "switch"
PLATFORMS = [PLATFORM_SENSOR, PLATFORM_COVER, PLATFORM_LIGHT, PLATFORM_SWITCH]


class OptionsFlowHandler(config_entries.OptionsFlow):
    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        super().__init__()
        self._config_entry = config_entry
        self._selected_device_entry_id = None
        self._device_entries = None
        self._device_registry = None
        self._current_dev_config = None
        self._current_dev_config_key = None

    def is_device_type(self, identifiers: set, expected_type: str):
        return self.get_enocean_id(identifiers, expected_type) is not None

    def get_enocean_id(self, identifiers: set, expected_type: str):
        for id in identifiers:
            if len(id) == 2 and expected_type in id[1]:
                identifier_string = id[1]
                return identifier_string.split("-")[1]
        return None

    async def async_step_init(self, user_input=None):
        """Manage the options."""
        if user_input is not None:
            if ADD_KEY in user_input:
                if user_input[ADD_KEY] == PLATFORM_COVER:
                    return await self.async_step_create_cover()
                if user_input[ADD_KEY] == PLATFORM_SWITCH:
                    return await self.async_step_create_switch()
                if user_input[ADD_KEY] == PLATFORM_SENSOR:
                    return await self.async_step_create_sensor()
                if user_input[ADD_KEY] == PLATFORM_LIGHT:
                    return await self.async_step_create_light()
            if EDIT_KEY in user_input:
                if user_input[EDIT_KEY] == PLATFORM_SENSOR:
                    return await self.async_step_select_sensor()
                if user_input[EDIT_KEY] == PLATFORM_COVER:
                    return await self.async_step_select_cover()
                if user_input[EDIT_KEY] == PLATFORM_SWITCH:
                    return await self.async_step_select_switch()
                if user_input[EDIT_KEY] == PLATFORM_LIGHT:
                    return await self.async_step_select_light()
            if REMOVE_KEY in user_input:
                if user_input[REMOVE_KEY] == PLATFORM_SENSOR:
                    return await self.async_step_select_sensor_to_remove()
                if user_input[REMOVE_KEY] == PLATFORM_COVER:
                    return await self.async_step_select_cover_to_remove()
                if user_input[REMOVE_KEY] == PLATFORM_SWITCH:
                    return await self.async_step_select_switch_to_remove()
                if user_input[REMOVE_KEY] == PLATFORM_LIGHT:
                    return await self.async_step_select_light_to_remove()

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(ADD_KEY): vol.In(PLATFORMS),
                    vol.Optional(EDIT_KEY): vol.In(PLATFORMS),
                    vol.Optional(REMOVE_KEY): vol.In(PLATFORMS),
                },
            ),
        )

    async def async_step_create_cover(self, user_input=None):
        """Add new cover step"""
        errors = {}
        if user_input is not None:
            dev_id = self.device_id_or_none(user_input[CONF_ID])
            if dev_id is None:
                errors[CONF_ID] = "invalid_id"
            if (
                CONF_COVERS in self._config_entry.data
                and to_hex_string(dev_id) in self._config_entry.data[CONF_COVERS]
            ):
                errors[CONF_ID] = "id_in_use"
            sender_id = self.device_id_or_none(user_input[CONF_SENDER_ID])
            if sender_id is None:
                errors[CONF_SENDER_ID] = "invalid_sender_id"
            try:
                if not errors:
                    data = ENOCEAN_COVER_SCHEMA(
                        {
                            CONF_SENDER_ID: sender_id,
                            CONF_NAME: user_input[CONF_NAME],
                            CONF_USE_VLD: user_input[CONF_USE_VLD],
                            CONF_ID: dev_id,
                        }
                    )
            except vol.error.Error:
                errors["base"] = "invalid_data"
            if not errors:
                self.update_config_data(covers={to_hex_string(dev_id): data})  # type: ignore
                return self.async_create_entry(title="", data=None)
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_ID, description={"suggested_value": "0xff,0xff,0xff,0xff"}
                ): cv.string,
                vol.Required(
                    CONF_SENDER_ID,
                    description={"suggested_value": "0xff,0xff,0xff,0xff"},
                ): cv.string,
                vol.Required(CONF_NAME): cv.string,
                vol.Optional(CONF_USE_VLD, default=False): cv.boolean,
            }
        )
        return self.async_show_form(
            step_id="create_cover", data_schema=schema, errors=errors
        )

    async def async_step_create_light(self, user_input=None):
        """Add new light step"""
        errors = {}
        if user_input is not None:
            dev_id = self.device_id_or_none(user_input[CONF_ID])
            if dev_id is None:
                errors[CONF_ID] = "invalid_id"
            if (
                CONF_LIGHTS in self._config_entry.data
                and to_hex_string(dev_id) in self._config_entry.data[CONF_LIGHTS]
            ):
                errors[CONF_ID] = "id_in_use"
            sender_id = self.device_id_or_none(user_input[CONF_SENDER_ID])
            if sender_id is None:
                errors[CONF_SENDER_ID] = "invalid_sender_id"
            user_input[CONF_ID] = dev_id
            user_input[CONF_SENDER_ID] = sender_id
            try:
                if not errors:
                    data = LIGHT_SCHEMA(user_input)
            except vol.error.Error:
                errors["base"] = "invalid_data"
            if not errors:
                self.update_config_data(lights={to_hex_string(dev_id): data})  # type: ignore
                return self.async_create_entry(title="", data=None)
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_ID, description={"suggested_value": "0xff,0xff,0xff,0xff"}
                ): cv.string,
                vol.Required(
                    CONF_SENDER_ID,
                    description={"suggested_value": "0xff,0xff,0xff,0xff"},
                ): cv.string,
                vol.Required(CONF_NAME): cv.string,
            }
        )
        return self.async_show_form(
            step_id="create_light", data_schema=schema, errors=errors
        )

    async def async_step_create_sensor(self, user_input=None):
        """Add new sensor step"""
        errors = {}
        if user_input is not None:
            dev_id = self.device_id_or_none(user_input[CONF_ID])
            if dev_id is None:
                errors[CONF_ID] = "invalid_id"
            user_input[CONF_ID] = dev_id
            if (
                CONF_SENSORS in self._config_entry.data
                and to_hex_string(dev_id) in self._config_entry.data[CONF_SENSORS]
            ):
                errors[CONF_ID] = "id_in_use"
            try:
                if not errors:
                    data = SENSOR_SCHEMA(user_input)
            except vol.error.Error:
                errors["base"] = "invalid_data"
            if not errors:
                self.update_config_data(sensors={to_hex_string(dev_id): data})  # type: ignore
                return self.async_create_entry(title="", data=None)
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_ID, description={"suggested_value": "0xff,0xff,0xff,0xff"}
                ): cv.string,
                vol.Required(CONF_NAME): cv.string,
                vol.Required(CONF_DEVICE_CLASS): vol.In(SENSOR_TYPES.keys()),
                vol.Optional(CONF_MAX_TEMP): vol.Coerce(int),
                vol.Optional(CONF_MIN_TEMP): vol.Coerce(int),
                vol.Optional(CONF_RANGE_FROM): cv.positive_int,
                vol.Optional(CONF_RANGE_TO): cv.positive_int,
            }
        )
        return self.async_show_form(
            step_id="create_sensor", data_schema=schema, errors=errors
        )

    async def async_step_create_switch(self, user_input=None):
        """Add new switch step"""
        errors = {}
        if user_input is not None:
            dev_id = self.device_id_or_none(user_input[CONF_ID])
            if dev_id is None:
                errors[CONF_ID] = "invalid_id"
            if (
                CONF_SWITCHES in self._config_entry.data
                and to_hex_string(dev_id) in self._config_entry.data[CONF_SWITCHES]
            ):
                errors[CONF_ID] = "id_in_use"
            sender_id = self.device_id_or_none(user_input[CONF_SENDER_ID])
            if sender_id is None:
                errors[CONF_SENDER_ID] = "invalid_sender_id"
            user_input[CONF_ID] = dev_id
            user_input[CONF_SENDER_ID] = sender_id
            if user_input[CONF_ALL_CHANNELS]:
                user_input[CONF_CHANNEL] = SWITCH_ALL_CHANNELS
            user_input.pop(CONF_ALL_CHANNELS, None)
            try:
                if not errors:
                    data = SWITCH_SCHEMA(user_input)
            except vol.error.Error:
                errors["base"] = "invalid_data"
            if not errors:
                self.update_config_data(switches={to_hex_string(dev_id): data})  # type: ignore
                return self.async_create_entry(title="", data=None)
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_ID, description={"suggested_value": "0xff,0xff,0xff,0xff"}
                ): cv.string,
                vol.Required(
                    CONF_SENDER_ID,
                    description={"suggested_value": "0xff,0xff,0xff,0xff"},
                ): cv.string,
                vol.Required(CONF_NAME): cv.string,
                vol.Optional(CONF_CHANNEL, default=0): vol.All(
                    int, vol.Range(min=0, max=29)
                ),
                vol.Optional(CONF_ALL_CHANNELS): cv.boolean,
            }
        )
        return self.async_show_form(
            step_id="create_switch", data_schema=schema, errors=errors
        )

    async def async_step_select_cover(self, user_input=None):
        return await self.async_step_select_device(
            "cover",
            self.async_step_set_cover_options,
            "select_cover",
            user_input=user_input,
        )

    async def async_step_select_cover_to_remove(self, user_input=None):
        return await self.async_step_select_device(
            "cover",
            self.async_step_remove_cover,
            "select_cover_to_remove",
            user_input=user_input,
        )

    async def async_step_select_switch_to_remove(self, user_input=None):
        return await self.async_step_select_device(
            "switch",
            self.async_step_remove_switch,
            "select_switch_to_remove",
            user_input=user_input,
        )

    async def async_step_select_light_to_remove(self, user_input=None):
        return await self.async_step_select_device(
            "light",
            self.async_step_remove_light,
            "select_light_to_remove",
            user_input=user_input,
        )

    async def async_step_select_sensor_to_remove(self, user_input=None):
        return await self.async_step_select_device(
            "sensor",
            self.async_step_remove_sensor,
            "select_sensor_to_remove",
            user_input=user_input,
        )

    async def async_step_select_light(self, user_input=None):
        return await self.async_step_select_device(
            "light",
            self.async_step_set_light_options,
            "select_light",
            user_input=user_input,
        )

    async def async_step_select_device(
        self, device_type, set_options_step, step_id, user_input=None
    ):
        """Select a device."""
        DEVICE = "device"
        if user_input is not None:
            if DEVICE in user_input:
                self._selected_device_entry_id = user_input[DEVICE]
                return await set_options_step()

            return self.async_create_entry(title="", data=user_input)

        device_registry = await async_get_device_registry(self.hass)
        device_entries = async_entries_for_config_entry(
            device_registry, self._config_entry.entry_id
        )
        self._device_registry = device_registry
        self._device_entries = device_entries

        configure_devices = {
            entry.id: entry.name_by_user if entry.name_by_user else entry.name
            for entry in device_entries
            if self.is_device_type(entry.identifiers, device_type)
        }

        return self.async_show_form(
            step_id=step_id,
            data_schema=vol.Schema(
                {
                    vol.Optional(DEVICE): vol.In(configure_devices),
                }
            ),
        )

    async def async_step_select_sensor(self, user_input=None):
        return await self.async_step_select_device(
            "sensor",
            self.async_step_set_sensor_options,
            "select_sensor",
            user_input=user_input,
        )

    async def async_step_select_switch(self, user_input=None):
        return await self.async_step_select_device(
            "switch",
            self.async_step_set_switch_options,
            "select_switch",
            user_input=user_input,
        )

    def find_matching_config(self, device_type, config_key):
        device_id = self._selected_device_entry_id
        # find matching device entity to extract device id (part of unique id)
        for matching_device in filter(
            lambda x: x.id == device_id, self._device_entries
        ):
            # self._config_entry.data[CONF_COVERS]
            id = self.get_enocean_id(matching_device.identifiers, device_type)
            if id in self._config_entry.data[config_key]:
                # for matching_config in filter(
                #     lambda x: list(map(lambda x: hex(x), x[CONF_ID]))
                #     == self.get_enocean_id(matching_device.identifiers, "cover"),
                #     self._config_entry.data[CONF_COVERS],
                # ):
                self._current_dev_config = self._config_entry.data[config_key][id]
                self._current_dev_config_key = id
                return
        self._current_dev_config = None
        self._current_dev_config_key = None

    def device_id_or_none(self, input):
        sender_id = []
        try:
            sender_id = list(map(lambda x: int(x, 16), input.split(",")))
            # should be a valid number as well
            if not all(map(lambda x: x >= 0 and x <= 255, sender_id)):
                return None
        except ValueError:
            return None
        return sender_id

    async def async_step_remove_cover(self, user_input=None):
        self.find_matching_config("cover", CONF_COVERS)
        if self._current_dev_config_key is not None:
            self._device_registry.async_remove_device(self._selected_device_entry_id)
            self.update_config_data(covers={self._current_dev_config_key: None})

        return self.async_create_entry(title="", data=None)

    async def async_step_remove_switch(self, user_input=None):
        self.find_matching_config("switch", CONF_SWITCHES)
        if self._current_dev_config_key is not None:
            self._device_registry.async_remove_device(self._selected_device_entry_id)
            self.update_config_data(switches={self._current_dev_config_key: None})
        return self.async_create_entry(title="", data=None)

    async def async_step_remove_light(self, user_input=None):
        self.find_matching_config("light", CONF_LIGHTS)
        if self._current_dev_config_key is not None:
            self._device_registry.async_remove_device(self._selected_device_entry_id)
            self.update_config_data(lights={self._current_dev_config_key: None})
        return self.async_create_entry(title="", data=None)

    async def async_step_remove_sensor(self, user_input=None):
        self.find_matching_config("sensor", CONF_SENSORS)
        if self._current_dev_config_key is not None:
            self._device_registry.async_remove_device(self._selected_device_entry_id)
            self.update_config_data(sensors={self._current_dev_config_key: None})
        return self.async_create_entry(title="", data=None)

    async def async_step_set_cover_options(self, user_input=None):
        errors = {}
        self.find_matching_config("cover", CONF_COVERS)
        if user_input is not None and self._current_dev_config_key is not None:
            sender_id = self.device_id_or_none(user_input[CONF_SENDER_ID])
            if sender_id is None:
                errors[CONF_SENDER_ID] = "invalid_sender_id"
            name = user_input[CONF_NAME]
            use_vld = user_input[CONF_USE_VLD]
            try:
                if not errors:
                    data = ENOCEAN_COVER_SCHEMA(
                        {
                            CONF_SENDER_ID: sender_id,
                            CONF_NAME: name,
                            CONF_USE_VLD: use_vld,
                            CONF_ID: self._current_dev_config[CONF_ID],
                        }
                    )
            except vol.error.Error:
                errors["base"] = "invalid_data"
            if not errors:
                self.update_config_data(covers={self._current_dev_config_key: data})  # type: ignore
                return self.async_create_entry(title="", data=None)
        if self._current_dev_config is not None:
            schema = vol.Schema(
                {
                    vol.Required(
                        CONF_SENDER_ID,
                        default=",".join(
                            map(
                                lambda x: hex(x),
                                self._current_dev_config[CONF_SENDER_ID],
                            )
                        ),
                    ): cv.string,
                    vol.Required(
                        CONF_NAME,
                        default=self._current_dev_config[CONF_NAME],
                    ): cv.string,
                    vol.Optional(
                        CONF_USE_VLD,
                        default=self._current_dev_config.get(CONF_USE_VLD, False),
                    ): cv.boolean,
                }
            )

            return self.async_show_form(
                step_id="set_cover_options", data_schema=schema, errors=errors
            )
        return self.async_create_entry(title="", data=None)

    async def async_step_set_sensor_options(self, user_input=None):
        errors = {}
        self.find_matching_config("sensor", CONF_SENSORS)
        if user_input is not None and self._current_dev_config_key is not None:
            # Test schema
            try:
                user_input[CONF_ID] = self._current_dev_config[CONF_ID]
                data = SENSOR_SCHEMA(user_input)
            except vol.error.Error:
                errors["base"] = "invalid_data"
            if not errors:
                self.update_config_data(sensors={self._current_dev_config_key: data})  # type: ignore
                return self.async_create_entry(title="", data=None)
        if self._current_dev_config is not None:
            schema = vol.Schema(
                {
                    vol.Required(
                        CONF_NAME, default=self._current_dev_config[CONF_NAME]
                    ): cv.string,
                    vol.Required(
                        CONF_DEVICE_CLASS,
                        default=self._current_dev_config[CONF_DEVICE_CLASS],
                    ): vol.In(SENSOR_TYPES.keys()),
                    vol.Optional(
                        CONF_MAX_TEMP, default=self._current_dev_config[CONF_MAX_TEMP]
                    ): vol.Coerce(int),
                    vol.Optional(
                        CONF_MIN_TEMP, default=self._current_dev_config[CONF_MIN_TEMP]
                    ): vol.Coerce(int),
                    vol.Optional(
                        CONF_RANGE_FROM,
                        default=self._current_dev_config[CONF_RANGE_FROM],
                    ): cv.positive_int,
                    vol.Optional(
                        CONF_RANGE_TO, default=self._current_dev_config[CONF_RANGE_TO]
                    ): cv.positive_int,
                }
            )
            return self.async_show_form(
                step_id="set_sensor_options", data_schema=schema, errors=errors
            )
        return self.async_create_entry(title="", data=None)

    async def async_step_set_switch_options(self, user_input=None):
        errors = {}
        self.find_matching_config("switch", CONF_SWITCHES)
        if user_input is not None and self._current_dev_config_key is not None:
            # Test schema
            try:
                user_input[CONF_ID] = self._current_dev_config[CONF_ID]
                sender_id = self.device_id_or_none(user_input[CONF_SENDER_ID])
                if sender_id is None:
                    errors[CONF_SENDER_ID] = "invalid_sender_id"
                user_input[CONF_SENDER_ID] = sender_id
                if user_input[CONF_ALL_CHANNELS]:
                    user_input[CONF_CHANNEL] = SWITCH_ALL_CHANNELS
                user_input.pop(CONF_ALL_CHANNELS, None)
                data = SWITCH_SCHEMA(user_input)
            except vol.error.Error:
                errors["base"] = "invalid_data"
            if not errors:
                self.update_config_data(switches={self._current_dev_config_key: data})  # type: ignore
                return self.async_create_entry(title="", data=None)
        if self._current_dev_config is not None:
            if self._current_dev_config[CONF_CHANNEL] == SWITCH_ALL_CHANNELS:
                all_channels = True
                channel_number = 0
            else:
                all_channels = False
                channel_number = self._current_dev_config[CONF_CHANNEL]
            schema = vol.Schema(
                {
                    vol.Required(
                        CONF_SENDER_ID,
                        default=",".join(
                            map(
                                lambda x: hex(x),
                                self._current_dev_config[CONF_SENDER_ID],
                            )
                        ),
                    ): cv.string,
                    vol.Required(
                        CONF_NAME, default=self._current_dev_config[CONF_NAME]
                    ): cv.string,
                    vol.Optional(CONF_CHANNEL, default=channel_number): vol.All(
                        int, vol.Range(min=0, max=29)
                    ),
                    vol.Optional(CONF_ALL_CHANNELS, default=all_channels): cv.boolean,
                }
            )
            return self.async_show_form(
                step_id="set_switch_options", data_schema=schema, errors=errors
            )
        return self.async_create_entry(title="", data=None)

    async def async_step_set_light_options(self, user_input=None):
        errors = {}
        self.find_matching_config("light", CONF_LIGHTS)
        if user_input is not None and self._current_dev_config_key is not None:
            # Test schema
            try:
                user_input[CONF_ID] = self._current_dev_config[CONF_ID]
                sender_id = self.device_id_or_none(user_input[CONF_SENDER_ID])
                if sender_id is None:
                    errors[CONF_SENDER_ID] = "invalid_sender_id"
                user_input[CONF_SENDER_ID] = sender_id
                data = LIGHT_SCHEMA(user_input)
            except vol.error.Error:
                errors["base"] = "invalid_data"
            if not errors:
                self.update_config_data(lights={self._current_dev_config_key: data})  # type: ignore
                return self.async_create_entry(title="", data=None)
        if self._current_dev_config is not None:
            schema = vol.Schema(
                {
                    vol.Required(
                        CONF_SENDER_ID,
                        default=",".join(
                            map(
                                lambda x: hex(x),
                                self._current_dev_config[CONF_SENDER_ID],
                            )
                        ),
                    ): cv.string,
                    vol.Required(
                        CONF_NAME, default=self._current_dev_config[CONF_NAME]
                    ): cv.string,
                }
            )
            return self.async_show_form(
                step_id="set_light_options", data_schema=schema, errors=errors
            )
        return self.async_create_entry(title="", data=None)

    @callback
    def update_config_data(
        self,
        global_options=None,
        covers=None,
        sensors=None,
        switches=None,
        lights=None,
    ):
        """Update data in ConfigEntry."""
        removal = False
        entry_data = self._config_entry.data.copy()
        for platform, values in {
            CONF_COVERS: covers,
            CONF_SENSORS: sensors,
            CONF_SWITCHES: switches,
            CONF_LIGHTS: lights,
        }.items():
            entry_data[platform] = copy.deepcopy(
                self._config_entry.data.get(platform, {})
            )
            if values:
                for id, options in values.items():
                    if options is None:
                        entry_data[platform].pop(id)
                        removal = True
                    else:
                        entry_data[platform][id] = options
        self.hass.config_entries.async_update_entry(self._config_entry, data=entry_data)
        if not removal:
            self.hass.async_create_task(
                self.hass.config_entries.async_reload(self._config_entry.entry_id)
            )
