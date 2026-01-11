#!/usr/bin/env python3
"""RAMSES RF - a RAMSES-II protocol decoder & analyser."""

from ramses_rf import Device
from ramses_rf.binding_fsm import BindContext
from ramses_rf.device import Fakeable


def ensure_fakeable(dev: Device, make_fake: bool = True) -> None:
    """Ensure a Device is Fakeable (i.e. has Fakeable mixin).

    :param dev: The device to ensure is fakeable.
    :param make_fake: Whether to call _make_fake() on the device.
    """

    class _Fakeable(dev.__class__, Fakeable):
        pass

    if isinstance(dev, Fakeable):
        return

    dev.__class__ = _Fakeable
    assert isinstance(dev, Fakeable)

    setattr(dev, "_bind_context", BindContext(dev))  # noqa: B010

    if make_fake:
        dev._make_fake()
