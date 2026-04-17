"""Config flow for babybuddy integration."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.config_entries import ConfigFlowResult
from homeassistant.const import (
    CONF_API_KEY,
    CONF_HOST,
    CONF_PATH,
    CONF_PORT,
    CONF_SCAN_INTERVAL,
    TEMPERATURE,
    UnitOfMass,
    UnitOfTemperature,
    UnitOfVolume,
)
from homeassistant.core import callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .client import BabyBuddyClient
from .const import (
    CONF_CONNECTION_MODE,
    CONF_FEEDING_UNIT,
    CONF_INGRESS_TOKEN,
    CONF_WEIGHT_UNIT,
    CONFIG_FLOW_VERSION,
    CONNECTION_MODE_DIRECT,
    CONNECTION_MODE_INGRESS,
    DEFAULT_NAME,
    DEFAULT_PATH,
    DEFAULT_PORT,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
)
from .errors import AuthorizationError, ConnectError

DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_CONNECTION_MODE, default=CONNECTION_MODE_DIRECT): vol.In(
            [CONNECTION_MODE_DIRECT, CONNECTION_MODE_INGRESS]
        ),
        vol.Optional(CONF_HOST): str,
        vol.Optional(CONF_PORT, default=DEFAULT_PORT): cv.port,
        vol.Optional(CONF_PATH, default=DEFAULT_PATH): str,
        vol.Optional(CONF_INGRESS_TOKEN): str,
        vol.Required(CONF_API_KEY): str,
    }
)


class BabyBuddyFlowHandler(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle babybuddy config flow."""

    VERSION = CONFIG_FLOW_VERSION

    @staticmethod
    @callback
    def async_get_options_flow(
        entry: config_entries.ConfigEntry,
    ) -> BabyBuddyOptionsFlowHandler:
        """Get the options flow for this handler."""
        return BabyBuddyOptionsFlowHandler(entry)

    def __init__(self) -> None:
        """Initiate config flow."""
        self._reauth_unique_id = None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle a flow initialized by the user."""
        errors: dict[str, str] = {}

        if user_input is not None:
            data = self._validate_user_input(user_input, errors)
            if data is None:
                return self.async_show_form(
                    step_id="user",
                    data_schema=DATA_SCHEMA,
                    errors=errors,
                )

            await self.async_set_unique_id(
                f"{data[CONF_CONNECTION_MODE]}-{data.get(CONF_HOST, data.get(CONF_INGRESS_TOKEN))}-{data[CONF_API_KEY]}"
            )
            self._abort_if_unique_id_configured()

            try:
                client: BabyBuddyClient = BabyBuddyClient(
                    data[CONF_HOST],
                    data.get(CONF_PORT),
                    data[CONF_PATH],
                    data[CONF_API_KEY],
                    async_get_clientsession(self.hass),
                )
                await client.async_connect()
            except AuthorizationError:
                errors["api_key"] = "invalid_auth"
            except ConnectError:
                errors["base"] = "cannot_connect"

            if not errors:
                return self.async_create_entry(
                    title=f"{DEFAULT_NAME} ({data[CONF_HOST]})",
                    data=data,
                )

        return self.async_show_form(
            step_id="user",
            data_schema=DATA_SCHEMA,
            errors=errors,
        )

    def _validate_user_input(
        self, user_input: dict[str, Any], errors: dict[str, str]
    ) -> dict[str, Any] | None:
        """Validate user config and normalize entry data."""
        data = {**user_input}
        connection_mode = data[CONF_CONNECTION_MODE]
        if connection_mode == CONNECTION_MODE_DIRECT:
            if not data.get(CONF_HOST):
                errors["base"] = "missing_fields"
            if errors:
                return None
            data[CONF_PATH] = data.get(CONF_PATH, DEFAULT_PATH)
            return data

        ingress_token = data.get(CONF_INGRESS_TOKEN, "").strip().strip("/")
        if not ingress_token:
            errors["base"] = "missing_fields"
            return None

        data[CONF_HOST] = "http://supervisor"
        data[CONF_PATH] = f"/core/api/hassio_ingress/{ingress_token}"
        data.pop(CONF_PORT, None)
        data[CONF_INGRESS_TOKEN] = ingress_token
        return data

    async def async_step_reauth(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Perform reauth upon an API authentication error."""
        self._reauth_unique_id = self.context["unique_id"]
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Dialog that informs the user that reauth is required."""
        errors: dict[str, str] = {}

        existing_entry = await self.async_set_unique_id(self._reauth_unique_id)
        if user_input is not None and existing_entry is not None:
            user_input[CONF_HOST] = existing_entry.data[CONF_HOST]
            if CONF_PORT in existing_entry.data:
                user_input[CONF_PORT] = existing_entry.data[CONF_PORT]
            user_input[CONF_PATH] = existing_entry.data[CONF_PATH]
            try:
                client: BabyBuddyClient = BabyBuddyClient(
                    user_input[CONF_HOST],
                    user_input.get(CONF_PORT),
                    user_input[CONF_PATH],
                    user_input[CONF_API_KEY],
                    async_get_clientsession(self.hass),
                )
                await client.async_connect()
            except ConnectError:
                errors["base"] = "cannot_connect"

            if not errors:
                self.hass.config_entries.async_update_entry(
                    existing_entry,
                    data={**existing_entry.data, **user_input},
                )
                await self.hass.config_entries.async_reload(existing_entry.entry_id)
                return self.async_abort(reason="reauth_successful")

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_API_KEY): str,
                }
            ),
            errors=errors,
        )


class BabyBuddyOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle babybuddy options."""

    def __init__(self, entry: config_entries.ConfigEntry) -> None:
        """Init object."""
        self.entry = entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage babybuddy options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        options: dict[vol.Optional, Any] = {
            vol.Optional(
                TEMPERATURE,
                default=self.entry.options.get(TEMPERATURE, None),
            ): vol.In([UnitOfTemperature.CELSIUS, UnitOfTemperature.FAHRENHEIT]),
            vol.Optional(
                CONF_WEIGHT_UNIT,
                default=self.entry.options.get(CONF_WEIGHT_UNIT, None),
            ): vol.In(
                [
                    UnitOfMass.KILOGRAMS,
                    UnitOfMass.GRAMS,
                    UnitOfMass.POUNDS,
                    UnitOfMass.OUNCES,
                ]
            ),
            vol.Optional(
                CONF_FEEDING_UNIT,
                default=self.entry.options.get(CONF_FEEDING_UNIT, None),
            ): vol.In([UnitOfVolume.MILLILITERS, UnitOfVolume.FLUID_OUNCES]),
            vol.Optional(
                CONF_SCAN_INTERVAL,
                default=self.entry.options.get(
                    CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL
                ),
            ): cv.positive_int,
        }
        return self.async_show_form(step_id="init", data_schema=vol.Schema(options))
