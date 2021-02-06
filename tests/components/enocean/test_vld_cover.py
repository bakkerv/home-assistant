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
from homeassistant.components.enocean.cover import CONF_USE_VLD, CONF_SENDER_ID
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


def goto_position_message(pos):
    RadioPacket.create(
        rorg=RORG.VLD,
        rorg_func=0x05,
        rorg_type=0x00,
        sender=SENDER_ID,
        destination=COVER_ID,
        command=1,  # Set position & angle
        POS=100 - pos,  # Set position
        ANG=127,  # No angle change
        REPO=0,  # Go directly to position/angle
        LOCK=0,  # No change
        CHN=0,  # set channel, fixed to channel 1
    )


def current_state_message(enocean_pos):
    return RadioPacket.create(
        rorg=RORG.VLD,
        rorg_func=0x05,
        rorg_type=0x00,
        sender=COVER_ID,
        destination=SENDER_ID,
        command=4,  # Reply
        POS=enocean_pos,  # Set position
        CHN=0,  # set channel, fixed to channel 1
    )


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
                    CONF_USE_VLD: True,
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


async def test_cover_has_initial_state_unknown(hass_with_cover_and_send_signals):
    hass, send_messages = hass_with_cover_and_send_signals
    state = hass.states.get("cover.test")
    assert state.state == STATE_UNKNOWN


# see http://tools.enocean-alliance.org/EEPViewer/profiles/D2/05/00/D2-05-00.pdf
# for packet formats


async def test_cover_close_command_sends_close_message(
    hass_with_cover_and_send_signals,
):
    hass, send_messages = hass_with_cover_and_send_signals
    current_pos = current_state_message(enocean_pos=50)
    dispatcher_send(
        hass,
        SIGNAL_RECEIVE_MESSAGE,
        current_pos,
    )

    await hass.async_block_till_done()
    state = hass.states.get("cover.test")
    assert state.state == STATE_OPEN

    await hass.services.async_call(
        "cover", "close_cover", {"entity_id": "cover.test"}, blocking=True
    )

    def close_command(packet):
        packet.parse_eep(0x05, 0x00)
        return (
            packet.parsed["CMD"]["raw_value"] == 1
            and packet.parsed["POS"]["raw_value"] == 100
            and packet.parsed["ANG"]["raw_value"] == 127
            and packet.parsed["REPO"]["raw_value"] == 0
            and packet.parsed["LOCK"]["raw_value"] == 0
            and packet.parsed["CHN"]["raw_value"] == 0
            and packet.sender == SENDER_ID
            and packet.destination == COVER_ID
        )

    assert any(map(lambda x: close_command(x[0]), send_messages))
    state = hass.states.get("cover.test")
    assert state.state == STATE_CLOSING


async def test_cover_open_command_sends_open_message(hass_with_cover_and_send_signals):
    hass, send_messages = hass_with_cover_and_send_signals

    current_pos = current_state_message(enocean_pos=50)
    dispatcher_send(
        hass,
        SIGNAL_RECEIVE_MESSAGE,
        current_pos,
    )

    await hass.async_block_till_done()
    state = hass.states.get("cover.test")
    assert state.state == STATE_OPEN

    await hass.services.async_call(
        "cover", "open_cover", {"entity_id": "cover.test"}, blocking=True
    )

    def open_command(packet):
        return (
            packet.parsed["CMD"]["raw_value"] == 1
            and packet.parsed["POS"]["raw_value"] == 0
            and packet.parsed["ANG"]["raw_value"] == 127
            and packet.parsed["REPO"]["raw_value"] == 0
            and packet.parsed["LOCK"]["raw_value"] == 0
            and packet.parsed["CHN"]["raw_value"] == 0
            and packet.sender == SENDER_ID
            and packet.destination == COVER_ID
        )

    assert any(map(lambda x: open_command(x[0]), send_messages))
    state = hass.states.get("cover.test")
    assert state.state == STATE_OPENING


async def test_cover_stop_command_sends_stop_message(
    hass_with_cover_and_send_signals,
):
    hass, send_messages = hass_with_cover_and_send_signals
    await hass.services.async_call(
        "cover", "stop_cover", {"entity_id": "cover.test"}, blocking=True
    )

    def stop_command(packet):
        return (
            packet.parsed["CMD"]["raw_value"] == 2
            and packet.parsed["CHN"]["raw_value"] == 0
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
        return (
            packet.parsed["CMD"]["raw_value"] == 1
            and packet.parsed["POS"]["raw_value"] == 70
            and packet.parsed["ANG"]["raw_value"] == 127
            and packet.parsed["REPO"]["raw_value"] == 0
            and packet.parsed["LOCK"]["raw_value"] == 0
            and packet.parsed["CHN"]["raw_value"] == 0
            and packet.sender == SENDER_ID
            and packet.destination == COVER_ID
        )

    assert any(map(lambda x: position_command(x[0]), send_messages))


async def test_cover_position_100_set_state_to_closed(hass_with_cover_and_send_signals):
    """ Cover position closed is defined as 100 in protocol"""
    hass, _ = hass_with_cover_and_send_signals
    current_pos = current_state_message(enocean_pos=100)
    dispatcher_send(hass, SIGNAL_RECEIVE_MESSAGE, current_pos)

    await hass.async_block_till_done()
    state = hass.states.get("cover.test")
    assert state.state == STATE_CLOSED


async def test_cover_position_0_set_state_to_opened(hass_with_cover_and_send_signals):
    """ Cover position closed is defined as 0 in protocol"""
    hass, _ = hass_with_cover_and_send_signals
    current_pos = current_state_message(enocean_pos=0)
    dispatcher_send(hass, SIGNAL_RECEIVE_MESSAGE, current_pos)

    await hass.async_block_till_done()
    state = hass.states.get("cover.test")
    assert state.state == STATE_OPEN


async def test_cover_position_upwards_sets_openin_untill_reached(
    hass_with_cover_and_send_signals,
):
    hass, _ = hass_with_cover_and_send_signals
    current_pos = current_state_message(enocean_pos=50)
    dispatcher_send(hass, SIGNAL_RECEIVE_MESSAGE, current_pos)

    await hass.async_block_till_done()
    state = hass.states.get("cover.test")
    assert state.state == STATE_OPEN

    await hass.services.async_call(
        "cover",
        "set_cover_position",
        {"entity_id": "cover.test", "position": 80},
        blocking=True,
    )
    await hass.async_block_till_done()
    state = hass.states.get("cover.test")
    assert state.state == STATE_OPENING
    current_pos = current_state_message(enocean_pos=20)
    dispatcher_send(hass, SIGNAL_RECEIVE_MESSAGE, current_pos)
    await hass.async_block_till_done()

    state = hass.states.get("cover.test")
    assert state.state == STATE_OPEN


async def test_cover_position_downwards_sets_closing_untill_reached(
    hass_with_cover_and_send_signals,
):
    hass, _ = hass_with_cover_and_send_signals
    current_pos = current_state_message(enocean_pos=50)
    dispatcher_send(hass, SIGNAL_RECEIVE_MESSAGE, current_pos)

    await hass.async_block_till_done()
    state = hass.states.get("cover.test")
    assert state.state == STATE_OPEN

    await hass.services.async_call(
        "cover",
        "set_cover_position",
        {"entity_id": "cover.test", "position": 20},
        blocking=True,
    )
    await hass.async_block_till_done()
    state = hass.states.get("cover.test")
    assert state.state == STATE_CLOSING
    current_pos = current_state_message(enocean_pos=80)
    dispatcher_send(hass, SIGNAL_RECEIVE_MESSAGE, current_pos)
    await hass.async_block_till_done()

    state = hass.states.get("cover.test")
    assert state.state == STATE_OPEN
