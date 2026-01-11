"""Tests to achieve 100% coverage for the virtual_rf package.

This module targets edge cases in hardware emulation, error handling,
and factory logic that are not exercised by standard integration tests.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ramses_rf.const import DevType
from ramses_rf.schemas import SZ_CLASS, SZ_KNOWN_LIST
from tests.virtual_rf import (
    VirtualRf,
    _get_hgi_id_for_schema,
    main as virtual_rf_main,
    rf_factory,
)
from tests.virtual_rf.const import HgiFwTypes
from tests.virtual_rf.helpers import ensure_fakeable
from tests.virtual_rf.virtual_rf import VirtualRfBase


@pytest.mark.asyncio
async def test_virtual_rf_init_errors() -> None:
    """Test VirtualRf initialization error paths.

    Verifies that the engine enforces the maximum port limit.
    """
    # Note: If this fails to raise, check virtual_rf.py line 125
    # for the specific comparison operator used for num_ports.
    with pytest.raises(ValueError, match="Port limit exceeded"):
        VirtualRf(7)
        # await rf.stop() is unreachable here


def test_virtual_rf_init_windows_error() -> None:
    """Test OS check in VirtualRf init (mocking Windows/NT)."""
    with (
        patch("tests.virtual_rf.virtual_rf.os.name", "nt"),
        pytest.raises(RuntimeError, match="Unsupported OS"),
    ):
        VirtualRf(1)


@pytest.mark.asyncio
async def test_virtual_rf_gateway_errors() -> None:
    """Test error paths when configuring gateways on the virtual RF.

    Covers invalid port lookups and duplicate gateway IDs.
    """
    rf = VirtualRf(2)
    try:
        # 1. Test non-existent port
        with pytest.raises(LookupError, match="Port does not exist"):
            rf.set_gateway("/dev/pts/nonexistent", "18:111111")

        # 2. Setup valid port
        rf.set_gateway(rf.ports[0], "18:111111")

        # 3. Test duplicate gateway ID on a different port
        with pytest.raises(LookupError, match="Gateway exists on another port"):
            rf.set_gateway(rf.ports[1], "18:111111")

        # 4. Test unknown firmware type
        with pytest.raises(LookupError, match="Unknown FW specified"):
            rf.set_gateway(rf.ports[1], "18:222222", fw_type="INVALID_FW")
    finally:
        await rf.stop()


@pytest.mark.asyncio
async def test_virtual_rf_evofw3_trace_and_version() -> None:
    """Test evofw3 specific trace flags (!) and version command.

    Verifies that the engine handles '!' commands appropriately for evofw3.
    """
    rf = VirtualRf(1)
    port = rf.ports[0]
    rf.set_gateway(port, "18:111111", fw_type=HgiFwTypes.EVOFW3)

    # 1. Test version command (!V)
    assert rf._proc_after_rx(port, b"!V") == b"# evofw3 0.7.1\r\n"

    # 2. Test unknown trace flag after Rx (should return None)
    assert rf._proc_after_rx(port, b"!X") is None

    # 3. Test trace flag before Tx (should trigger push and return None)
    # If this fails, ensure the gateway is correctly mapped in rf._gateways
    assert rf._proc_before_tx(port, b"!X") is None
    await rf.stop()


@pytest.mark.asyncio
async def test_virtual_rf_hgi80_logic() -> None:
    """Test HGI80 specific behavior (dropping frames with wrong addr0).

    Verifies addr0 filtering and swapping logic specific to HGI80 hardware.
    """
    rf = VirtualRf(1)
    port = rf.ports[0]
    rf.set_gateway(port, "18:222222", fw_type=HgiFwTypes.HGI_80)

    # 1. HGI80 drops frames if addr0 is not 18:000730
    # Note: frame must be "raw" (no RSSI prefix) for _proc_before_tx
    bad_frame = b"RQ --- 18:111111 01:123456 --:-- 3EF0 001 00"
    assert rf._proc_before_tx(port, bad_frame) is None

    # 2. HGI80 accepts 18:000730 and swaps it with the actual gateway ID
    good_frame = b"RQ --- 18:000730 01:123456 --:-- 3EF0 001 00"
    processed = rf._proc_before_tx(port, good_frame)
    assert processed is not None
    assert b"18:222222" in processed
    await rf.stop()


@pytest.mark.asyncio
async def test_virtual_rf_no_gateway_logic() -> None:
    """Test logic when no gateway is assigned to a port."""
    rf = VirtualRf(1)
    port = rf.ports[0]
    # No gateway set on this port

    # 1. _proc_before_tx returns frame as-is if no gateway found
    frame = b"RQ --- 18:000730 01:123456 --:-- 0005 002 00"
    assert rf._proc_before_tx(port, frame) == frame

    # 2. _proc_after_rx returns None if no gateway found and frame is a trace flag
    assert rf._proc_after_rx(port, b"!V") is None

    await rf.stop()


def test_get_hgi_id_schema_errors() -> None:
    """Test schema parsing errors in virtual_rf init.

    Ensures that invalid schemas (multiple/misconfigured HGI) are rejected.
    """
    # 1. Test Multiple gateways per schema
    schema_multi = {
        SZ_KNOWN_LIST: {
            "18:111111": {SZ_CLASS: DevType.HGI},
            "18:222222": {SZ_CLASS: DevType.HGI},
        }
    }
    with pytest.raises(TypeError, match="Multiple Gateways"):
        _get_hgi_id_for_schema(schema_multi, 0)

    # 2. Test Missing HGI class on 18: device
    schema_no_class: dict[str, Any] = {SZ_KNOWN_LIST: {"18:111111": {}}}
    with pytest.raises(TypeError, match="must have its class defined explicitly"):
        _get_hgi_id_for_schema(schema_no_class, 0)


@pytest.mark.asyncio
async def test_rf_factory_coverage() -> None:
    """Test factory edge cases and port limits.

    Validates the creation of VirtualRf instances from schemas.
    """
    # 1. Test Max ports (7 schemas for a 6-port limit)
    with pytest.raises(TypeError, match="maximum of 6 ports"):
        await rf_factory([None] * 7)

    # 2. Test None schema entry
    rf, gwys = await rf_factory([None], start_gwys=False)
    try:
        assert len(rf.ports) == 1
        assert len(gwys) == 0
    finally:
        await rf.stop()


@pytest.mark.asyncio
async def test_helpers_ensure_fakeable() -> None:
    """Test the ensure_fakeable utility in helpers.py.

    Verifies dynamic class mutation for faked devices.
    """

    class DummyDevice:
        """A minimal mock device."""

        def __init__(self) -> None:
            self.id = "01:123456"
            self._gwy = MagicMock()  # Mock gateway for BindContext

    dev: Any = DummyDevice()
    # Initial transition to _Fakeable
    ensure_fakeable(dev, make_fake=False)
    assert "_Fakeable" in dev.__class__.__name__

    # Re-running on already fakeable device should return early
    ensure_fakeable(dev, make_fake=False)

    # Test make_fake=True (triggers dev._make_fake())
    dev2: Any = DummyDevice()
    ensure_fakeable(dev2, make_fake=True)
    assert "_Fakeable" in dev2.__class__.__name__


@pytest.mark.asyncio
async def test_virtual_rf_replies() -> None:
    """Test the command/reply matching logic.

    Verifies that the virtual RF can simulate replies for specific commands.
    """
    rf = VirtualRf(1)

    # 1. Add a reply rule
    cmd_regex = "RQ.* 01:123456"
    reply_pkt = "RP --- 01:123456 18:111111 --:------ 0006 001 00"
    rf.add_reply_for_cmd(cmd_regex, reply_pkt)

    # 2. Manually check regex match logic
    cmd_bytes = b"RQ --- 18:111111 01:123456 --:------ 0006 001 00\r\n"
    matched = rf._find_reply_for_cmd(cmd_bytes)
    assert matched is not None
    assert b"0006 001 00" in matched

    # 3. Trigger the cast logic via dump_frames_to_rf
    # This ensures lines 271-273 in virtual_rf.py (reply casting) are executed
    await rf.dump_frames_to_rf([cmd_bytes])

    # Verify the reply ended up in the log (indicating it was cast to ports)
    # The reply "RP ..." doesn't start with "!", so _proc_after_rx adds "000 "
    has_reply = any(b"0006 001 00" in entry[2] for entry in rf._log)
    assert has_reply

    await rf.stop()


@pytest.mark.asyncio
async def test_rf_factory_hgi_logic() -> None:
    """Test specific HGI logic in rf_factory schema parsing."""

    # 1. Explicit HGI class with custom FW type
    schema_explicit = {
        SZ_KNOWN_LIST: {
            "18:111111": {SZ_CLASS: DevType.HGI, "_type": HgiFwTypes.EVOFW3}
        }
    }
    rf, gwys = await rf_factory([schema_explicit], start_gwys=False)
    try:
        assert rf.gateways["18:111111"] == rf.ports[0]
        # Check if fw_type was correctly identified
        assert rf._gateways[rf.ports[0]]["fw_type"] == HgiFwTypes.EVOFW3
    finally:
        await rf.stop()

    # 2. Ambiguous HGI (implied by ID but no class) -> TypeError
    schema_ambiguous: dict[str, Any] = {
        SZ_KNOWN_LIST: {
            "18:222222": {}  # Missing SZ_CLASS: DevType.HGI
        }
    }
    with pytest.raises(TypeError, match="class defined explicitly"):
        await rf_factory([schema_ambiguous], start_gwys=False)


@pytest.mark.asyncio
async def test_rf_factory_start_gwys() -> None:
    """Test rf_factory with start_gwys=True."""

    # We patch Gateway to control the instance and its transport
    # rf_factory imports Gateway from ramses_rf, so we patch it where it is used
    with patch("tests.virtual_rf.Gateway") as MockGateway:
        mock_gwy = MockGateway.return_value
        mock_gwy.start = AsyncMock()
        mock_gwy._transport = MagicMock()
        mock_gwy._transport._extra = {}

        # Use an empty schema dict to trigger gateway creation
        rf, gwys = await rf_factory([{}], start_gwys=True)
        try:
            assert len(gwys) == 1
            mock_gwy.start.assert_called_once()

            # Verify the virtual_rf injection into transport
            # Note: We need to ensure transport exists, which Gateway() creates.
            assert mock_gwy._transport._extra["virtual_rf"] == rf
        finally:
            await rf.stop()


@pytest.mark.asyncio
async def test_virtual_rf_dump_and_main() -> None:
    """Test dump_frames_to_rf and main function for full coverage."""
    rf = VirtualRf(1)
    try:
        # Test dump_frames_to_rf
        # This injects frames as if they were transmitted by a mock device
        test_frame = b"RQ --- 18:000000 01:000000 --:-- 0000 000 00"
        await rf.dump_frames_to_rf([test_frame])

        # Test dump frames with timeout AND force the wait loop to run.
        # We mock select to return True once, then False (to exit loop).
        # This ensures the 'while' loop runs once (await asyncio.sleep) and then exits.
        # We pass an iterator that will NOT raise StopIteration, just yield False forever after True.

        select_responses = iter([True, False, False, False])

        def mock_select(*args: Any, **kwargs: Any) -> list[Any]:
            try:
                val = next(select_responses)
                return [val] if val else []
            except StopIteration:
                return []

        with patch.object(rf._selector, "select", side_effect=mock_select):
            await rf.dump_frames_to_rf([test_frame], timeout=0.01)

            # Manually exhaust the iterator to cover the `except StopIteration` block
            # We consumed True, False (loop exit).
            # Call it enough times to hit StopIteration
            for _ in range(5):
                mock_select()

        # Check that logic put something in the log
        assert len(rf._log) > 0
    finally:
        await rf.stop()

    # Test the standalone main() function
    # Mocking serial.Serial to avoid real hardware/PTY ops during this test
    with (
        patch("tests.virtual_rf.virtual_rf.Serial", MagicMock()),
        patch("tests.virtual_rf.virtual_rf.serial_for_url", MagicMock()),
    ):
        await virtual_rf_main()


@pytest.mark.asyncio
async def test_virtual_rf_stop_idempotency() -> None:
    """Test that stop() can be called multiple times without error."""
    rf = VirtualRf(1)
    await rf.stop()
    await rf.stop()  # Should be no-op


@pytest.mark.asyncio
async def test_virtual_rf_rx_filtering() -> None:
    """Test additional Rx filtering logic."""
    rf = VirtualRf(1)
    port = rf.ports[0]

    # Ensure regular frame passes through (returns None, meaning no modification/blocking for now)
    # The default impl returns "000 " + frame unless it's a ! command
    res = rf._proc_after_rx(port, b"RQ --- ...")
    assert res == b"000 RQ --- ..."

    # Test filtering when gateway is not EVOFW3 for ! commands
    rf.set_gateway(port, "18:222222", fw_type=HgiFwTypes.HGI_80)
    assert rf._proc_after_rx(port, b"!V") is None
    # Cover line 443 in virtual_rf.py:
    # If the gateway is not EVOFW3, ! commands are NOT transmitted
    assert rf._proc_before_tx(port, b"!V") is None

    await rf.stop()


@pytest.mark.asyncio
async def test_virtual_rf_setup_event_handlers() -> None:
    """Test the _setup_event_handlers method and internal functions."""
    rf = VirtualRf(1)
    try:
        # 1. Test running setup_event_handlers on POSIX (default in this environment)
        # Mocking loop to capture the handlers registered
        with patch.object(rf, "_loop") as mock_loop:
            rf._setup_event_handlers()

            # Verify signal handlers were added
            assert (
                mock_loop.add_signal_handler.call_count == 3
            )  # SIGABRT, SIGINT, SIGTERM

            # Verify exception handler was set
            args, _ = mock_loop.set_exception_handler.call_args
            exception_handler = args[0]

            # 2. Execute the inner 'handle_exception' function
            # Patch _cleanup to avoid closing FDs prematurely during this test phase
            with patch.object(rf, "_cleanup"):
                # Case A: Exception present in context
                context = {"message": "Test Error", "exception": ValueError("Boom")}
                with pytest.raises(ValueError, match="Boom"):
                    exception_handler(mock_loop, context)

                # Case B: No exception in context (just message)
                context_no_exc = {"message": "Just a warning"}
                exception_handler(mock_loop, context_no_exc)  # Should not raise

            # 3. Execute the inner 'handle_sig_posix' function via the lambda registration
            # The add_signal_handler call args are (signal, callback)
            # The callback is a lambda that calls create_task
            sig_args, _ = mock_loop.add_signal_handler.call_args_list[0]
            sig_lambda = sig_args[1]

            # Call the lambda, which calls create_task
            sig_lambda()
            assert mock_loop.create_task.called

            # 4. Trigger the coroutine directly to test handle_sig_posix body
            # The lambda calls create_task(coro). We can extract that coro and await it.
            coro = mock_loop.create_task.call_args[0][0]

            # We mock signal.raise_signal to prevent actual signal propagation
            with (
                patch("tests.virtual_rf.virtual_rf.signal.raise_signal") as mock_raise,
                patch.object(rf, "_cleanup") as mock_cleanup,
            ):
                await coro
                mock_cleanup.assert_called_once()
                mock_raise.assert_called_once()

        # 5. Test Non-POSIX path (Windows)
        with (
            patch("tests.virtual_rf.virtual_rf.os.name", "nt"),
            pytest.raises(RuntimeError, match="Unsupported OS"),
        ):
            rf._setup_event_handlers()

    finally:
        await rf.stop()


@pytest.mark.asyncio
async def test_virtual_rf_base_methods() -> None:
    """Test VirtualRfBase specific methods (base implementation)."""

    # We instantiate VirtualRfBase directly to test its default behavior
    # before it is overridden by VirtualRf
    rf_base = VirtualRfBase(1)
    try:
        # Default behavior is pass-through
        assert rf_base._proc_after_rx("port", b"data") == b"data"
        assert rf_base._proc_before_tx("port", b"data") == b"data"
    finally:
        await rf_base.stop()
