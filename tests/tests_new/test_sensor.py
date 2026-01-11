"""Tests to achieve 100% coverage for sensor.py."""

from __future__ import annotations

from unittest.mock import MagicMock, PropertyMock, patch

import pytest
from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.const import (
    CONCENTRATION_PARTS_PER_MILLION,
    PERCENTAGE,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant

from custom_components.ramses_cc.const import DOMAIN
from custom_components.ramses_cc.sensor import (
    RamsesSensor,
    RamsesSensorEntityDescription,
    async_setup_entry,
)

# Constants for testing
SENSOR_ID = "01:123456"


@pytest.fixture
def mock_broker() -> MagicMock:
    """Return a mock broker.

    :return: A MagicMock simulating the RamsesBroker.
    """
    broker = MagicMock()
    broker.hass.data = {DOMAIN: {"test_entry": broker}}
    broker.async_register_platform = MagicMock()
    return broker


@pytest.fixture
def mock_device() -> MagicMock:
    """Return a mock RAMSES RF device.

    :return: A MagicMock simulating a RAMSES RF device.
    """
    device = MagicMock()
    device.id = SENSOR_ID
    device.is_faked = True
    device.temperature = 20.5
    device.co2_level = 800
    device.indoor_humidity = 0.45  # 45%
    return device


async def test_sensor_setup_entry(hass: HomeAssistant, mock_broker: MagicMock) -> None:
    """Test the async_setup_entry logic (Lines 107-121).

    :param hass: The Home Assistant instance.
    :param mock_broker: The mock broker fixture.
    """
    entry = MagicMock()
    entry.entry_id = "test_entry"
    hass.data[DOMAIN] = {entry.entry_id: mock_broker}

    async_add_entities = MagicMock()

    # Mock the platform discovery
    with patch(
        "custom_components.ramses_cc.sensor.async_get_current_platform",
        return_value=MagicMock(),
    ):
        await async_setup_entry(hass, entry, async_add_entities)

    # Verify platform registration
    assert mock_broker.async_register_platform.called
    add_devices_callback = mock_broker.async_register_platform.call_args[0][1]

    # Test the add_devices callback inside setup_entry
    mock_rf_device = MagicMock()
    mock_rf_device.id = SENSOR_ID
    # Must match a description class and have the required attribute
    from ramses_rf.device.heat import DhwSensor

    mock_rf_device.__class__ = DhwSensor
    mock_rf_device.temperature = 25.0

    add_devices_callback([mock_rf_device])
    assert async_add_entities.called


def test_sensor_available_logic(mock_broker: MagicMock, mock_device: MagicMock) -> None:
    """Test the availability logic branches (Line 148).

    :param mock_broker: The mock broker fixture.
    :param mock_device: The mock device fixture.
    """
    desc = RamsesSensorEntityDescription(
        key="temp",
        ramses_rf_attr="temperature",
    )
    sensor = RamsesSensor(mock_broker, mock_device, desc)

    # Branch 1: Faked device (Line 148)
    mock_device.is_faked = True
    assert sensor.available is True

    # Branch 2: Not faked but has state (Line 149)
    mock_device.is_faked = False
    with patch.object(RamsesSensor, "state", new_callable=PropertyMock) as mock_state:
        mock_state.return_value = 20.0
        assert sensor.available is True

        # Branch 3: Not faked and no state
        mock_state.return_value = None
        assert sensor.available is False


def test_sensor_native_value_percentage(
    mock_broker: MagicMock, mock_device: MagicMock
) -> None:
    """Test native_value conversion for percentage sensors.

    :param mock_broker: The mock broker fixture.
    :param mock_device: The mock device fixture.
    """
    desc = RamsesSensorEntityDescription(
        key="heat_demand",
        ramses_rf_attr="heat_demand",
        native_unit_of_measurement=PERCENTAGE,
    )
    mock_device.heat_demand = 0.55
    sensor = RamsesSensor(mock_broker, mock_device, desc)

    assert sensor.native_value == pytest.approx(55.0)
    mock_device.heat_demand = None
    assert sensor.native_value is None


def test_sensor_icon_override(mock_broker: MagicMock, mock_device: MagicMock) -> None:
    """Test icon override when the value is zero/None.

    :param mock_broker: The mock broker fixture.
    :param mock_device: The mock device fixture.
    """
    desc = RamsesSensorEntityDescription(
        key="relay_demand",
        ramses_rf_attr="relay_demand",
        icon="mdi:power-plug",
        ramses_cc_icon_off="mdi:power-plug-off",
    )
    mock_device.relay_demand = 0
    sensor = RamsesSensor(mock_broker, mock_device, desc)

    assert sensor.icon == "mdi:power-plug-off"
    mock_device.relay_demand = 1
    assert sensor.icon == "mdi:power-plug"


async def test_sensor_put_services(
    mock_broker: MagicMock, mock_device: MagicMock
) -> None:
    """Test all async_put service calls.

    :param mock_broker: The mock broker fixture.
    :param mock_device: The mock device fixture.
    """
    from ramses_rf.device.hvac import HvacCarbonDioxideSensor

    co2_device = MagicMock(spec=HvacCarbonDioxideSensor)
    co2_device.id = SENSOR_ID
    co2_desc = RamsesSensorEntityDescription(
        key="co2",
        ramses_rf_attr="co2_level",
        device_class=SensorDeviceClass.CO2,
        native_unit_of_measurement=CONCENTRATION_PARTS_PER_MILLION,
    )
    co2_sensor = RamsesSensor(mock_broker, co2_device, co2_desc)
    co2_sensor.async_put_co2_level(1000)
    assert co2_device.co2_level == 1000

    from ramses_rf.device.heat import DhwSensor

    dhw_device = MagicMock(spec=DhwSensor)
    dhw_device.id = SENSOR_ID
    dhw_desc = RamsesSensorEntityDescription(
        key="temp",
        ramses_rf_attr="temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
    )
    dhw_sensor = RamsesSensor(mock_broker, dhw_device, dhw_desc)
    dhw_sensor.async_put_dhw_temp(60.0)
    assert dhw_device.temperature == 60.0

    from ramses_rf.device.hvac import HvacHumiditySensor

    hum_device = MagicMock(spec=HvacHumiditySensor)
    hum_device.id = SENSOR_ID
    hum_desc = RamsesSensorEntityDescription(
        key="hum",
        ramses_rf_attr="indoor_humidity",
        device_class=SensorDeviceClass.HUMIDITY,
        native_unit_of_measurement=PERCENTAGE,
    )
    hum_sensor = RamsesSensor(mock_broker, hum_device, hum_desc)
    hum_sensor.async_put_indoor_humidity(50.0)
    assert hum_device.indoor_humidity == 0.5

    from ramses_rf.device.heat import Thermostat

    tstat_device = MagicMock(spec=Thermostat)
    tstat_device.id = SENSOR_ID
    tstat_sensor = RamsesSensor(mock_broker, tstat_device, dhw_desc)
    tstat_sensor.async_put_room_temp(21.0)
    assert tstat_device.temperature == 21.0


async def test_sensor_put_errors(mock_broker: MagicMock) -> None:
    """Test TypeError raised when service is called on wrong device type.

    :param mock_broker: The mock broker fixture.
    """
    co2_desc = RamsesSensorEntityDescription(
        key="co2",
        ramses_rf_attr="co2_level",
        device_class=SensorDeviceClass.CO2,
        native_unit_of_measurement=CONCENTRATION_PARTS_PER_MILLION,
    )
    generic_device = MagicMock()
    generic_device.id = SENSOR_ID
    co2_sensor = RamsesSensor(mock_broker, generic_device, co2_desc)

    with pytest.raises(TypeError, match="Cannot set CO2 level"):
        co2_sensor.async_put_co2_level(500)

    dhw_desc = RamsesSensorEntityDescription(
        key="temp",
        ramses_rf_attr="temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
    )
    dhw_sensor = RamsesSensor(mock_broker, generic_device, dhw_desc)
    with pytest.raises(TypeError, match="Cannot set CO2 level"):
        dhw_sensor.async_put_dhw_temp(50.0)

    hum_desc = RamsesSensorEntityDescription(
        key="hum",
        ramses_rf_attr="indoor_humidity",
        device_class=SensorDeviceClass.HUMIDITY,
        native_unit_of_measurement=PERCENTAGE,
    )
    hum_sensor = RamsesSensor(mock_broker, generic_device, hum_desc)
    with pytest.raises(TypeError, match="Cannot set indoor humidity"):
        hum_sensor.async_put_indoor_humidity(50.0)

    tstat_sensor = RamsesSensor(mock_broker, generic_device, dhw_desc)
    with pytest.raises(TypeError, match="Cannot set CO2 level"):
        tstat_sensor.async_put_room_temp(20.0)
