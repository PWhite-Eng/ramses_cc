"""Tests to achieve 100% coverage for water_heater.py."""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import ANY, AsyncMock, MagicMock, PropertyMock, patch

import pytest
from homeassistant.const import STATE_OFF, STATE_ON
from homeassistant.core import HomeAssistant

from custom_components.ramses_cc.const import DOMAIN, SystemMode, ZoneMode
from custom_components.ramses_cc.water_heater import (
    STATE_AUTO,
    STATE_BOOST,
    RamsesWaterHeater,
)

# Constants for testing
DHW_ID = "13:123456"
SZ_ACTIVE = "active"


@pytest.fixture
def mock_broker(hass: HomeAssistant) -> MagicMock:
    """Return a mock broker with an entry attached."""
    entry = MagicMock()
    entry.entry_id = "test_entry"
    broker = MagicMock()
    broker.hass = hass
    hass.data[DOMAIN] = {entry.entry_id: broker}
    return broker


@pytest.fixture
def mock_dhw_device() -> MagicMock:
    """Return a mock DhwZone device."""
    device = MagicMock()
    device.id = DHW_ID
    device.mode = {"mode": ZoneMode.SCHEDULE, SZ_ACTIVE: True}
    device.temperature = 50.0
    device.setpoint = 55.0
    device.params = {"test": "params"}
    device.schedule = {"test": "schedule"}
    device.schedule_version = 1
    device.tcs.system_mode = {"system_mode": SystemMode.AUTO}

    # Async methods
    device.get_schedule = AsyncMock()
    device.set_schedule = AsyncMock()
    return device


@pytest.fixture
def water_heater_entity(
    hass: HomeAssistant, mock_broker: MagicMock, mock_dhw_device: MagicMock
) -> RamsesWaterHeater:
    """Return a RamsesWaterHeater entity."""
    description = MagicMock()
    description.key = "dhwzone"
    entity = RamsesWaterHeater(mock_broker, mock_dhw_device, description)
    entity.hass = hass

    # Mock the internal platform to prevent async_write_ha_state crashes
    mock_platform = MagicMock()
    mock_platform.platform_name = "ramses_cc"
    mock_platform.domain = DOMAIN
    entity.platform = mock_platform

    return entity


async def test_water_heater_property_logic(
    water_heater_entity: RamsesWaterHeater, mock_dhw_device: MagicMock
) -> None:
    """Test property return paths (Lines 126, 128)."""
    # Test Line 126: Mode is SCHEDULE (Auto)
    mock_dhw_device.mode = {"mode": ZoneMode.SCHEDULE}
    assert water_heater_entity.current_operation == STATE_AUTO

    # Test Line 128: Mode is PERMANENT and Active (On)
    mock_dhw_device.mode = {"mode": ZoneMode.PERMANENT, SZ_ACTIVE: True}
    assert water_heater_entity.current_operation == STATE_ON

    # Test Line 128: Mode is PERMANENT and Inactive (Off)
    mock_dhw_device.mode = {"mode": ZoneMode.PERMANENT, SZ_ACTIVE: False}
    assert water_heater_entity.current_operation == STATE_OFF


async def test_water_heater_property_errors(
    water_heater_entity: RamsesWaterHeater, mock_dhw_device: MagicMock
) -> None:
    """Test property catch blocks for TypeErrors."""
    # Force TypeError in current_operation
    with patch.object(mock_dhw_device, "mode", new_callable=PropertyMock) as mock_mode:
        mock_mode.side_effect = TypeError
        assert water_heater_entity.current_operation is None

    # Force TypeError in is_away_mode_on
    with patch.object(
        mock_dhw_device.tcs, "system_mode", new_callable=PropertyMock
    ) as mock_sys:
        mock_sys.side_effect = TypeError
        assert water_heater_entity.is_away_mode_on is None


async def test_set_temperature_and_params(
    water_heater_entity: RamsesWaterHeater, mock_dhw_device: MagicMock
) -> None:
    """Test setting temperature and parameters (Lines 177, 243-248)."""
    # Test Line 177: set_temperature calls async_set_dhw_params
    with patch.object(water_heater_entity, "async_write_ha_state_delayed"):
        water_heater_entity.set_temperature(temperature=60.0)

        # Lines 243-248: Verify device.set_config was called
        mock_dhw_device.set_config.assert_called_with(
            setpoint=60.0, overrun=None, differential=None
        )


async def test_set_operation_modes(water_heater_entity: RamsesWaterHeater) -> None:
    """Test set_operation_mode branches."""
    with patch.object(water_heater_entity, "async_set_dhw_mode") as mock_set_mode:
        water_heater_entity.set_operation_mode(STATE_BOOST)
        mock_set_mode.assert_called_with(
            mode=ZoneMode.TEMPORARY, active=True, until=ANY
        )

        water_heater_entity.set_operation_mode(STATE_OFF)
        mock_set_mode.assert_called_with(
            mode=ZoneMode.PERMANENT, active=False, until=None
        )

        water_heater_entity.set_operation_mode(STATE_ON)
        mock_set_mode.assert_called_with(
            mode=ZoneMode.PERMANENT, active=True, until=None
        )


async def test_water_heater_services(
    water_heater_entity: RamsesWaterHeater, mock_dhw_device: MagicMock
) -> None:
    """Test custom service calls."""
    water_heater_entity.async_fake_dhw_temp(45.0)
    assert mock_dhw_device.sensor.temperature == 45.0

    water_heater_entity.async_reset_dhw_mode()
    assert mock_dhw_device.reset_mode.called

    water_heater_entity.async_reset_dhw_params()
    assert mock_dhw_device.reset_config.called

    water_heater_entity.async_set_dhw_boost()
    assert mock_dhw_device.set_boost_mode.called


async def test_async_set_dhw_mode_logic(
    water_heater_entity: RamsesWaterHeater, mock_dhw_device: MagicMock
) -> None:
    """Test async_set_dhw_mode complex logic with duration."""
    water_heater_entity.async_set_dhw_mode(
        mode=ZoneMode.TEMPORARY, active=True, duration=timedelta(hours=2)
    )
    assert mock_dhw_device.set_mode.called
    args = mock_dhw_device.set_mode.call_args.kwargs
    assert args["until"] is not None


async def test_schedule_management(
    water_heater_entity: RamsesWaterHeater, mock_dhw_device: MagicMock
) -> None:
    """Test schedule services."""
    with patch.object(water_heater_entity, "async_write_ha_state"):
        await water_heater_entity.async_get_dhw_schedule()
        assert mock_dhw_device.get_schedule.called

        schedule_json = '{"mon": []}'
        await water_heater_entity.async_set_dhw_schedule(schedule_json)
        mock_dhw_device.set_schedule.assert_called_with({"mon": []})
