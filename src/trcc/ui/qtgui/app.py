"""GUI entry — QApplication + MainWindow shell.

MainWindow is a horizontal split: an ``ActivitySidebar`` on the left and
a ``QStackedWidget`` on the right that swaps the active panel.  Every
panel subclasses :class:`BasePanel` so they share the same ``app`` /
``bus`` plumbing.

Adding a panel: register the widget on the stacked container with the
same key the sidebar emits, and add an entry to ``sidebar._ENTRIES``.
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QGuiApplication, QIcon
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QMainWindow,
    QStackedWidget,
    QStatusBar,
    QWidget,
)

from ...app import App
from ...core.commands import (
    ControlCenterSnapshot,
    GetFirstRunStatus,
    GetPlatformInfo,
    ListDevices,
    RefreshAutostart,
    RenderAndSend,
    RestoreDeviceState,
    TickDisplay,
)

if TYPE_CHECKING:
    from ...core.ports import Platform
from ...core.events import (
    DeviceConnected,
    DeviceDisconnected,
    ErrorOccurred,
    FrameSent,
    ThemeLoaded,
    VideoStarted,
    VideoStopped,
)
from ...core.models import Wire
from ..bus_bridge import BusBridge
from ..qt_periodic import PeriodicUpdater
from ..qt_tray import TrayController
from .panels import (
    AboutPanel,
    ActivitySidebar,
    CloudThemeBrowser,
    ConfigurationPanel,
    DevicePanel,
    DisplayPanel,
    LedPanel,
    LocalThemeBrowser,
    MaskBrowser,
    OverlayEditorPanel,
    PreviewPanel,
    ScreencastPanel,
    StatusPanel,
    SystemPanel,
)

log = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    """Top-level window: sidebar + stacked content + status bar."""

    def __init__(self, app: App) -> None:
        super().__init__()
        self._app = app
        self._bus = BusBridge(app.events)

        # #201 repair — the same Command cli, api and gui all dispatch, and
        # the one capability qtgui could not reach.  An entry keeps whatever
        # launch command it was written with forever, so a moved install stops
        # autostarting while the panel still reads "enabled" (``is_enabled()``
        # is ``path.is_file()``, which a stale entry satisfies).  Dispatched
        # unconditionally because the port's contract is that refresh NEVER
        # installs an entry that is not there — gui's extra first-launch
        # auto-enable is gui's own product decision and stays there.
        autostart = app.dispatch(RefreshAutostart())
        log.info("MainWindow.__init__: autostart refresh — enabled=%s target=%s",
                 autostart.enabled, autostart.target)

        self.setWindowTitle("TRCC — Thermalright LCD/LED Cooler Control (next)")
        self.resize(960, 640)

        # ── Layout: sidebar | stacked content ──
        sidebar = ActivitySidebar(app, self._bus, self)
        content = QStackedWidget(self)
        content.setObjectName("trcc-content")

        # Register panels.  Key matches the sidebar entry's key.
        self._panels: dict[str, QWidget] = {
            "devices": DevicePanel(app, self._bus, self),
            "display": DisplayPanel(app, self._bus, self),
            "preview": PreviewPanel(app, self._bus, self),
            "themes":  LocalThemeBrowser(app, self._bus, self),
            "cloud":   CloudThemeBrowser(app, self._bus, self),
            "masks":   MaskBrowser(app, self._bus, self),
            "overlay": OverlayEditorPanel(app, self._bus, self),
            "screencast": ScreencastPanel(app, self._bus, self),
            "config":  ConfigurationPanel(app, self._bus, self),
            "led":     LedPanel(app, self._bus, self),
            "status":  StatusPanel(app, self._bus, self),
            "system":  SystemPanel(app, self._bus, self),
            "about":   AboutPanel(app, self._bus, self),
        }
        for widget in self._panels.values():
            content.addWidget(widget)
        # First-run users land on System (where the doctor lives) so the
        # welcome screen guides them; everyone else starts on Devices.
        initial = ("system" if app.dispatch(GetFirstRunStatus()).is_first_run
                   else "devices")
        content.setCurrentWidget(self._panels[initial])
        sidebar.select(initial)
        sidebar.selected.connect(
            lambda key: content.setCurrentWidget(
                self._panels.get(key, self._panels["devices"]),
            ),
        )

        container = QWidget(self)
        row = QHBoxLayout(container)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        row.addWidget(sidebar)
        row.addWidget(content, 1)
        self.setCentralWidget(container)

        status = QStatusBar(self)
        self.setStatusBar(status)
        self._status = status

        # EventBus → status bar (thread-safe via Qt.QueuedConnection)
        qconn = Qt.ConnectionType.QueuedConnection
        self._bus.device_connected.connect(self._on_connected, type=qconn)
        self._bus.device_disconnected.connect(self._on_disconnected, type=qconn)
        self._bus.frame_sent.connect(self._on_frame_sent, type=qconn)
        self._bus.theme_loaded.connect(self._on_theme_loaded, type=qconn)
        self._bus.error_occurred.connect(self._on_error, type=qconn)
        self._bus.video_started.connect(self._on_video_started, type=qconn)
        self._bus.video_stopped.connect(self._on_video_stopped, type=qconn)

        # Display-start restore — METHOD_UI.md's entry contract, which qtgui
        # did not honour at all: `RestoreLastTheme` was reachable ONLY from the
        # display panel's "Restore last" button, so connecting a device and
        # opening qtgui showed nothing until you clicked it.  cli and api have
        # dispatched `RestoreDeviceState` at their display-start since #150.
        #
        # It sits HERE, after the subscriptions above, on purpose: the restore
        # loads a theme, which publishes `ThemeLoaded`, which is what starts
        # the render ticker.  Dispatched any earlier in __init__ the event
        # would fire into an unconnected bus and nothing would ever animate.
        self._restore_display_state()

        # Metrics ticker — dispatches RenderAndSend to every device with an
        # active theme, at AppSettings.refresh_interval_s.  Started lazily when
        # a theme gets loaded; stops when no active themes remain.
        self._ticker = QTimer(self)
        self._ticker.setSingleShot(False)
        self._ticker.timeout.connect(self._on_tick)

        # Per-device VIDEO tickers, keyed by device.  A video needs its own
        # cadence (~33 ms at 30 fps), which the metrics ticker above cannot
        # provide — it runs at refresh_interval_s, 2 s by default, so driving
        # video from it would advance one frame every two seconds.  Matches the
        # gui skin, which likewise keeps a separate per-device animation timer.
        self._video: dict[str, PeriodicUpdater] = {}

        self._show_platform_info()

        # Shared tray: a window-close hides to the tray (keeps the LCD running)
        # exactly like the gui skin — via the shared TrayController, not a
        # qtgui-local reinvention.  Exit (menu) or a force-quit ends the process.
        icon_path = (Path(__file__).resolve().parents[2]
                     / "assets" / "icons" / "trcc.png")
        icon = QIcon(str(icon_path)) if icon_path.exists() else QIcon()
        self._tray = TrayController(
            self,
            # The same Query ``_show_platform_info`` uses — asking the bus
            # instead of ``app.platform``, which an AppProxy does not have.
            minimize_on_close=app.dispatch(GetPlatformInfo()).minimize_on_close,
            icon=icon,
        )
        self._tray.install()

    def closeEvent(self, event: Any) -> None:
        if self._tray.intercept_close(event):
            return
        # Genuine quit: stop the metrics ticker AND every per-device video
        # ticker; the daemon-thread loops die with the process.
        self._ticker.stop()
        for updater in self._video.values():
            updater.stop()
        event.accept()
        # End the event loop so ``run``'s ``finally: app.close()`` actually
        # runs.  ``quitOnLastWindowClosed`` is False (hide-to-tray), so
        # accepting the close does NOT return from ``qapp.exec()`` — without
        # this the process lived on with the metrics thread still polling, the
        # panel still lit, and /dev/sgN still held.  Same last two lines as
        # gui's closeEvent; App teardown stays in ``run``'s finally so it
        # happens exactly once.
        log.info("MainWindow.closeEvent: real quit — quitting the event loop")
        if (qapp := QApplication.instance()) is not None:
            qapp.quit()

    def _show_platform_info(self) -> None:
        # One Query carries all three: PlatformInfoResult already flattens
        # distro/install/config_dir, so this needs no GetPaths beside it.
        info = self._app.dispatch(GetPlatformInfo())
        msg = (f"{info.distro_name}  |  install: {info.install_method}"
               f"  |  config: {info.config_dir}")
        if self._app.dispatch(GetFirstRunStatus()).is_first_run:
            msg = (
                "Welcome to TRCC.  Open System → run Doctor to check your "
                "setup, then plug in a device and open Devices to scan."
            )
        self._status.showMessage(msg)

    # ── Event handlers ────────────────────────────────────────────────

    def _restore_display_state(self, key: str | None = None) -> None:
        """Give every attached LCD a renderable display state.  Idempotent.

        Enumerates through ``ListDevices`` rather than ``app.devices``: the
        latter is an ``AttributeError`` under ``TRCC_DAEMON=1``, where a UI
        holds an ``AppProxy`` that exposes ``dispatch`` and nothing else, and
        that Query exists precisely because nothing else could answer "which
        devices are there".

        ``key=None`` covers the coldplug fleet — devices attached by
        ``discover_and_connect`` BEFORE this window existed, which never emit
        ``DeviceConnected`` anywhere this window can hear it.  A key restores
        the one device that just arrived.  ``RestoreDeviceState`` no-ops when a
        theme is already active, so the two paths may overlap freely.
        """
        fleet = self._app.dispatch(ListDevices()).devices
        # Entry log with the resolved count — THE RULE.  Without it this method
        # is SILENT on an empty fleet, which is precisely the case a reader
        # needs to distinguish from "ran and restored nothing".
        log.info("_restore_display_state: key=%s, %d device(s) attached",
                 key or "<all>", len(fleet))
        for entry in fleet:
            if key is not None and entry.key != key:
                continue
            if not entry.connected or entry.wire == Wire.LED.value:
                log.debug("_restore_display_state: skip %s (wire=%s connected=%s)",
                          entry.key, entry.wire, entry.connected)
                continue
            result = self._app.dispatch(RestoreDeviceState(key=entry.key))
            log.info("_restore_display_state: %s → ok=%s %s",
                     entry.key, result.ok, result.message)

    def _on_connected(self, event: DeviceConnected) -> None:
        log.info("_on_connected: %s", event.key)
        w, h = event.resolution
        self._status.showMessage(f"Connected: {event.key} ({w}×{h})", 5000)
        # A hotplugged device needs the same display-start restore the
        # coldplug fleet gets in __init__ — otherwise it attaches and sits dark.
        self._restore_display_state(event.key)

    def _on_disconnected(self, event: DeviceDisconnected) -> None:
        log.info("_on_disconnected")
        self._status.showMessage(f"Disconnected: {event.key}", 5000)

    def _on_frame_sent(self, event: FrameSent) -> None:
        log.info("_on_frame_sent")
        self._status.showMessage(f"Frame sent: {event.bytes_sent} bytes", 2000)

    def _on_error(self, event: ErrorOccurred) -> None:
        log.info("_on_error")
        self._status.showMessage(f"Error [{event.kind}]: {event.message}", 8000)

    def _on_theme_loaded(self, event: ThemeLoaded) -> None:
        """A theme got loaded on some device — make sure the ticker is running."""
        log.info("_on_theme_loaded")
        del event
        self._ensure_ticker_running()

    def _ensure_ticker_running(self) -> None:
        """Start the QTimer if there are active themes; stop it otherwise."""
        if not any(d.has_active_theme
                   for d in self._app.dispatch(ListDevices()).devices):
            if self._ticker.isActive():
                self._ticker.stop()
            return
        snap = self._app.dispatch(ControlCenterSnapshot())
        interval_ms = max(100, int(snap.refresh_interval_s * 1000))
        if not self._ticker.isActive() or self._ticker.interval() != interval_ms:
            self._ticker.start(interval_ms)

    def _on_video_started(self, event: VideoStarted) -> None:
        """A video began on a device — give it its own frame-rate ticker.

        Without this qtgui rendered a video theme repeatedly but never advanced
        its cursor, so the panel showed frame 0 forever.  ``interval_ms`` comes
        off the event (derived from the playback's fps server-side), so this
        skin never has to query MediaService.
        """
        log.info("_on_video_started: key=%s interval_ms=%d frames=%d",
                 event.key, event.interval_ms, event.frame_count)
        updater = self._video.get(event.key)
        if updater is None:
            updater = PeriodicUpdater(self)
            self._video[event.key] = updater
        # PeriodicUpdater drops the previous connection on restart, so a
        # re-started video re-paces instead of firing twice per tick.
        updater.start(event.interval_ms, partial(self._on_video_tick, event.key))

    def _on_video_stopped(self, event: VideoStopped) -> None:
        """Video ended on a device — stop its ticker; metrics keep it alive."""
        log.info("_on_video_stopped: key=%s", event.key)
        updater = self._video.pop(event.key, None)
        if updater is not None:
            updater.stop()

    def _on_video_tick(self, key: str) -> None:
        """One video frame for *key* — advance the cursor, render, send.

        Per-tick (~30 Hz), so DEBUG — never INFO, or one video buries every
        user-action line in the log.
        """
        log.debug("_on_video_tick: key=%s", key)
        try:
            self._app.dispatch(TickDisplay(key=key))
        except Exception as e:
            log.exception("Video tick failed for %s: %s", key, e)

    def _on_tick(self) -> None:
        """Fire one render+send for every device with an active theme.

        Skips any device currently driven by its own video ticker — that
        ticker already renders at frame rate, and rendering the same device
        from both would double its wire traffic.  Same rule the gui skin
        states as "animation timer owns the wire".
        """
        rendering = [d.key for d in self._app.dispatch(ListDevices()).devices
                     if d.has_active_theme]
        if not rendering:
            self._ticker.stop()
            return
        for key in rendering:
            updater = self._video.get(key)
            if updater is not None and updater.is_active:
                log.debug("_on_tick: %s driven by its video ticker — skip", key)
                continue
            try:
                self._app.dispatch(RenderAndSend(key=key))
            except Exception as e:
                log.exception("Tick failed for %s: %s", key, e)


def run(
    platform: Platform | None = None,
    on_ready: Callable[[MainWindow], None] | None = None,
    *,
    force_exit: bool = True,
    start_hidden: bool = False,
) -> int:
    """Start the qtgui skin from an injected ``Platform``.  Returns the exit code.

    A thin alias over the UI bus (``ui/_base.py``); the launch sequence is
    ``UserInterface.start``, shared with every other face.  ``QtGuiUI`` keeps
    what is qtgui's own: the inline coldplug (gui runs it on a splash worker;
    qtgui runs it before the window builds so pickers and browsers populate at
    construction) and its window.

    ``force_exit`` stays here rather than on the face: ``os._exit`` must run
    after the bus's ``finally`` has closed the App, so it cannot live inside
    ``QtGuiUI.run``.
    """
    log.info("run: delegating to the UI bus (start_hidden=%s)", start_hidden)
    from .._uis import QtGuiUI
    exit_code = QtGuiUI(start_hidden=start_hidden, on_ready=on_ready).start(platform)
    if force_exit:
        import os as _os
        _os._exit(exit_code)
    return exit_code


def launch(
    platform: Platform | None = None,
    on_ready: Callable[[MainWindow], None] | None = None,
    *,
    force_exit: bool = True,
    start_hidden: bool = False,
) -> int:
    """Back-compat entry — ``trcc qtgui`` and the direct entry points call this.

    Identical to :func:`run`; kept as the historical name until the CLI router
    dispatches ``run`` directly.
    """
    return run(platform, on_ready, force_exit=force_exit,
               start_hidden=start_hidden)


# Silence unused-import warnings for QGuiApplication (kept for reference).
_ = QGuiApplication
