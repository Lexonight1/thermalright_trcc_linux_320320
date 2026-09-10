#!/usr/bin/env python3
"""Multi-process log rotation smoke — does the shared log survive N writers?

The daemon flip makes concurrent writers permanent: the daemon owns USB and
rendering, a CLI or GUI client dispatches into it, and both write
``~/.trcc/trcc.log``.  ``trcc report`` pastes that file, and for hardware we do
not own it IS the diagnosis — so what it loses, we never see.

A unit test cannot prove this.  The failure is between PROCESSES: two of them
rotate the chain at the same moment, one renames a file the other already
moved, and a writer left holding a renamed inode keeps appending to a file
nothing reads.  Threads share a handler and never reproduce it.

What this measures, against a SINGLE-WRITER CONTROL at the same total volume —
because a rotating log is *meant* to forget, and only a loss BELOW the control
is the concurrency defect.  Measured by THIS harness, at its own timing:

    writers            1       2       3       4
    kept    before  48.6%   48.6%   39.9%   33.1%
            after   48.6%   48.6%   48.5%   48.5%
    crashes before      0       1       3       3
            after       0       0       0       0
    latest  before  100.0%  14.4%   12.1%   14.2%
            after   100.0%  100.0%  100.0%  100.0%

The single-writer figure is not a defect: 12 MB of records into a 1 MB x 5
chain keeps 6 MB of them.  What matters is that four writers keep what one
does.  (An earlier note recorded a flat "30.7% record loss" with no control,
which conflated the two and put the cliff at two writers instead of three.)

The ``latest`` row moves for a second, separate reason — a joining process
truncating a live peer's per-run log — and isolating it needs the run-claim
alone reverted: that reads 97.8% / 93.2% / 85.8%.

Run:
    PYTHONPATH=src python3.12 dev/smoke_log_multiprocess.py

    # ...and again under the WINDOWS file policy, which any OS can execute:
    TRCC_SMOKE_CLOSE_BETWEEN_RECORDS=1 \
        PYTHONPATH=src python3.12 dev/smoke_log_multiprocess.py

Windows cannot rename a file a peer holds open (WinError 32), so its handler
closes after every write instead of holding the file.  That POLICY is the half
of the Windows fix a Linux box can exercise, and both runs read identically —
48.6 / 48.6 / 48.5 / 48.5 %% kept, zero crashes, ``latest`` at 100 %%.  What it
cannot prove is the rename itself; that needs Windows.

Exit code 0 when concurrent writers cost nothing and nothing crashed, 1
otherwise.
"""
from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from trcc.adapters.infra.logging import (
    LOCK_SUFFIX,
    configure_logging,
    log_chain,
    shared_handler_class,
)

#: ~12 MB of records against the shipped 1 MB x 5 chain, so the rotation set
#: genuinely cycles and a writer that over-advances it is visible.
TOTAL_RECORDS = 60_000
MAX_BYTES = 1_000_000
BACKUP_COUNT = 5
WRITER_COUNTS = (1, 2, 3, 4)

#: A writer keeping more than this much less than the single-writer control is
#: paying for concurrency.  The measured gap was 17.6 points; replicates of the
#: control sit within 0.1, so a point of slack is generous either way.
TOLERANCE_POINTS = 1.0

#: ``latest`` holds 10 MB x 1 = 20 MB, comfortably more than the ~12 MB written
#: here, so every record should survive.  Anything short of that is truncation
#: loss, not rotation.
LATEST_MIN_KEPT = 99.0

#: Writers JOIN a session already in progress.  That is the real shape — a
#: daemon is running when a client arrives — and it is what makes the per-run
#: defect visible: a joiner that truncates unconditionally destroys whatever
#: the live peer has written SO FAR.  Started simultaneously the same defect
#: reached only 98.2%, and the gate nearly passed on broken code.
JOIN_DELAY_S = 0.2

#: The two defects need DIFFERENT things from the timing, and tuning for one
#: alone silently disarms the other:
#:
#: * rotation needs writers writing AT THE SAME TIME, or no two processes ever
#:   rotate the chain together;
#: * the per-run log needs a writer to JOIN while a peer is still alive, or it
#:   is simply the next session and truncating is correct.
#:
#: Flat-out writers finish in ~0.3s, which is shorter than the join delay — so
#: staggering alone made them consecutive rather than concurrent, and the smoke
#: PASSED an unshared handler.  Pacing every writer stretches each one across
#: the whole window so the joins land mid-flight.
PACE_EVERY = 250
PACE_S = 0.02

#: Writer 0 also stays alive after writing, so even the last joiner meets a
#: live peer.  Without it, ``latest`` kept exactly 1/N and the smoke failed
#: CORRECT code — every later writer really did own a fresh run.
LINGER_MARGIN_S = 0.5

_RECORD = re.compile(r"SMOKE w=(\d+) seq=(\d+)")

log = logging.getLogger(__name__)


def _force_close_between_records() -> None:
    """Adopt the WINDOWS file policy on whatever OS is running this.

    Windows cannot rename a file a peer holds open (WinError 32), so its
    handler closes after every write.  That policy is the part of the Windows
    fix a Linux box CAN exercise: if closing between records broke concurrency
    — lost records, extra rotations, a stuck lock — it would show up here
    rather than on a reporter's machine.  What this canNOT prove is the rename
    itself; only Windows can.
    """
    shared_handler_class()._keep_open = False


def _write(log_file: Path, writer: int, count: int, writers: int) -> None:
    """One writer process: configure logging exactly as the app does.

    Writer 0 is the "daemon" — first in, and still running when every other
    writer joins, which is the only arrangement in which truncating a peer's
    run actually costs records.
    """
    if os.environ.get("TRCC_SMOKE_CLOSE_BETWEEN_RECORDS"):
        _force_close_between_records()
    time.sleep(writer * JOIN_DELAY_S)
    configure_logging(
        log_file, level=logging.DEBUG, max_bytes=MAX_BYTES,
        backup_count=BACKUP_COUNT, stderr_level=logging.CRITICAL,
    )
    writer_log = logging.getLogger(f"trcc.smoke.w{writer}")
    for seq in range(count):
        writer_log.debug("SMOKE w=%d seq=%d %s", writer, seq, "x" * 120)
        if seq % PACE_EVERY == 0:
            time.sleep(PACE_S)      # stretch every writer across the window
    if writer == 0:
        # Hold the session open until every client has joined and finished.
        time.sleep(writers * JOIN_DELAY_S + LINGER_MARGIN_S)
    logging.shutdown()


def _surviving(log_file: Path) -> set[tuple[int, int]]:
    """Every record still readable anywhere in the rotation set."""
    found: set[tuple[int, int]] = set()
    for segment in log_chain(log_file):
        text = segment.read_text(encoding="utf-8", errors="replace")
        found.update((int(w), int(s)) for w, s in _RECORD.findall(text))
    return found


def _latest_kept(log_file: Path) -> float:
    """Percentage of all records still in the per-run ``latest`` log.

    ``latest`` answers "what did THIS launch do", and it earns that by being
    truncated at startup.  With concurrent writers that has to mean the
    SESSION, not the process: truncating unconditionally let a joining client
    wipe a live peer's run mid-write.  Measured before the fix, three writers
    left {7499, 5345, 9000} of 9,000 each — a file blended from three runs with
    two of them partly destroyed.
    """
    latest = log_file.with_name(f"{log_file.stem}.latest{log_file.suffix}")
    found: set[tuple[int, int]] = set()
    for segment in (latest, latest.with_name(f"{latest.name}.1")):
        if segment.is_file():
            found.update(
                (int(w), int(s)) for w, s in
                _RECORD.findall(segment.read_text(encoding="utf-8",
                                                  errors="replace"))
            )
    return 100.0 * len(found) / TOTAL_RECORDS


def _run(root: Path, writers: int) -> tuple[float, int]:
    """Spawn *writers* processes over one log.  Returns (kept %, crashes)."""
    shutil.rmtree(root, ignore_errors=True)
    root.mkdir(parents=True)
    log_file = root / "trcc.log"
    each = TOTAL_RECORDS // writers

    procs = [
        subprocess.Popen(
            [sys.executable, __file__, "--writer", str(log_file), str(w),
             str(each), str(writers)],
            stderr=subprocess.PIPE, text=True, env={**os.environ},
        )
        for w in range(writers)
    ]
    crashes = sum(
        (proc.communicate()[1] or "").count("FileNotFoundError")
        for proc in procs
    )
    kept = len(_surviving(log_file))
    return 100.0 * kept / (each * writers), crashes


def main() -> int:
    log.info("smoke_log_multiprocess: %d records, %d x %d chain",
             TOTAL_RECORDS, MAX_BYTES, BACKUP_COUNT)
    root = Path(tempfile.mkdtemp(prefix="trcc-logsmoke-"))
    failures: list[str] = []
    control: float | None = None

    print(f"{TOTAL_RECORDS:,} records total, into a "
          f"{MAX_BYTES // 1000}kB x {BACKUP_COUNT} chain\n")
    print(f"  {'writers':>7}  {'kept':>7}  {'vs control':>10}  {'crashes':>7}"
          f"  {'latest':>7}")
    for writers in WRITER_COUNTS:
        kept, crashes = _run(root / f"w{writers}", writers)
        latest_kept = _latest_kept(root / f"w{writers}" / "trcc.log")
        if control is None:
            control = kept
        delta = kept - control
        print(f"  {writers:>7}  {kept:>6.1f}%  {delta:>+9.1f}pt  {crashes:>7}"
              f"  {latest_kept:>6.1f}%")

        if crashes:
            failures.append(
                f"{writers} writers: {crashes} rollover crash(es) — two "
                f"processes renamed the same segment",
            )
        if delta < -TOLERANCE_POINTS:
            failures.append(
                f"{writers} writers: kept {kept:.1f}% against a "
                f"{control:.1f}% single-writer control ({delta:+.1f}pt) — "
                f"concurrency is costing records",
            )

        if latest_kept < LATEST_MIN_KEPT:
            failures.append(
                f"{writers} writers: the per-run log kept only "
                f"{latest_kept:.1f}% — a joining process truncated a LIVE "
                f"peer's session out from under it",
            )

    # The lock must never be mistaken for a segment by the report's reader.
    sidecar = root / "w2" / f"trcc.log{LOCK_SUFFIX}"
    if sidecar.exists() and sidecar in log_chain(root / "w2" / "trcc.log"):
        failures.append(f"{sidecar.name} was read as log content")

    shutil.rmtree(root, ignore_errors=True)
    if failures:
        print()
        for line in failures:
            print(f"FAIL  {line}")
        print(f"\n{len(failures)} check(s) failed.")
        return 1
    print("\nConcurrent writers cost nothing and nothing crashed.")
    return 0


if __name__ == "__main__":
    if len(sys.argv) == 6 and sys.argv[1] == "--writer":
        _write(Path(sys.argv[2]), int(sys.argv[3]), int(sys.argv[4]),
               int(sys.argv[5]))
        raise SystemExit(0)
    raise SystemExit(main())
