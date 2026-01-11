"""
Unit tests to achieve 100% coverage for tests_old/helpers.py.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

import pytest

from ramses_rf.gateway import Gateway
from tests.tests_old.helpers import (
    cast_packets_to_rf,
    no_data_left_to_read,
    normalise_storage_file,
)


def test_normalise_storage_file_with_packets() -> None:
    """
    Test normalise_storage_file with actual packet data to cover the dict comprehension.

    :return: None
    """
    mock_data = {
        "key": "ramses_cc",
        "version": 1,
        "data": {
            "client_state": {
                "packets": {
                    "old_ts": "packet_1",
                    "older_ts": "packet_2",
                }
            }
        },
    }

    with (
        patch("builtins.open", MagicMock()),
        patch("tests.tests_old.helpers.json.load", return_value=mock_data),
        patch("tests.tests_old.helpers.STORAGE_KEY", "ramses_cc"),
        patch("tests.tests_old.helpers.STORAGE_VERSION", 1),
    ):
        result = normalise_storage_file("fake_path.json")

        packets = result["ramses_cc"]["data"]["client_state"]["packets"]
        assert len(packets) == 2
        for timestamp in packets:
            assert isinstance(timestamp, str)
            assert "T" in timestamp


@pytest.mark.asyncio
async def test_no_data_left_to_read_loop() -> None:
    """
    Test the sleep loop in no_data_left_to_read.

    :return: None
    """
    # Create the nested mock structure manually
    mock_gwy = MagicMock(spec=Gateway)
    mock_transport = MagicMock()
    mock_gwy._transport = mock_transport  # Manually attach protected attribute

    # 1st call: data exists (enters loop), 2nd call: empty (exits loop)
    type(mock_transport.serial).in_waiting = PropertyMock(side_effect=[1, 0])

    with patch("tests.tests_old.helpers.asyncio.sleep", AsyncMock()) as mock_sleep:
        await no_data_left_to_read(mock_gwy)
        assert mock_sleep.call_count == 1


@pytest.mark.asyncio
async def test_cast_packets_to_rf_with_gwy() -> None:
    """
    Test cast_packets_to_rf specifically triggering the gateway wait block.

    :return: None
    """
    mock_rf = AsyncMock()
    mock_gwy = MagicMock(spec=Gateway)
    mock_transport = MagicMock()
    mock_gwy._transport = mock_transport

    # Mock serial in_waiting to be 0 so no_data_left_to_read exits immediately
    type(mock_transport.serial).in_waiting = PropertyMock(return_value=0)

    # Mock a single valid log line
    log_line = (
        "2024-01-01 12:00:00.000000 ... RQ --- 18:000001 01:123456 --:-- 3EF0 001 00\n"
    )

    with (
        patch(
            "tests.tests_old.helpers.open",
            MagicMock(
                return_value=MagicMock(__enter__=MagicMock(return_value=[log_line]))
            ),
        ),
        patch("tests.tests_old.helpers.Command", return_value="RQ ... 3EF0 001 00"),
        patch("tests.tests_old.helpers.asyncio.sleep", AsyncMock()),
        patch("tests.tests_old.helpers.no_data_left_to_read", AsyncMock()) as mock_wait,
    ):
        await cast_packets_to_rf(mock_rf, "fake.log", gwy=mock_gwy)

        # Verify the 'if gwy:' block was executed
        mock_wait.assert_called_once_with(mock_gwy)
