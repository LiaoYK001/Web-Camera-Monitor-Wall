"""Fixed native tool entrypoints; arguments are passed as a vector, never a shell."""
import os
import pathlib
import runpy
import sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
TOOLS = {
    "webobs-transcoder": "desktop-tools/transcoder.py",
    "webobs-s3-archive": "archive/s3_archive.py",
    "webobs-encrypted-backup": "backup/encrypted_backup.py",
    "webobs-detector-worker": "analytics/detector_worker.py",
    "webobs-online-source": "go2rtc/online_source.py",
}
if len(sys.argv) < 2 or sys.argv[1] not in TOOLS:
    raise SystemExit(2)
script = pathlib.Path(__file__).resolve().parents[1] / TOOLS[sys.argv[1]]
sys.argv = [str(script), *sys.argv[2:]]
runpy.run_path(str(script), run_name="__main__")
