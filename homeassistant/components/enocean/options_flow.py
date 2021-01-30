from homeassistant.components.command_line.cover import COVER_SCHEMA
from homeassistant.const import (
    CONF_COVERS,
    CONF_DEVICE,
    CONF_ID,
    CONF_NAME,
    CONF_SENSORS,
)
from homeassistant import config_entries, exceptions
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import callback
from enocean.utils import from_hex_string, to_hex_string
import copy


from homeassistant.helpers import config_validation as cv
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

_LOGGER = logging.getLogger(__name__)


EDIT_KEY = "edit_selection"
ADD_COVER = "Add cover"
EDIT_COVER = "Edit cover"
ADD_SENSOR = "Add sensor"
EDIT_SENSOR = "Edit sensor"


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
            if user_input[EDIT_KEY] == EDIT_COVER:
                return await self.async_step_select_cover()
            if user_input[EDIT_KEY] == ADD_COVER:
                return await self.async_step_create_cover()
            if user_input[EDIT_KEY] == ADD_SENSOR:
                return await self.async_step_create_sensor()
            if user_input[EDIT_KEY] == EDIT_SENSOR:
                return await self.async_step_select_sensor()

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(EDIT_KEY): vol.In(
                        [ADD_COVER, EDIT_COVER, ADD_SENSOR, EDIT_SENSOR]
                    )
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
            except vol.error.Error as error:
                errors["base"] = "invalid_data"
            if not errors:
                self.update_config_data(covers={to_hex_string(dev_id): data})
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

    async def async_step_create_sensor(self, user_input=None):
        """Add new sensor step"""
        errors = {}
        if user_input is not None:
            dev_id = self.device_id_or_none(user_input[CONF_ID])
            if dev_id is None:
                errors[CONF_ID] = "invalid_id"
            user_input[CONF_ID] = dev_id
            try:
                if not errors:
                    data = SENSOR_SCHEMA(user_input)
            except vol.error.Error as error:
                errors["base"] = "invalid_data"
            if not errors:
                self.update_config_data(sensors={to_hex_string(dev_id): data})
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

    async def async_step_select_cover(self, user_input=None):
        """Manage the options."""
        if user_input is not None:
            if CONF_COVERS in user_input:
                self._selected_device_entry_id = user_input[CONF_COVERS]
                return await self.async_step_set_cover_options()

            return self.async_create_entry(title="", data=user_input)

        device_registry = await async_get_device_registry(self.hass)
        device_entries = async_entries_for_config_entry(
            device_registry, self._config_entry.entry_id
        )
        self._device_registry = device_registry
        self._device_entries = device_entries

        configure_covers = {
            entry.id: entry.name_by_user if entry.name_by_user else entry.name
            for entry in device_entries
            if self.is_device_type(entry.identifiers, "cover")
        }

        return self.async_show_form(
            step_id="select_cover",
            data_schema=vol.Schema(
                {
                    vol.Optional(CONF_COVERS): vol.In(configure_covers),
                }
            ),
        )

    async def async_step_select_sensor(self, user_input=None):
        """Manage the options."""
        if user_input is not None:
            if CONF_SENSORS in user_input:
                self._selected_device_entry_id = user_input[CONF_SENSORS]
                return await self.async_step_set_sensor_options()

            return self.async_create_entry(title="", data=user_input)

        device_registry = await async_get_device_registry(self.hass)
        device_entries = async_entries_for_config_entry(
            device_registry, self._config_entry.entry_id
        )
        self._device_registry = device_registry
        self._device_entries = device_entries

        configure_sensors = {
            entry.id: entry.name_by_user if entry.name_by_user else entry.name
            for entry in device_entries
            if self.is_device_type(entry.identifiers, "sensor")
        }

        return self.async_show_form(
            step_id="select_sensor",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_SENSORS): vol.In(configure_sensors),
                }
            ),
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
            except vol.error.Error as error:
                errors["base"] = "invalid_data"
            if not errors:
                self.update_config_data(covers={self._current_dev_config_key: data})
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
            except vol.error.Error as error:
                errors["base"] = "invalid_data"
            if not errors:
                self.update_config_data(sensors={self._current_dev_config_key: data})
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

    @callback
    def update_config_data(self, global_options=None, covers=None, sensors=None):
        """Update data in ConfigEntry."""
        entry_data = self._config_entry.data.copy()
        for platform in [CONF_COVERS, CONF_SENSORS]:
            entry_data[platform] = copy.deepcopy(
                self._config_entry.data.get(platform, {})
            )
        if covers:
            for id, options in covers.items():
                if options is None:
                    entry_data[CONF_COVERS].pop(id)
                else:
                    entry_data[CONF_COVERS][id] = options
        if sensors:
            for id, options in sensors.items():
                if options is None:
                    entry_data[CONF_SENSORS].pop(id)
                else:
                    entry_data[CONF_SENSORS][id] = options
        self.hass.config_entries.async_update_entry(self._config_entry, data=entry_data)
        self.hass.async_create_task(
            self.hass.config_entries.async_reload(self._config_entry.entry_id)
        )
