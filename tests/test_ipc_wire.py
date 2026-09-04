"""IPC wire-format round-trip tests.

Pure-data checks: encode + decode are inverses for Commands and
Results across primitive fields, Path, Enum, tuple, list, and nested
frozen dataclasses.  No socket / threads — the transport layer
gets its own coverage in test_ipc_server.py.
"""
from __future__ import annotations

import dataclasses
import inspect
import json
import typing
from pathlib import Path

import pytest

from trcc.core.commands import (
    LoadTheme,
    SendColor,
    SetBrightness,
    SetFitMode,
    SetOrientation,
    UploadBootAnimation,
)
from trcc.core.events import (
    Event,
    FrameSent,
    SensorsUpdated,
    SystemResumed,
)
from trcc.core.models import (
    DeviceInfo,
    HandshakeResult,
    HardwareMetrics,
    Kind,
    PanelCutout,
    ProductInfo,
    Wire,
)
from trcc.core.results import (
    ConnectResult,
    DiscoverResult,
    Result,
    SendResult,
)
from trcc.ipc import (
    COMMAND_TYPES,
    EVENT_TYPES,
    RESULT_TYPES,
    decode_command,
    decode_event,
    decode_result,
    encode_command,
    encode_event,
    encode_result,
)

# ── Registries are populated at import ──────────────────────────────


def test_command_registry_collects_every_command_subclass() -> None:
    """EVERY Command defined under ``core/commands/`` is reachable by name.

    Enumerated, not sampled.  This assertion used to name 21 commands against
    a registry of 136 — 15% — which is a sample wearing a gate's name.

    What it guards is a silent failure.  Dispatch is zero-touch
    (``App.dispatch`` is ``cmd.execute(self)``, no handler map), but
    ``COMMAND_TYPES`` is collected from the ``core.commands`` package
    namespace and ``core/commands/__init__.py`` is a hand-maintained export
    list.  A Command defined in a submodule and not re-exported therefore
    works in-process, is UNDISPATCHABLE over IPC, is invisible to the parity
    audit and to any generated reference — and passes the whole suite.
    """
    import importlib
    import pkgutil

    import trcc.core.commands as pkg
    from trcc.core.commands._base import Command, Query

    defined: dict[str, str] = {}
    for mod_info in pkgutil.iter_modules(pkg.__path__):
        module = importlib.import_module(f"trcc.core.commands.{mod_info.name}")
        for name, obj in vars(module).items():
            if (inspect.isclass(obj) and issubclass(obj, Command)
                    and obj not in (Command, Query)
                    and obj.__module__ == module.__name__):
                defined[name] = mod_info.name

    unexported = {n: m for n, m in defined.items() if n not in COMMAND_TYPES}
    assert not unexported, (
        "these Commands are defined but not re-exported from "
        "core/commands/__init__.py, so they are undispatchable over IPC and "
        "invisible to the contract audit:\n"
        + "\n".join(f"  {n}  (core/commands/{m}.py)"
                     for n, m in sorted(unexported.items()))
    )
    assert len(defined) >= 100, (
        f"only {len(defined)} Commands discovered — the collector is probably "
        "broken, not the tree"
    )


def test_result_registry_collects_every_result_subclass() -> None:
    expected = {"DiscoverResult", "ConnectResult", "SendResult",
                "RenderResult", "ThemeResult", "OrientationResult",
                "BrightnessResult", "BootAnimationResult"}
    missing = expected - set(RESULT_TYPES)
    assert not missing, f"Missing from registry: {missing}"


# ── Command round-trip — primitives ────────────────────────────────


def test_send_color_roundtrip() -> None:
    cmd = SendColor(key="0402:3922", r=255, g=128, b=0)
    envelope = encode_command(cmd)

    assert envelope == {
        "command": "SendColor",
        "kwargs": {"key": "0402:3922", "r": 255, "g": 128, "b": 0},
    }

    rebuilt = decode_command(envelope)
    assert isinstance(rebuilt, SendColor)
    assert rebuilt == cmd


def test_set_brightness_roundtrip() -> None:
    cmd = SetBrightness(key="0402:3922", percent=42)
    rebuilt = decode_command(encode_command(cmd))
    assert isinstance(rebuilt, SetBrightness)
    assert rebuilt == cmd


def test_set_orientation_roundtrip() -> None:
    cmd = SetOrientation(key="0402:3922", degrees=90)
    rebuilt = decode_command(encode_command(cmd))
    assert isinstance(rebuilt, SetOrientation)
    assert rebuilt == cmd


def test_set_fit_mode_roundtrip_string_field() -> None:
    cmd = SetFitMode(key="0402:3922", mode="width")
    rebuilt = decode_command(encode_command(cmd))
    assert isinstance(rebuilt, SetFitMode)
    assert rebuilt == cmd


# ── Command round-trip — Path field ────────────────────────────────


def test_load_theme_serializes_path_as_string() -> None:
    cmd = LoadTheme(key="0402:3922", path=Path("/tmp/some/theme"))
    envelope = encode_command(cmd)

    # Path goes to the wire as a plain str (json-friendly)
    assert envelope["kwargs"]["path"] == "/tmp/some/theme"

    rebuilt = decode_command(envelope)
    assert isinstance(rebuilt, LoadTheme)
    assert rebuilt.path == Path("/tmp/some/theme")
    assert isinstance(rebuilt.path, Path)


# ── Command round-trip — list[Path] field ──────────────────────────


def test_upload_boot_animation_roundtrip_list_of_paths() -> None:
    frames = [Path("/tmp/f0.png"), Path("/tmp/f1.png"), Path("/tmp/f2.png")]
    cmd = UploadBootAnimation(
        key="0402:3922",
        frame_paths=frames,
        delays_ds=[10, 10, 10],
    )
    envelope = encode_command(cmd)

    # Paths serialize as strings on the wire
    assert envelope["kwargs"]["frame_paths"] == [
        "/tmp/f0.png", "/tmp/f1.png", "/tmp/f2.png",
    ]
    assert envelope["kwargs"]["delays_ds"] == [10, 10, 10]

    rebuilt = decode_command(envelope)
    assert isinstance(rebuilt, UploadBootAnimation)
    assert rebuilt.frame_paths == frames
    assert all(isinstance(p, Path) for p in rebuilt.frame_paths)
    assert rebuilt.delays_ds == [10, 10, 10]


# ── Result round-trip — flat ──────────────────────────────────────


def test_send_result_roundtrip() -> None:
    result = SendResult(ok=True, message="Sent 1024 bytes",
                        key="0402:3922", bytes_sent=1024)
    envelope = encode_result(result)
    assert envelope["type"] == "SendResult"
    assert envelope["ok"] is True
    assert envelope["bytes_sent"] == 1024

    rebuilt = decode_result(envelope)
    assert isinstance(rebuilt, SendResult)
    assert rebuilt == result


# ── Result round-trip — nested dataclass + tuple ──────────────────


def test_connect_result_roundtrip_with_handshake() -> None:
    """HandshakeResult survives nested-dataclass coercion (resolution tuple)."""
    handshake = HandshakeResult(
        resolution=(320, 320),
        model_id=100,
        pm_byte=100,
        sub_byte=0,
        fbl=100,
        raw_response=b"\x64" + b"\x00" * 63,
    )
    result = ConnectResult(
        ok=True, message="Connected: (320, 320)",
        key="0402:3922", handshake=handshake,
    )

    envelope = encode_result(result)
    rebuilt = decode_result(envelope)

    assert isinstance(rebuilt, ConnectResult)
    assert rebuilt.handshake is not None
    assert rebuilt.handshake.resolution == (320, 320)
    assert isinstance(rebuilt.handshake.resolution, tuple)
    assert rebuilt.handshake.fbl == 100
    assert rebuilt.handshake.raw_response == b"\x64" + b"\x00" * 63


# ── Discover result with list[ProductInfo] ─────────────────────────


def test_discover_result_with_empty_lists_roundtrips() -> None:
    result = DiscoverResult(ok=True, message="No devices", products=[], devices=[])
    rebuilt = decode_result(encode_result(result))
    assert isinstance(rebuilt, DiscoverResult)
    assert rebuilt.products == []
    assert rebuilt.devices == []


def test_discover_result_with_products_roundtrips() -> None:
    """Regression guard (859634af): a NON-EMPTY ProductInfo must survive the
    wire.  The empty-lists case above never builds a ProductInfo, so it missed
    the bug where ``decode_result`` → ``get_type_hints(ProductInfo)`` raised
    ``NameError`` on the TYPE_CHECKING-only ``PanelCutout`` annotation.  Any
    non-empty products list triggers it; the explicit PanelCutout also asserts
    the nested value survives."""
    product = ProductInfo(
        vid=0x0402, pid=0x3922, vendor="Acme", product="Test LCD",
        wire=Wire.SCSI, kind=Kind.LCD, native_resolution=(320, 320),
        panel_cutout=PanelCutout(x=10, y=20, w=30, h=40),
    )
    result = DiscoverResult(
        ok=True, message="1 device",
        products=[product], devices=[DeviceInfo(vid=0x0402, pid=0x3922)],
    )

    rebuilt = decode_result(encode_result(result))

    assert isinstance(rebuilt, DiscoverResult)
    assert len(rebuilt.products) == 1
    p = rebuilt.products[0]
    assert (p.vid, p.pid, p.product) == (0x0402, 0x3922, "Test LCD")
    assert p.wire is Wire.SCSI and p.kind is Kind.LCD
    assert p.native_resolution == (320, 320)
    assert p.panel_cutout == PanelCutout(x=10, y=20, w=30, h=40)
    assert len(rebuilt.devices) == 1
    assert (rebuilt.devices[0].vid, rebuilt.devices[0].pid) == (0x0402, 0x3922)


# ── Falls back to base Result for unknown types ────────────────────


def test_unknown_result_type_falls_back_to_base() -> None:
    rebuilt = decode_result({"type": "NotAResult", "ok": False,
                             "message": "garbage"})
    assert isinstance(rebuilt, Result)
    assert rebuilt.ok is False
    assert rebuilt.message == "garbage"


def test_unknown_command_decode_raises_clear_error() -> None:
    import pytest

    with pytest.raises(ValueError, match="Unknown command"):
        decode_command({"command": "NotACommand", "kwargs": {}})


def test_missing_command_key_decode_raises() -> None:
    import pytest

    with pytest.raises(ValueError, match="missing 'command'"):
        decode_command({"kwargs": {}})


# ── Event round-trip — the whole registry, not a sample ─────────────
#
# Events are the half daemon mode never had: ``AppProxy`` exposes dispatch
# only, so both GUIs raise ``AttributeError`` on ``app.events`` the moment
# TRCC_DAEMON=1.  This gates the codec that unblocks them.


def _sample(hint: object, field_name: str) -> object:
    """A non-default value for *hint*, so a dropped field can't pass.

    Raises on a type it doesn't know: a new event field whose type the wire
    has never carried should fail here loudly rather than go untested.
    """
    import types as _types

    origin = typing.get_origin(hint)
    args = typing.get_args(hint)

    if origin in (typing.Union, _types.UnionType):
        return _sample([a for a in args if a is not type(None)][0], field_name)
    if origin is tuple:
        if len(args) == 2 and args[1] is Ellipsis:
            return (_sample(args[0], field_name),)
        return tuple(_sample(a, field_name) for a in args)
    if origin is list:
        return [_sample(args[0], field_name)] if args else []
    if origin is dict:
        return {"sample_key": _sample(args[1], field_name)} if args else {}
    if hint is str:
        return f"value-for-{field_name}"
    if hint is bool:
        return True
    if hint is int:
        return 7
    if hint is float:
        return 1.5
    if hint is typing.Any:
        return None          # in-process-only field; None is the wire value
    if dataclasses.is_dataclass(hint) and isinstance(hint, type):
        hints = typing.get_type_hints(hint)
        return hint(**{f.name: _sample(hints[f.name], f.name)
                       for f in dataclasses.fields(hint)})
    raise AssertionError(
        f"no wire sample defined for {hint!r} (field {field_name!r}) — "
        "teach _sample about it, or the field is untested",
    )


def _populated(cls: type) -> object:
    hints = typing.get_type_hints(cls)
    return cls(**{f.name: _sample(hints[f.name], f.name)
                  for f in dataclasses.fields(cls)})


@pytest.mark.parametrize("name", sorted(EVENT_TYPES))
def test_every_event_type_survives_the_wire(name: str) -> None:
    """Exhaustive: every registered event, every field, JSON-clean and equal.

    Parametrized over the registry rather than a hand-written list, so an
    event added later is covered without anyone remembering to add it.
    """
    event = _populated(EVENT_TYPES[name])
    envelope = encode_event(event)

    json.dumps(envelope)          # must survive the actual transport
    assert envelope["event"] == name

    assert decode_event(envelope) == event


def test_event_registry_covers_every_bus_bridge_subscription() -> None:
    """The 20 types both GUIs subscribe to must all be decodable, or a
    daemon-mode window silently stops receiving one of them."""
    from trcc.core import events as events_module

    subscribed = {
        "DeviceDiscovered", "DeviceConnected", "DeviceDisconnected", "FrameSent",
        "OrientationChanged", "BrightnessChanged", "ThemeLoaded",
        "LedColorsChanged", "SensorsUpdated", "ErrorOccurred", "MaskApplied",
        "MaskPositionChanged", "MaskVisibilityChanged", "VideoStarted",
        "VideoStopped", "ScreencastStarted", "ScreencastStopped",
        "SystemSuspending", "SystemResumed", "DataInstalled",
    }
    assert subscribed <= set(EVENT_TYPES), subscribed - set(EVENT_TYPES)
    # ...and the registry is the module, not a list that can drift from it.
    declared = {
        n for n, c in vars(events_module).items()
        if inspect.isclass(c) and issubclass(c, Event) and c is not Event
    }
    assert declared <= set(EVENT_TYPES), declared - set(EVENT_TYPES)


def test_frame_sent_keeps_its_colours_as_tuples() -> None:
    """``display_colors`` carries ``(r, g, b)`` triples.  Annotated bare
    ``list`` they came back as lists — equal-looking, but the coercion had
    nothing to rebuild from and the round-trip was not an identity."""
    event = FrameSent(key="0402:3922", bytes_sent=12,
                      display_colors=[(255, 0, 0), (0, 128, 255)])

    rebuilt = decode_event(encode_event(event))

    assert isinstance(rebuilt, FrameSent)
    assert rebuilt.display_colors == [(255, 0, 0), (0, 128, 255)]
    assert all(isinstance(c, tuple) for c in rebuilt.display_colors)
    assert rebuilt == event


def test_a_live_surface_is_dropped_rather_than_crashing_the_stream() -> None:
    """``FrameSent.surface`` is a renderer surface — unserializable by design.
    It must become None, not raise: one un-encodable frame event cannot be
    allowed to take down the subscription."""
    event = FrameSent(key="0402:3922", bytes_sent=12, surface=object())

    envelope = encode_event(event)
    json.dumps(envelope)

    assert envelope["fields"]["surface"] is None
    assert decode_event(envelope).surface is None


def test_sensors_updated_carries_its_typed_snapshot() -> None:
    """The one event with a nested dataclass the UIs read attributes off."""
    metrics = HardwareMetrics(cpu_temp=55.5, readings={"cpu:temp": 55.5})
    event = SensorsUpdated(reading_count=1, readings={"cpu:temp": 55.5},
                           temp_unit="F", metrics=metrics)

    rebuilt = decode_event(encode_event(event))

    assert isinstance(rebuilt, SensorsUpdated)
    assert rebuilt.metrics.cpu_temp == 55.5
    assert rebuilt.metrics.readings == {"cpu:temp": 55.5}
    assert rebuilt.temp_unit == "F"


def test_an_event_with_no_fields_round_trips() -> None:
    """Suspend/resume carry nothing but their type — and they are two of the
    four unkeyed events a key filter must never drop."""
    assert decode_event(encode_event(SystemResumed())) == SystemResumed()


def test_unknown_event_raises_instead_of_falling_back() -> None:
    """Unlike ``decode_result``, which degrades to the base ``Result``.
    ``EventBus.publish`` dispatches on exact ``type()``, so a base ``Event``
    stand-in would reach zero subscribers — a silent loss."""
    import pytest as _pytest

    with _pytest.raises(ValueError, match="Unknown event"):
        decode_event({"event": "NotAnEvent", "fields": {}})


def test_missing_event_key_raises() -> None:
    import pytest as _pytest

    with _pytest.raises(ValueError, match="missing 'event'"):
        decode_event({"fields": {}})
