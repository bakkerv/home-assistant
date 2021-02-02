"""Tests for EnOcean covers"""

from unittest.mock import AsyncMock, Mock, call, patch

from enocean.protocol.constants import RORG
from enocean.protocol.packet import RadioPacket
import pytest

from homeassistant.components.enocean.const import (
    DOMAIN,
    SIGNAL_RECEIVE_MESSAGE,
    SIGNAL_SEND_MESSAGE,
)
from homeassistant.components.enocean.cover import (
    A5_FUNCTION_BLIND_CLOSE,
    A5_FUNCTION_BLIND_OPEN,
    A5_FUNCTION_BLIND_STOP,
    A5_FUNCTION_STATUS_REQUEST,
    A5_FUNCTION_TO_POSITION,
    CONF_SENDER_ID,
)
from homeassistant.const import (
    CONF_COVERS,
    CONF_DEVICE,
    CONF_ID,
    CONF_NAME,
    STATE_CLOSED,
    STATE_CLOSING,
    STATE_OPEN,
    STATE_OPENING,
    STATE_UNKNOWN,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.dispatcher import dispatcher_send

from tests.common import MockConfigEntry, assert_setup_component, async_mock_signal

COVER_ID = [1, 1, 1, 1]
SENDER_ID = [2, 2, 2, 2]


@pytest.fixture
async def config_entry_with_enocean_cover(hass: HomeAssistant) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_DEVICE: "/somePath",
            CONF_COVERS: {
                "0x01:0x01:0x01:0x01": {
                    CONF_ID: COVER_ID,
                    CONF_SENDER_ID: SENDER_ID,
                    CONF_NAME: "test",
                }
            },
        },
    )
    entry.add_to_hass(hass)
    return entry


@pytest.fixture
def dongle_mock():
    return AsyncMock()


@pytest.fixture
async def hass_with_cover_and_send_signals(
    hass: HomeAssistant, config_entry_with_enocean_cover: MockConfigEntry, dongle_mock
):
    with patch("homeassistant.components.enocean.EnOceanDongle", autospec=True) as sc:
        sc.return_value = dongle_mock
        send_messages = async_mock_signal(hass, SIGNAL_SEND_MESSAGE)
        await hass.config_entries.async_setup(config_entry_with_enocean_cover.entry_id)
        await hass.async_block_till_done()
        return (hass, send_messages)


@pytest.fixture
def closed_enocean_message():
    return RadioPacket.create(RORG.BS4, 0x11, 0x03, sender=COVER_ID, EP=3)


@pytest.fixture
def opened_enocean_message():
    return RadioPacket.create(RORG.BS4, 0x11, 0x03, sender=COVER_ID, EP=2)


@pytest.fixture
def closing_enocean_message():
    return RadioPacket.create(
        RORG.BS4, 0x11, 0x03, sender=COVER_ID, EP=1, PVF=1, ST=3, BSP=10
    )


@pytest.fixture
def opening_enocean_message():
    return RadioPacket.create(
        RORG.BS4, 0x11, 0x03, sender=COVER_ID, EP=1, PVF=1, ST=2, BSP=10
    )


@pytest.fixture
def closing_enocean_message_inverse_motp():
    return RadioPacket.create(
        RORG.BS4, 0x11, 0x03, sender=COVER_ID, EP=1, PVF=1, ST=3, BSP=10, MOTP=1
    )


@pytest.fixture
def opening_enocean_message_inverse_motp():
    return RadioPacket.create(
        RORG.BS4, 0x11, 0x03, sender=COVER_ID, EP=1, PVF=1, ST=2, BSP=10, MOTP=1
    )


async def test_cover_has_initial_state_unknown(hass_with_cover_and_send_signals):
    hass, send_messages = hass_with_cover_and_send_signals
    state = hass.states.get("cover.test")
    assert state.state == STATE_UNKNOWN
    await hass.async_block_till_done()
    # check is a request for a state is done

    def is_request(packet):
        packet.parse_eep(0x38, 0x08)
        return (
            packet.parsed["FUNC"]["raw_value"] == A5_FUNCTION_STATUS_REQUEST
            and packet.sender == SENDER_ID
            and packet.destination == COVER_ID
        )

    assert any(map(lambda x: is_request(x[0]), send_messages))


async def test_cover_close_command_sends_close_message(
    hass_with_cover_and_send_signals,
):
    hass, send_messages = hass_with_cover_and_send_signals
    await hass.services.async_call(
        "cover", "close_cover", {"entity_id": "cover.test"}, blocking=True
    )

    def close_command(packet):
        packet.parse_eep(0x38, 0x08)
        return (
            packet.parsed["FUNC"]["raw_value"] == A5_FUNCTION_BLIND_CLOSE
            and packet.parsed["COM"]["raw_value"] == 7
            and packet.sender == SENDER_ID
            and packet.destination == COVER_ID
        )

    assert any(map(lambda x: close_command(x[0]), send_messages))


async def test_cover_open_command_sends_open_message(
    hass_with_cover_and_send_signals,
):
    hass, send_messages = hass_with_cover_and_send_signals
    await hass.services.async_call(
        "cover", "open_cover", {"entity_id": "cover.test"}, blocking=True
    )

    def open_command(packet):
        packet.parse_eep(0x38, 0x08)
        return (
            packet.parsed["FUNC"]["raw_value"] == A5_FUNCTION_BLIND_OPEN
            and packet.parsed["COM"]["raw_value"] == 7
            and packet.sender == SENDER_ID
            and packet.destination == COVER_ID
        )

    assert any(map(lambda x: open_command(x[0]), send_messages))


async def test_cover_stop_command_sends_stop_message(
    hass_with_cover_and_send_signals,
):
    hass, send_messages = hass_with_cover_and_send_signals
    await hass.services.async_call(
        "cover", "stop_cover", {"entity_id": "cover.test"}, blocking=True
    )

    def stop_command(packet):
        packet.parse_eep(0x38, 0x08)
        return (
            packet.parsed["FUNC"]["raw_value"] == A5_FUNCTION_BLIND_STOP
            and packet.parsed["COM"]["raw_value"] == 7
            and packet.sender == SENDER_ID
            and packet.destination == COVER_ID
        )

    assert any(map(lambda x: stop_command(x[0]), send_messages))


async def test_cover_set_position_command_sends_position_message(
    hass_with_cover_and_send_signals,
):
    hass, send_messages = hass_with_cover_and_send_signals
    await hass.services.async_call(
        "cover",
        "set_cover_position",
        {"entity_id": "cover.test", "position": 30},
        blocking=True,
    )

    def position_command(packet):
        packet.parse_eep(0x38, 0x08)
        return (
            packet.parsed["FUNC"]["raw_value"] == A5_FUNCTION_TO_POSITION
            and packet.parsed["COM"]["raw_value"] == 7
            and packet.parsed["P1"]["raw_value"] == 70
            and packet.sender == SENDER_ID
            and packet.destination == COVER_ID
        )

    assert any(map(lambda x: position_command(x[0]), send_messages))


async def test_cover_closed_message_set_state_to_closed(
    hass_with_cover_and_send_signals, closed_enocean_message
):
    hass, _ = hass_with_cover_and_send_signals
    dispatcher_send(
        hass,
        SIGNAL_RECEIVE_MESSAGE,
        closed_enocean_message,
    )

    await hass.async_block_till_done()
    state = hass.states.get("cover.test")
    assert state.state == STATE_CLOSED


async def test_cover_opened_message_set_state_to_opened(
    hass_with_cover_and_send_signals, opened_enocean_message
):
    hass, _ = hass_with_cover_and_send_signals
    dispatcher_send(
        hass,
        SIGNAL_RECEIVE_MESSAGE,
        opened_enocean_message,
    )

    await hass.async_block_till_done()
    state = hass.states.get("cover.test")
    assert state.state == STATE_OPEN


async def test_cover_opening_message_set_state_to_opening(
    hass_with_cover_and_send_signals, opening_enocean_message
):
    hass, _ = hass_with_cover_and_send_signals
    dispatcher_send(
        hass,
        SIGNAL_RECEIVE_MESSAGE,
        opening_enocean_message,
    )

    await hass.async_block_till_done()
    state = hass.states.get("cover.test")
    assert state.state == STATE_OPENING
    assert state.attributes["current_position"] == 75


async def test_cover_closing_message_set_state_to_closing(
    hass_with_cover_and_send_signals, closing_enocean_message
):
    hass, _ = hass_with_cover_and_send_signals
    dispatcher_send(
        hass,
        SIGNAL_RECEIVE_MESSAGE,
        closing_enocean_message,
    )

    await hass.async_block_till_done()
    state = hass.states.get("cover.test")
    assert state.state == STATE_CLOSING
    assert state.attributes["current_position"] == 75


async def test_cover_opening_message_set_state_to_opening(
    hass_with_cover_and_send_signals, opening_enocean_message_inverse_motp
):
    hass, _ = hass_with_cover_and_send_signals
    dispatcher_send(
        hass,
        SIGNAL_RECEIVE_MESSAGE,
        opening_enocean_message_inverse_motp,
    )

    await hass.async_block_till_done()
    state = hass.states.get("cover.test")
    assert state.state == STATE_OPENING
    assert state.attributes["current_position"] == 25


async def test_cover_closing_message_set_state_to_closing_inverse_motp(
    hass_with_cover_and_send_signals, closing_enocean_message_inverse_motp
):
    hass, _ = hass_with_cover_and_send_signals
    dispatcher_send(
        hass,
        SIGNAL_RECEIVE_MESSAGE,
        closing_enocean_message_inverse_motp,
    )

    await hass.async_block_till_done()
    state = hass.states.get("cover.test")
    assert state.state == STATE_CLOSING
    assert state.attributes["current_position"] == 25
