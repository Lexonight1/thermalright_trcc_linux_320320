"""The sensor dashboard on the bus — ``GetSensorDashboard`` / ``SetSensorDashboard``.

Until these existed the layout at ``<config_dir>/system_config.json`` was
readable by exactly one UI: the legacy GUI imported the persistence adapter
directly, so cli / api / qtgui could not see the file at all.

What is pinned here is the part a review cannot see by reading the two
classes: that the Query really is a read (it must not create the file), that
the Result is a COPY (a widget must not be able to rebind a row by assignment
and skip the bus), and that both survive the daemon socket — because in-process
they would pass by sharing objects, which is exactly the bug.
"""
from __future__ import annotations

from trcc.app import App
from trcc.core.commands import GetSensorDashboard, SetSensorDashboard
from trcc.core.models import PanelConfig, SensorBinding
from trcc.ipc import (
    decode_command,
    decode_result,
    encode_command,
    encode_result,
)


def test_get_returns_the_six_default_panels(fake_platform) -> None:
    result = App(fake_platform).dispatch(GetSensorDashboard())
    assert result.ok
    assert [p.name for p in result.panels] == [
        "CPU", "GPU", "Memory", "HDD", "Network", "Fan",
    ]
    assert all(len(p.sensors) == 4 for p in result.panels)


def test_get_does_not_write_the_file(fake_platform) -> None:
    """A Query answers and changes nothing — including on disk.

    The GUI used to ``load(); auto_map(); save()`` at panel construction,
    which froze the auto-map at whatever the very first run happened to see:
    a pump idle at that moment stayed mis-bound forever.  The read now
    re-derives every time and only :class:`SetSensorDashboard` writes.
    """
    app = App(fake_platform)
    app.dispatch(GetSensorDashboard())
    assert not app.sysinfo.path.exists(), (
        f"GetSensorDashboard wrote {app.sysinfo.path} — it is a Query"
    )


def test_result_panels_are_copies_not_app_state(fake_platform) -> None:
    """Writing through the Result must change nothing.

    If the Result handed out ``app.sysinfo.panels`` itself, a widget could
    rebind a row by assignment and never dispatch — the exact bypass this
    pair of Commands exists to remove.  It would also work ONLY in-process:
    over the socket the caller gets objects rebuilt from JSON.
    """
    app = App(fake_platform)
    result = app.dispatch(GetSensorDashboard())
    before = app.sysinfo.panels[0].sensors[0].sensor_id

    result.panels[0].name = "hijacked"
    result.panels[0].sensors[0].sensor_id = "hijacked"

    assert app.sysinfo.panels[0].name == "CPU"
    assert app.sysinfo.panels[0].sensors[0].sensor_id == before


def test_set_persists_and_survives_a_restart(fake_platform) -> None:
    app = App(fake_platform)
    panels = app.dispatch(GetSensorDashboard()).panels
    panels[0].name = "My Cooler"
    panels[0].sensors[0] = SensorBinding("TEMP", "cpu:temp", "°C")

    written = app.dispatch(SetSensorDashboard(panels=tuple(panels)))
    assert written.ok
    assert app.sysinfo.path.exists()

    reread = App(fake_platform).dispatch(GetSensorDashboard())
    assert reread.panels[0].name == "My Cooler"
    assert reread.panels[0].sensors[0].sensor_id == "cpu:temp"


def test_set_stores_a_copy_of_the_commands_panels(fake_platform) -> None:
    """The saved layout must not alias the Command's own tuple."""
    app = App(fake_platform)
    panels = app.dispatch(GetSensorDashboard()).panels
    app.dispatch(SetSensorDashboard(panels=tuple(panels)))

    panels[0].name = "changed after the dispatch"
    assert app.sysinfo.panels[0].name == "CPU"


def test_set_refuses_an_empty_layout(fake_platform) -> None:
    """Saving nothing would make the next load fall back to defaults.

    A wipe dressed up as a write — and the UI path that could send it is a
    delete-the-last-panel click.
    """
    app = App(fake_platform)
    app.dispatch(GetSensorDashboard())
    result = app.dispatch(SetSensorDashboard(panels=()))

    assert not result.ok
    assert result.message
    assert not app.sysinfo.path.exists()


def test_add_delete_and_rename_all_go_through_the_one_verb(fake_platform) -> None:
    """One bulk verb covers rebind / add / delete / rename (SetOverlayConfig precedent)."""
    app = App(fake_platform)
    panels = app.dispatch(GetSensorDashboard()).panels

    panels.append(PanelConfig(0, "Custom", [
        SensorBinding(f"Sensor {i + 1}", "", "") for i in range(4)
    ]))
    del panels[1]
    panels[0].name = "Renamed"

    app.dispatch(SetSensorDashboard(panels=tuple(panels)))
    names = [p.name for p in App(fake_platform)
             .dispatch(GetSensorDashboard()).panels]
    assert names == ["Renamed", "Memory", "HDD", "Network", "Fan", "Custom"]


def test_unbound_rows_survive_a_save(fake_platform) -> None:
    """``sensor_id=""`` is how the user says "nothing here"."""
    app = App(fake_platform)
    panels = app.dispatch(GetSensorDashboard()).panels
    panels[0].sensors[0] = SensorBinding("TEMP", "", "°C")
    app.dispatch(SetSensorDashboard(panels=tuple(panels)))

    reread = App(fake_platform).dispatch(GetSensorDashboard())
    # Re-read auto-maps it again -- which is the self-healing behaviour, and
    # the reason the Query reports how many rows it filled.
    assert reread.auto_mapped >= 1


def test_the_command_survives_the_daemon_socket(fake_platform) -> None:
    """Two levels of nesting: list[PanelConfig] each holding list[SensorBinding]."""
    app = App(fake_platform)
    command = SetSensorDashboard(
        panels=tuple(app.dispatch(GetSensorDashboard()).panels),
    )
    restored = decode_command(encode_command(command))

    assert isinstance(restored, SetSensorDashboard)
    assert isinstance(restored.panels[0], PanelConfig)
    assert isinstance(restored.panels[0].sensors[0], SensorBinding)
    assert restored.panels == command.panels


def test_the_result_survives_the_daemon_socket(fake_platform) -> None:
    result = App(fake_platform).dispatch(GetSensorDashboard())
    restored = decode_result(encode_result(result))

    assert restored.panels == result.panels
    assert restored.auto_mapped == result.auto_mapped
