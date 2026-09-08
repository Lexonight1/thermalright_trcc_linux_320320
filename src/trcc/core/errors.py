"""Domain exception hierarchy."""
from __future__ import annotations


class TrccError(Exception):
    """Base for all TRCC domain errors."""


class DeviceNotFoundError(TrccError):
    """No device matched the requested identity."""


class DeviceNotConnectedError(TrccError):
    """Operation required a connected device; none was attached."""


class HandshakeError(TrccError):
    """Device handshake failed or returned invalid data."""


class TransportError(TrccError):
    """Underlying USB/transport layer failed."""


class DeviceDisconnectedError(TransportError):
    """Send failed N consecutive times with a disconnect-class errno.

    Raised by ``Device.send`` after the recovery tracker hits the
    consecutive-disconnect threshold.  The device's transport is
    closed before the raise so the next send attempt will get a
    fresh handle (or fail fast if the device is genuinely gone).

    Commands that catch :class:`TransportError` will catch this too
    (it's a subclass); use ``isinstance`` to publish the more specific
    :class:`DeviceDisconnected` event for the auto-detach path.
    """


class PermissionError_(TrccError):
    """Host OS denied access (missing udev rule, kernel driver, etc.)."""


class UnsupportedOperationError(TrccError):
    """Device or protocol doesn't support the requested operation."""


class UnknownUserInterfaceError(TrccError):
    """No :class:`~trcc.ui.UserInterface` is registered under that name.

    Raised by the ``UIS`` registry's miss policy.  Like an unregistered wire
    and unlike an unknown OS, this is a DEFECT rather than something to
    degrade through: a caller asking for a UI that does not exist has a typo
    or a stale entry point, and silently substituting another face of the app
    would be worse than stopping.
    """


class ConfigError(TrccError):
    """Persistent settings / config file is invalid or unreadable."""


class ThemeError(TrccError):
    """Theme load / parse / export failed."""


class HttpFetchError(RuntimeError):
    """Raised on any transport or HTTP-level fetch failure.

    Subclasses ``RuntimeError`` (not ``TrccError``) deliberately: the
    HTTP adapter and several call sites catch it as ``RuntimeError``,
    and the broad ``except TrccError`` handlers in ``commands.py``
    must NOT swallow network failures — those map to user-facing
    "couldn't reach the server" messages, not generic command errors.
    Lives in core so Commands import it without reaching into the
    ``adapters.repo`` layer.
    """
