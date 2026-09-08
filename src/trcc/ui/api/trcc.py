"""``/trcc/`` router — daemon lifecycle control.

The existing ``/system`` and ``/devices`` namespaces are device- and
metrics-shaped; daemon-control is conceptually different (lifecycle of
the singleton process itself), so it lives under its own prefix —
legacy parity with ``legacy/ui/api/trcc.py``.

Endpoints:

  POST /trcc/ensure  — start the daemon if it is not already running
                       (idempotent; "is it up? no -- create it")
  POST /trcc/kill    — stop the running daemon (the API process exits
                       cleanly)
  GET  /trcc/status  — pid / uptime / device counts.  Reads directly
                       from the in-process state (the API server is
                       almost always running INSIDE the daemon); no
                       IPC hop needed for next/'s layout.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Request

from ...core.commands import (
    DaemonStatus,
    EnsureDaemon,
    ListDevices,
    StopDaemon,
)
from ...core.models import Kind
from .schemas import DaemonKillResponse, DaemonStatusResponse

log = logging.getLogger(__name__)

router = APIRouter(prefix="/trcc", tags=["trcc"])


@router.post("/kill", response_model=DaemonKillResponse)
def kill(request: Request) -> DaemonKillResponse:
    """Stop the running TRCC daemon.

    Dispatches ``StopDaemon`` -- the daemon's lifecycle is on the bus like
    every other capability, rather than this route importing
    ``daemon.kill_daemon`` itself.  Returns ``ok=true`` once the daemon has
    shut down within the timeout.  The API process itself exits as part of
    the shutdown.
    """
    log.info("api POST /trcc/kill")
    result = request.app.state.trcc.dispatch(StopDaemon())
    return DaemonKillResponse(ok=result.ok, message=result.message)


@router.post("/ensure", response_model=DaemonKillResponse)
def ensure(request: Request) -> DaemonKillResponse:
    """Start the TRCC daemon if it is not already running.

    *Is the daemon up?  No -- create it.  Yes -- nothing to do.*  Idempotent,
    so a caller can issue it unconditionally at start-up rather than probing
    first and racing between the probe and the spawn.

    Why it matters beyond convenience: the daemon is the one process that owns
    USB, polls the sensors and drives the render loop.  Every client that
    talks to it instead of building its own ``App`` is one fewer sensor poll
    and one fewer render pipeline for the same machine. (unified-UI contract)
    """
    log.info("api POST /trcc/ensure")
    result = request.app.state.trcc.dispatch(EnsureDaemon())
    return DaemonKillResponse(ok=result.ok, message=result.message)


@router.get("/status", response_model=DaemonStatusResponse)
def status(request: Request) -> DaemonStatusResponse:
    """Snapshot of the running daemon: pid, uptime, device counts.

    Used by ops scripts and remote phone clients before issuing
    commands.  When the API server is also the daemon (the common
    layout: ``trcc api`` boots the API inside the daemon), every
    field is populated from in-process state.

    Returns ``running=false`` with zeros elsewhere when no daemon is up.
    When one IS up but this process is not it, ``pid`` and ``uptime_seconds``
    come from the daemon itself rather than from this process — dispatching
    ``DaemonStatus`` over the socket runs it there.
    """
    log.info("api GET /trcc/status")
    trcc = request.app.state.trcc
    # Every field comes off the bus.  ``pid`` and ``uptime`` used to be
    # ``os.getpid()`` and the private ``daemon._started_at`` — this process's
    # facts, reported as the daemon's.  Correct only while the API ran INSIDE
    # the daemon; as a client it named the wrong process to signal and a
    # permanent uptime of 0.  The Command executes wherever the daemon is, so
    # over the socket it answers with the daemon's own.
    status = trcc.dispatch(DaemonStatus())
    if not status.running:
        return DaemonStatusResponse(
            ok=True, running=False,
            message="daemon not running",
        )
    # ``ListDevices`` rather than ``trcc.devices``: the latter is absent on the
    # ``AppProxy`` a daemon-mode client holds, which is exactly what this route
    # reports on.  ``kind`` carries the LCD/LED split (``Kind.LED``).
    devices = trcc.dispatch(ListDevices()).devices
    led_count = sum(1 for d in devices if d.kind == Kind.LED.value)
    lcd_count = len(devices) - led_count
    uptime = status.uptime_seconds
    return DaemonStatusResponse(
        ok=True, running=True,
        pid=status.pid,
        uptime_seconds=uptime,
        lcd_count=lcd_count,
        led_count=led_count,
        message=(f"daemon up {uptime}s, "
                 f"{lcd_count} LCD + {led_count} LED device(s)"),
    )
