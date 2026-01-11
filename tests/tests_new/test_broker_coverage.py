"""Tests for ramses_cc broker coverage to address missing lines."""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import voluptuous as vol
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import device_registry as dr, entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ramses_cc.broker import RamsesBroker
from custom_components.ramses_cc.const import DOMAIN, SIGNAL_NEW_DEVICES
from ramses_rf.device.hvac import HvacRemoteBase, HvacVentilator
from ramses_rf.system import Evohome
from ramses_tx.schemas import SZ_BOUND_TO, SZ_KNOWN_LIST

# Constants
HGI_ID = "18:000730"


@pytest.fixture
def mock_gateway() -> MagicMock:
    """Return a mock Gateway."""
    gateway = MagicMock()
    gateway.async_send_cmd = AsyncMock()
    gateway.systems = []
    gateway.devices = []
    # Mock HGI device for send_packet tests
    gateway.hgi.id = HGI_ID
    return gateway


@pytest.fixture
def mock_broker(hass: HomeAssistant, mock_gateway: MagicMock) -> RamsesBroker:
    """Return a configured RamsesBroker."""
    entry = MagicMock()
    entry.entry_id = "test_entry"
    entry.options = {
        "serial_port": "/dev/ttyUSB0",
        "ramses_rf": {},
        "known_list": {},
    }

    broker = RamsesBroker(hass, entry)
    broker.client = mock_gateway
    broker._device_info = {}
    broker._remotes = {}

    # Mock the store
    broker._store = MagicMock()
    broker._store.async_load = AsyncMock(return_value={})
    broker._store.async_save = AsyncMock()

    hass.data[DOMAIN] = {entry.entry_id: broker}
    return broker


class MockSystem:
    """Mock System class."""

    def __init__(self) -> None:
        """Initialize mock system."""
        self.id = "01:123456"
        self._SLUG = "CTL"

    def _msg_value_code(self, code: Any) -> dict[str, Any] | None:
        """Mock msg value code."""
        return {"description": "Evohome Controller"}


class MockZone:
    """Mock Zone class."""

    def __init__(self) -> None:
        """Initialize mock zone."""
        self.id = "01:123456_00"
        self._SLUG = "ZON"
        self.tcs = MagicMock()
        self.tcs.id = "01:123456"

    def _msg_value_code(self, code: Any) -> None:
        """Mock msg value code."""
        return None


class MockChild:
    """Mock Child class."""

    def __init__(self) -> None:
        """Initialize mock child."""
        self.id = "04:123456"
        self._SLUG = "TRV"
        self._parent = MagicMock()
        self._parent.id = "01:123456"

    def _msg_value_code(self, code: Any) -> None:
        """Mock msg value code."""
        return None


async def test_async_setup_schema_merge(
    hass: HomeAssistant, mock_broker: RamsesBroker
) -> None:
    """Test setup with schema merging and fallback logic."""
    mock_broker.client = None
    mock_broker._store.async_load.return_value = {
        "client_state": {
            "schema": {"system": {"appliance_control": "10:123456"}},
            "packets": {},
        }
    }

    mock_client = AsyncMock()

    with (
        patch(
            "custom_components.ramses_cc.broker.merge_schemas",
            return_value={"merged": True},
        ),
        patch(
            "custom_components.ramses_cc.broker.schema_is_minimal", return_value=True
        ),
        patch.object(
            mock_broker,
            "_create_client",
            side_effect=[vol.MultipleInvalid("Invalid"), mock_client],
        ),
        patch("custom_components.ramses_cc.broker._LOGGER.warning") as mock_warn,
    ):
        await mock_broker.async_setup()
        assert mock_warn.called
        assert "Failed to initialise with merged schema" in mock_warn.call_args[0][0]
        assert mock_broker._create_client.call_count == 2
        assert mock_client.start.called


async def test_update_device_logic(
    hass: HomeAssistant, mock_broker: RamsesBroker
) -> None:
    """Test _update_device logic for different device types."""
    mock_dr = MagicMock(spec=dr.DeviceRegistry)
    with (
        patch("homeassistant.helpers.device_registry.async_get", return_value=mock_dr),
        patch("custom_components.ramses_cc.broker.System", MockSystem),
        patch("custom_components.ramses_cc.broker.Zone", MockZone),
        patch("custom_components.ramses_cc.broker.Child", MockChild),
    ):
        mock_system = MagicMock()
        mock_system.id = "01:123456"
        mock_system.name = None
        mock_system._SLUG = "CTL"
        mock_system.__class__ = MockSystem  # type: ignore[assignment]
        mock_system._msg_value_code.return_value = {"description": "Evohome Controller"}

        mock_broker._update_device(mock_system)
        call_kwargs = mock_dr.async_get_or_create.call_args[1]
        assert call_kwargs["model"] == "Evohome Controller"
        assert call_kwargs["name"] == "Controller 01:123456"

        mock_zone = MagicMock()
        mock_zone.id = "01:123456_00"
        mock_zone.name = "Living Room"
        mock_zone._SLUG = "ZON"
        mock_zone.__class__ = MockZone  # type: ignore[assignment]
        mock_zone.tcs = MagicMock()
        mock_zone.tcs.id = "01:123456"
        mock_zone._msg_value_code.return_value = None

        mock_broker._update_device(mock_zone)
        call_kwargs = mock_dr.async_get_or_create.call_args[1]
        assert call_kwargs["name"] == "Living Room"
        assert call_kwargs["via_device"] == (DOMAIN, "01:123456")


async def test_update_device_unsupported_type(
    hass: HomeAssistant, mock_broker: RamsesBroker
) -> None:
    """Test _update_device path for devices that are not supported entity types (Lines 445-456)."""
    mock_dr = MagicMock(spec=dr.DeviceRegistry)
    with patch("homeassistant.helpers.device_registry.async_get", return_value=mock_dr):
        mock_unknown = MagicMock()
        mock_unknown.id = "18:000730"
        mock_unknown.name = "Gateway"
        mock_unknown._SLUG = "HGI"

        with (
            patch("custom_components.ramses_cc.broker.System", type),
            patch("custom_components.ramses_cc.broker.Zone", type),
            patch("custom_components.ramses_cc.broker.Child", type),
        ):
            mock_broker._update_device(mock_unknown)
            assert mock_dr.async_get_or_create.called


async def test_async_update_discovery_loop(
    hass: HomeAssistant, mock_broker: RamsesBroker
) -> None:
    """Test the discovery loop in async_update for all platforms (Lines 504-517)."""
    # Create the config entry in hass so device_registry can link devices to it
    config_entry = MockConfigEntry(domain=DOMAIN, entry_id="test_entry")
    config_entry.add_to_hass(hass)

    mock_sys = MagicMock(spec=Evohome)
    mock_sys.id = "01:111111"
    mock_sys.name = "Test System"
    mock_sys._SLUG = "CTL"
    mock_sys.zones = []  # Explicitly add zones list
    mock_sys.dhw = None  # Explicitly add dhw property
    # Ensure description is a string, not a Mock, to prevent JSON serialization error
    mock_sys._msg_value_code.return_value = {"description": "Evohome Controller"}

    mock_dev = MagicMock()
    mock_dev.id = "30:123456"
    mock_dev.name = "Test Device"
    mock_dev._SLUG = "FAN"
    mock_dev._msg_value_code.return_value = None
    # Disable 2411 support for this test to avoid fan param setup overhead/errors
    mock_dev.supports_2411 = False

    mock_broker.client.systems = [mock_sys]
    mock_broker.client.devices = [mock_dev]

    # Mock get_state to return a tuple (schema, packets) to fix unpacking error
    mock_broker.client.get_state.return_value = ({}, {})

    with (
        patch.object(
            mock_broker, "_async_setup_platform", AsyncMock(return_value=True)
        ),
        patch("custom_components.ramses_cc.broker.async_dispatcher_send") as mock_send,
    ):
        await mock_broker.async_update()
        # Verify signal for new system discovery (Platform.CLIMATE)
        assert any(
            SIGNAL_NEW_DEVICES.format("climate") in str(call)
            for call in mock_send.call_args_list
        )


async def test_async_unload_platforms(
    hass: HomeAssistant, mock_broker: RamsesBroker
) -> None:
    """Test async_unload_platforms and task cancellation (Lines 389-392)."""
    mock_task = MagicMock(spec=asyncio.Task)
    mock_task.cancel.return_value = False
    mock_broker._platform_setup_tasks = {"sensor": mock_task}

    with patch.object(
        hass.config_entries, "async_forward_entry_unload", AsyncMock(return_value=True)
    ):
        result = await mock_broker.async_unload_platforms()
        assert result is True


async def test_async_bind_device_success(
    hass: HomeAssistant, mock_broker: RamsesBroker
) -> None:
    """Test async_bind_device success path."""
    call = MagicMock(spec=ServiceCall)
    call.data = {
        "device_id": "30:123456",
        "offer": {},
        "confirm": {},
        "device_info": None,
    }

    mock_device = MagicMock()
    mock_device.id = "30:123456"
    mock_device._initiate_binding_process = AsyncMock(return_value=None)
    mock_broker.client.fake_device.return_value = mock_device

    with (
        patch("custom_components.ramses_cc.broker._LOGGER.warning") as mock_warn,
        patch("custom_components.ramses_cc.broker.async_call_later") as mock_later,
    ):
        await mock_broker.async_bind_device(call)
        assert mock_device._initiate_binding_process.called
        assert any("Success" in str(c) for c in mock_warn.call_args_list)
        assert mock_later.called


async def test_async_bind_device_errors(
    hass: HomeAssistant, mock_broker: RamsesBroker
) -> None:
    """Test async_bind_device error paths."""
    call = MagicMock(spec=ServiceCall)
    call.data = {
        "device_id": "30:123456",
        "offer": {},
        "confirm": {},
        "device_info": None,
    }

    mock_broker.client.fake_device.side_effect = LookupError("Device not found")

    with patch("custom_components.ramses_cc.broker._LOGGER.error") as mock_error:
        await mock_broker.async_bind_device(call)
        assert mock_error.called
        assert "Device not found" in str(mock_error.call_args)

    mock_device = MagicMock()
    mock_device.id = "30:123456"
    mock_broker.client.fake_device.side_effect = None
    mock_broker.client.fake_device.return_value = mock_device
    mock_device._initiate_binding_process = AsyncMock(
        side_effect=RuntimeError("Binding Failed")
    )

    with pytest.raises(RuntimeError, match="Binding Failed"):
        await mock_broker.async_bind_device(call)


async def test_setup_fan_bound_devices(
    hass: HomeAssistant, mock_broker: RamsesBroker
) -> None:
    """Test _setup_fan_bound_devices logic."""

    class MockFan(HvacVentilator):
        """Mock Fan."""

    mock_fan = MagicMock()
    mock_fan.id = "30:123456"
    mock_fan.__class__ = MockFan
    mock_fan.type = "FAN"
    mock_fan.add_bound_device = MagicMock()

    mock_broker.options = {SZ_KNOWN_LIST: {"30:123456": {SZ_BOUND_TO: "32:987654"}}}

    mock_remote = MagicMock()
    mock_remote.id = "32:987654"
    mock_remote.__class__ = HvacRemoteBase

    mock_broker.client.devices = [mock_fan, mock_remote]

    await mock_broker._setup_fan_bound_devices(mock_fan)
    assert mock_fan.add_bound_device.called
    args = mock_fan.add_bound_device.call_args
    assert args[0][0] == "32:987654"


async def test_async_send_packet_hgi_hack(
    hass: HomeAssistant, mock_broker: RamsesBroker
) -> None:
    """Test async_send_packet HGI address swapping hack."""
    mock_broker.client.hgi.id = HGI_ID

    call = MagicMock(spec=ServiceCall)
    call.data = {
        "device_id": HGI_ID,
        "verb": "I",
        "code": "1F09",
        "payload": "FF",
        "from_id": HGI_ID,
    }

    mock_cmd = MagicMock()
    mock_cmd.src.id = HGI_ID
    mock_cmd.dst.id = HGI_ID
    mock_cmd._frame = "00000000000000001800073018006402"
    mock_cmd._addrs = [HGI_ID, HGI_ID, "18:006402"]
    mock_cmd._repr = "Some Repr"

    mock_broker.client.create_cmd.return_value = mock_cmd

    class MyInvalid(Exception):
        """Mock Exception."""

    with (
        patch(
            "custom_components.ramses_cc.broker.pkt_addrs",
            side_effect=MyInvalid("Invalid"),
        ),
        patch("custom_components.ramses_cc.broker.PacketAddrSetInvalid", MyInvalid),
    ):
        await mock_broker.async_send_packet(call)
        assert mock_cmd._addrs[1] == "18:006402"
        assert mock_cmd._addrs[2] == HGI_ID
        assert mock_cmd._repr is None


async def test_resolve_device_id_lists(
    hass: HomeAssistant, mock_broker: RamsesBroker
) -> None:
    """Test _resolve_device_id with list inputs (Line 787)."""
    assert mock_broker._resolve_device_id({"device_id": []}) is None

    data = {"device_id": ["01:123456", "01:654321"]}
    with patch("custom_components.ramses_cc.broker._LOGGER.warning") as mock_warn:
        resolved = mock_broker._resolve_device_id(data)
        assert resolved == "01:123456"
        assert mock_warn.called
        assert "Multiple device_ids" in mock_warn.call_args[0][0]


async def test_target_to_device_id_resolution(
    hass: HomeAssistant, mock_broker: RamsesBroker
) -> None:
    """Test _target_to_device_id and resolution logic."""
    mock_dev_reg = MagicMock()
    mock_ent_reg = MagicMock(spec=er.EntityRegistry)

    with (
        patch(
            "homeassistant.helpers.device_registry.async_get", return_value=mock_dev_reg
        ),
        patch(
            "homeassistant.helpers.entity_registry.async_get", return_value=mock_ent_reg
        ),
    ):
        test_ha_dev_id = "ha_device_123"
        test_ramses_id = "01:111111"

        mock_dev_entry = MagicMock()
        mock_dev_entry.identifiers = {(DOMAIN, test_ramses_id)}
        mock_dev_entry.area_id = "kitchen"

        mock_dev_reg.async_get.return_value = mock_dev_entry
        mock_dev_reg.devices.values.return_value = [mock_dev_entry]

        mock_ent_entry = MagicMock()
        mock_ent_entry.device_id = test_ha_dev_id
        mock_ent_reg.async_get.return_value = mock_ent_entry

        target = {"entity_id": ["climate.living_room"]}
        assert mock_broker._target_to_device_id(target) == test_ramses_id

        target = {"device_id": [test_ha_dev_id]}
        assert mock_broker._target_to_device_id(target) == test_ramses_id

        target = {"area_id": ["kitchen"]}
        assert mock_broker._target_to_device_id(target) == test_ramses_id

        call_data: dict[str, Any] = {"device": [test_ha_dev_id]}
        assert mock_broker._resolve_device_id(call_data) == test_ramses_id


async def test_fan_param_entities_cached(
    hass: HomeAssistant, mock_broker: RamsesBroker
) -> None:
    """Test fan entity creation path when device is already initialized (Lines 854-875)."""
    mock_fan = MagicMock()
    mock_fan.id = "30:123456"
    mock_fan._SLUG = "FAN"
    mock_fan.supports_2411 = True
    mock_fan._initialized = True  # Simulate cached state

    mock_bus = MagicMock()
    with (
        patch(
            "custom_components.ramses_cc.number.create_parameter_entities",
            return_value=[MagicMock()],
        ),
        patch.object(mock_broker.hass, "bus", mock_bus),
    ):
        await mock_broker._async_setup_fan_device(mock_fan)
        assert mock_fan.set_param_update_callback.called


async def test_fan_param_id_validation_errors(
    hass: HomeAssistant, mock_broker: RamsesBroker
) -> None:
    """Test parameter ID validation errors (Lines 1032-1033)."""
    with pytest.raises(ValueError, match="Invalid parameter ID"):
        mock_broker._get_param_id({"param_id": "ZZ"})  # Non-hex

    with pytest.raises(ValueError, match="Invalid parameter ID"):
        mock_broker._get_param_id({"param_id": "1"})  # Too short


async def test_async_run_fan_param_sequence_error_handling(
    hass: HomeAssistant, mock_broker: RamsesBroker
) -> None:
    """Test full fan parameter sequence error path (Lines 1163, 1173)."""
    with (
        patch.object(
            mock_broker, "async_get_fan_param", side_effect=Exception("Sequence Fail")
        ),
        patch("custom_components.ramses_cc.broker._LOGGER.error") as mock_error,
    ):
        await mock_broker._async_run_fan_param_sequence({"device_id": "30:123456"})
        assert mock_error.called
        assert "Sequence Fail" in str(mock_error.call_args)


async def test_async_set_fan_param_failures(
    hass: HomeAssistant, mock_broker: RamsesBroker
) -> None:
    """Test failures during async_set_fan_param (Lines 1178-1187)."""
    # 1. ValueError for source (simulating an error swallowed by the broker)
    # The broker catches and logs ValueError, but re-raises other exceptions.
    # We also patch Command.set_fan_param to bypass parameter validation
    with patch("custom_components.ramses_cc.broker.Command.set_fan_param") as mock_cmd:
        mock_cmd.return_value = MagicMock()
        mock_broker.client.async_send_cmd.side_effect = ValueError("Source missing")

        with patch("custom_components.ramses_cc.broker._LOGGER.error") as mock_error:
            await mock_broker.async_set_fan_param(
                {
                    "device_id": "30:123456",
                    "param_id": "10",
                    "value": "1",
                    "from_id": "32:111111",
                }
            )
            assert mock_error.called
            assert "Source missing" in str(mock_error.call_args)
