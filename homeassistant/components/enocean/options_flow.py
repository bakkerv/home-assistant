from homeassistant.components.command_line.cover import COVER_SCHEMA
from homeassistant.const import CONF_COVERS, CONF_DEVICE, CONF_ID, CONF_NAME
from homeassistant import config_entries, exceptions
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import callback
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

_LOGGER = logging.getLogger(__name__)


class OptionsFlowHandler(config_entries.OptionsFlow):
    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        super().__init__()
        self._config_entry = config_entry
        self._selected_device_entry_id = None
        self._device_entries = None
        self._device_registry = None
        self._current_dev_config = None
        self._current_dev_config_key = None

    def is_cover_device(self, identifiers: set, expected_type: str):
        return self.get_enocean_id(identifiers, expected_type) is not None

    def get_enocean_id(self, identifiers: set, expected_type: str):
        for id in identifiers:
            if len(id) == 2 and expected_type in id[1]:
                identifier_string = id[1]
                return identifier_string.split("-")[1:]
        return None

    async def async_step_init(self, user_input=None):
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
            if self.is_cover_device(entry.identifiers, "cover")
        }

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(CONF_COVERS): vol.In(configure_covers),
                }
            ),
        )

    def find_matching_config(self):
        device_id = self._selected_device_entry_id
        # find matching device entity to extract device id (part of unique id)
        for matching_device in filter(
            lambda x: x.id == device_id, self._device_entries
        ):
            # self._config_entry.data[CONF_COVERS]
            id = ",".join(self.get_enocean_id(matching_device.identifiers, "cover"))
            if id in self._config_entry.data[CONF_COVERS]:
                # for matching_config in filter(
                #     lambda x: list(map(lambda x: hex(x), x[CONF_ID]))
                #     == self.get_enocean_id(matching_device.identifiers, "cover"),
                #     self._config_entry.data[CONF_COVERS],
                # ):
                self._current_dev_config = self._config_entry.data[CONF_COVERS][id]
                self._current_dev_config_key = id
                return
        self._current_dev_config = None
        self._current_dev_config_key = None

    async def async_step_set_cover_options(self, user_input=None):
        errors = {}
        self.find_matching_config()
        if user_input is not None and self._current_dev_config_key is not None:
            sender_id = ""
            try:
                sender_id = list(
                    map(lambda x: int(x, 16), user_input[CONF_SENDER_ID].split(","))
                )
            except ValueError:
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
                errors.update(error.errors)
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
                    vol.Optional(
                        CONF_USE_VLD,
                        default=self._current_dev_config.get(CONF_USE_VLD, False),
                    ): cv.boolean,
                    vol.Required(
                        CONF_NAME,
                        default=self._current_dev_config[CONF_NAME],
                    ): cv.string,
                }
            )

            return self.async_show_form(
                step_id="set_cover_options", data_schema=schema, errors=errors
            )
        return self.async_create_entry(title="", data=None)

    @callback
    def update_config_data(self, global_options=None, covers=None):
        """Update data in ConfigEntry."""
        entry_data = self._config_entry.data.copy()
        entry_data[CONF_COVERS] = copy.deepcopy(self._config_entry.data[CONF_COVERS])
        if covers:
            for id, options in covers.items():
                if options is None:
                    entry_data[CONF_COVERS].pop(id)
                else:
                    entry_data[CONF_COVERS][id] = options
        self.hass.config_entries.async_update_entry(self._config_entry, data=entry_data)
        self.hass.async_create_task(
            self.hass.config_entries.async_reload(self._config_entry.entry_id)
        )
