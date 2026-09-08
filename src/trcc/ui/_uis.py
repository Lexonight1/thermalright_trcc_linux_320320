"""The concrete UI faces — deliberately LIGHT.

Importing this module is what populates :data:`~trcc.ui._base.UIS`, the same
way importing ``adapters.device`` populates ``DEVICES``.  That only stays
affordable because **every heavy import in this file lives inside a method
body**: measured 2026-09-08, ``import trcc.daemon`` costs 153 ms,
``trcc.ipc`` 198 ms and ``trcc.ui.gui`` 247 ms, so hoisting any of them to
module scope would put that on the critical path of every ``trcc`` invocation.
As written, the marginal cost of the bus in the context that actually runs it —
a CLI process that has already imported ``ui.cli.main`` — is **0.13 ms**, and
it pulls exactly one new module.

Two rules follow, and ``tests/test_ui_bus.py`` gates both:

* heavy imports stay in method bodies;
* these classes do NOT live under ``ui/gui/`` or ``ui/qtgui/``, because
  importing *any* submodule of those packages runs their ``__init__`` --
  ``import trcc.ui.gui.assets`` costs 249 ms and loads 17 PySide6 modules.

The CLI is absent on purpose.  It is the **router**, not a leaf face: it
composes lazily per subcommand (``_ctx.get_app()``), so putting it through
``compose() -> run(app)`` would build an App it discards — and under
``TRCC_DAEMON=1`` would spawn a daemon that a ``trcc --help`` never needed.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from ._base import UserInterface

if TYPE_CHECKING:
    from ..app import App
    from ..core.ports import Platform, Renderer

log = logging.getLogger(__name__)


class ApiUI(UserInterface, name="api"):
    """The REST API — a headless server face.

    ``needs_session`` is **False**, which preserves today's behaviour exactly:
    the API brings up no coldplug and no live loops (measured — it dispatches
    neither ``start_session`` nor ``discover_and_connect`` anywhere).
    ``App.start_session``'s own docstring calls that out as the #148
    divergence, and flipping it here would change what the API does to USB on
    startup.  That is a behavioural fix and belongs in its own increment where
    it can be verified against a real fleet, not folded into a structural one.
    """

    needs_session = False

    def __init__(self, *, host: str = "127.0.0.1", port: int = 8080) -> None:
        log.info("ApiUI.__init__: host=%s port=%d", host, port)
        self.host = host
        self.port = port

    def compose(self, platform: Platform | None) -> App:
        """Headless composition: the API renders preview frames, has no widgets."""
        log.info("ApiUI.compose: headless QtRenderer")
        from .._boot import trcc
        from ..adapters.render.qt import QtRenderer
        return trcc(platform=platform, renderer=QtRenderer())

    def run(self, app: App) -> int:
        """Serve until the process is stopped."""
        log.info("ApiUI.run: serving on %s:%d", self.host, self.port)
        import uvicorn

        from .api.main import build_app
        uvicorn.run(build_app(trcc=app), host=self.host, port=self.port,
                    log_level="info")
        return 0


class DaemonUI(UserInterface, name="daemon"):
    """The background process that owns USB and serves every other face.

    A UI like the others -- "daemon should be a command that any ui can
    utilize" -- but with two things that are genuinely its own, and both are
    overrides rather than shared defaults for reasons that are load-bearing.
    """

    def __init__(self, *, renderer: Renderer | None = None) -> None:
        log.info("DaemonUI.__init__: renderer=%s", renderer is not None)
        self._renderer = renderer

    def preflight(self) -> int | None:
        """Refuse to start if another daemon already owns the socket.

        Exit code **1**, not 0: unlike the GUI -- where a peer means the
        running window was raised and this launch succeeded at what the user
        wanted -- a second daemon simply failed to start.

        This must run before :meth:`compose`.  Placed any later, the process
        would compose an App and coldplug in :meth:`bring_up`, **opening USB**,
        before discovering another daemon already owns the bus.
        """
        from .. import ipc
        if ipc.daemon_running():
            log.warning("DaemonUI.preflight: another daemon already owns %s",
                        ipc.socket_path())
            return 1
        from ..daemon import mark_started
        mark_started()
        return None

    def compose(self, platform: Platform | None) -> App:
        """Build a LOCAL App, never a proxy.

        The daemon owns USB directly and must never proxy to itself.  If
        ``TRCC_DAEMON`` leaked into this process's environment -- set in a
        shell profile, or inherited from the client that spawned us -- the
        inherited default would reach for a daemon socket instead of opening
        USB, and the startup path through it would re-spawn: a fork bomb
        (#162).  Strip the flag first, then build local.
        """
        import os

        from .._boot import _ENV_FLAG, _build_local_app
        log.info("DaemonUI.compose: stripping %s and building local",
                 _ENV_FLAG)
        os.environ.pop(_ENV_FLAG, None)
        return _build_local_app(platform=platform, renderer=self._renderer)

    def run(self, app: App) -> int:
        """Bind the socket and serve Commands until shutdown.

        ``App.close()`` is NOT called here: :meth:`UserInterface.start` owns
        it.  Closing in both places ran the whole detach-and-blank sequence
        twice -- the same double-teardown the GUI window had removed once
        already.
        """
        log.info("DaemonUI.run: binding the IPC server")
        from .. import ipc
        from ..daemon import _install_signal_handlers
        server = ipc.IPCServer(app)
        server.start()
        _install_signal_handlers(server)
        try:
            server.serve_forever()
        finally:
            server.shutdown()
        log.info("DaemonUI.run: served to completion")
        return 0
