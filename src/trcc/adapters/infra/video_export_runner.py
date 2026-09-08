"""VideoExportRunner implementations — the execution behind a ``.zt`` encode.

``ThreadVideoExportRunner`` drains a queue of submitted clips on one daemon
thread (production).  ``SyncVideoExportRunner`` encodes inline so tests stay
deterministic — no threads, no sleeps, no ffmpeg timing.

Both are injected at the composition root; the Command that submits a clip
never names a thread.  Mirrors ``data_install_runner.py`` and
``send_scheduler.py``, the other background workers in this package.
"""
from __future__ import annotations

import logging
import queue
import threading

from ...core.events import EventBus, VideoExportFinished, VideoExportProgress
from ...core.models import VideoExportRequest
from ...core.ports import VideoExportRunner

log = logging.getLogger(__name__)

# Wakes the worker out of a blocking ``get()`` at shutdown.
_STOP = object()


class _ProgressPublisher:
    """Turns the exporter's callback into bus events for one token.

    A named object rather than a closure so the token it carries is
    inspectable when a subscriber misbehaves, and so the exporter's
    ``(percent, message)`` contract stays the only thing it knows about.
    """

    __slots__ = ("_events", "_token")

    def __init__(self, events: EventBus, token: str) -> None:
        log.debug("_ProgressPublisher.__init__: token=%s", token)
        self._events = events
        self._token = token

    def __call__(self, percent: int, message: str) -> None:
        log.debug("progress: token=%s %d%% %s", self._token, percent, message)
        self._events.publish(VideoExportProgress(
            token=self._token, percent=percent, message=message,
        ))

    def __repr__(self) -> str:
        return f"<progress publisher for {self._token}>"


def _export_and_publish(
    events: EventBus, token: str, request: VideoExportRequest,
) -> bool:
    """Encode one clip and announce the outcome.  Never raises.

    The worker thread outlives any single export, so an exception here
    would kill every queued clip behind it.  Failure is published as
    ``VideoExportFinished(ok=False)`` instead — which is the only way a
    caller can hear about it anyway, since it submitted and returned long
    before ffmpeg started.
    """
    log.info("_export_and_publish: token=%s source=%s %d-%dms target=%dx%d "
             "rotation=%d", token, request.source, request.start_ms,
             request.end_ms, request.target_w, request.target_h,
             request.rotation)
    # Imported here, not at module scope: the exporter warns about a missing
    # ffmpeg on construction, and a headless run that never exports anything
    # should not pay for that probe.
    from ...services.video_export import VideoExporter, VideoExportError
    try:
        path = VideoExporter().export_zt(
            request, _ProgressPublisher(events, token),
        )
    except VideoExportError as e:
        # Actionable by contract — the exporter words these for a user.
        log.warning("_export_and_publish: token=%s failed — %s", token, e)
        events.publish(VideoExportFinished(
            token=token, ok=False, message=str(e),
        ))
        return False
    except Exception as e:
        log.exception("_export_and_publish: token=%s raised unexpectedly",
                      token)
        events.publish(VideoExportFinished(
            token=token, ok=False,
            message=f"Video export failed unexpectedly: {e}",
        ))
        return False
    log.info("_export_and_publish: token=%s wrote %s", token, path)
    events.publish(VideoExportFinished(
        token=token, ok=True, path=str(path),
        message=f"Exported {request.source.name} to {path.name}",
    ))
    return True


class ThreadVideoExportRunner(VideoExportRunner):
    """One daemon thread draining submitted clips — production."""

    def __init__(
        self,
        events: EventBus,
        *,
        join_timeout: float = 2.0,
    ) -> None:
        log.info("ThreadVideoExportRunner.__init__: join_timeout=%.1fs",
                 join_timeout)
        self._events = events
        self._join_timeout = join_timeout
        self._queue: queue.Queue = queue.Queue()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    def submit(self, token: str, request: VideoExportRequest) -> None:
        log.info("submit: token=%s source=%s", token, request.source)
        if self._stop.is_set():
            log.warning("submit: token=%s after shutdown — ignored", token)
            return
        self._start()
        self._queue.put((token, request))

    def _start(self) -> None:
        """Spawn the worker on first use — most runs never export."""
        with self._lock:
            if self._thread is not None:
                return
            log.info("_start: spawning video-export worker")
            self._thread = threading.Thread(
                target=self._run, name="trcc-video-export", daemon=True,
            )
            self._thread.start()

    def _run(self) -> None:
        log.info("_run: video-export worker started")
        while not self._stop.is_set():
            item = self._queue.get()
            if item is _STOP or self._stop.is_set():
                break
            token, request = item
            _export_and_publish(self._events, token, request)
        log.info("_run: video-export worker stopped")

    def shutdown(self) -> None:
        log.info("shutdown: stopping video-export worker")
        self._stop.set()
        thread = self._thread
        if thread is None:
            log.debug("shutdown: worker was never started")
            return
        self._queue.put(_STOP)   # break a blocking get() so the join is prompt
        thread.join(timeout=self._join_timeout)
        if thread.is_alive():
            # Mid-encode: ``subprocess.run`` owns the thread until ffmpeg's
            # own timeout.  It is a daemon, so it cannot hold the process open.
            log.warning(
                "shutdown: video-export worker did not stop within %.1fs "
                "(likely mid-encode) — abandoning it as a daemon",
                self._join_timeout,
            )
        self._thread = None


class SyncVideoExportRunner(VideoExportRunner):
    """Encodes inline on the caller's thread — deterministic tests."""

    def __init__(self, events: EventBus) -> None:
        log.info("SyncVideoExportRunner.__init__")
        self._events = events

    def submit(self, token: str, request: VideoExportRequest) -> None:
        log.info("submit: token=%s source=%s (inline)", token, request.source)
        _export_and_publish(self._events, token, request)

    def shutdown(self) -> None:
        log.info("shutdown: nothing to stop (inline runner)")
