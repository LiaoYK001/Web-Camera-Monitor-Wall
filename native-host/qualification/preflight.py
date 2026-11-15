#!/usr/bin/env python3
"""Target-machine P5 preflight: machine/tooling checks only, never a performance verdict."""
from __future__ import annotations

import argparse
import ctypes
import ctypes.wintypes as wintypes
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import platform
import sys

from common import SCHEMA, digest, metadata as metadata_contract, new_private_directory, read_json, write_json

BOUNDARIES = (
    "Preflight proves only that this machine exposes the expected Windows/GPU/monitor/host facts and that the two "
    "candidate EXEs and one operator metadata file are internally consistent. It does not capture pixels, start a "
    "camera, measure GPU decode, latency or CPU load, and never marks a P5 campaign qualified."
)


class MemoryStatusEx(ctypes.Structure):
    _fields_ = [("dwLength", wintypes.DWORD), ("dwMemoryLoad", wintypes.DWORD),
                ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]


def _windows_probe() -> dict:
    if os.name != "nt":
        raise RuntimeError("System probing requires Windows")
    import winreg

    memory = MemoryStatusEx()
    memory.dwLength = ctypes.sizeof(MemoryStatusEx)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(memory)):
        raise RuntimeError("GlobalMemoryStatusEx failed")
    cpu = ""
    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0") as key:
        cpu = winreg.QueryValueEx(key, "ProcessorNameString")[0].strip()
    adapters = []
    class_root = r"SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}"
    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, class_root) as key:
        index = 0
        while True:
            try:
                subkey = winreg.EnumKey(key, index)
            except OSError:
                break
            index += 1
            if not subkey.isdigit():
                continue
            try:
                with winreg.OpenKey(key, subkey) as adapter:
                    name = winreg.QueryValueEx(adapter, "DriverDesc")[0].strip()
                    driver = winreg.QueryValueEx(adapter, "DriverVersion")[0].strip()
            except OSError:
                continue
            if name:
                adapters.append({"name": name, "driverVersion": driver})
    monitors = 0
    def callback(_hm, _hdc, _rect, _data):
        nonlocal monitors
        monitors += 1
        return 1
    monitor_proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HMONITOR, wintypes.HDC,
                                      ctypes.POINTER(wintypes.RECT), wintypes.LPARAM)
    if not ctypes.windll.user32.EnumDisplayMonitors(None, None, monitor_proc(callback), 0):
        monitors = 1
    return {
        "os": platform.platform(),
        "osRelease": platform.release(),
        "osBuild": platform.version(),
        "machine": platform.machine(),
        "cpu": cpu,
        "logicalProcessors": os.cpu_count() or 0,
        "memoryBytes": memory.ullTotalPhys,
        "adapters": adapters,
        "monitors": monitors,
        "primaryWidth": ctypes.windll.user32.GetSystemMetrics(0),
        "primaryHeight": ctypes.windll.user32.GetSystemMetrics(1),
        "python": platform.python_version(),
    }


def executable(path: Path, role: str) -> dict:
    resolved = path.resolve(strict=True)
    if resolved.is_symlink() or not resolved.is_file() or resolved.name.lower() != "obs64.exe":
        raise ValueError(f"{role} must be a regular obs64.exe")
    size = resolved.stat().st_size
    if size <= 0 or size > 1024 * 1024 * 1024:
        raise ValueError(f"{role} size is implausible")
    return {"role": role, "name": resolved.name, "bytes": size, "sha256": digest(resolved)}


def run(native: Path, obs: Path, metadata_path: Path, output: Path, min_memory_gb: int,
        min_monitors: int, diagnostic: bool, system: dict | None = None) -> dict:
    native_exe = executable(native, "native")
    obs_exe = executable(obs, "obs")
    raw = read_json(metadata_path)
    meta = metadata_contract(raw)
    if meta["workload"] != "five-real-h265":
        if not diagnostic:
            raise ValueError("Preflight for a real campaign requires workload=five-real-h265")
    if any(item["codec"] != "h265" for item in meta["inputs"]):
        raise ValueError("Every P5 input must declare codec=h265")
    declarations = raw["declarations"]
    all_declared = all(declarations.values())
    if not all_declared and not diagnostic:
        raise ValueError("Operator declarations must all be confirmed before a real preflight")
    probe = system if system is not None else _windows_probe()
    checks = []

    def check(identifier: str, passed: bool, detail: str) -> None:
        checks.append({"id": identifier, "passed": bool(passed), "detail": detail})

    check("native-obs64", True, f"{native_exe['name']} {native_exe['bytes']} B sha256 {native_exe['sha256'][:12]}…")
    check("reference-obs64", True, f"{obs_exe['name']} {obs_exe['bytes']} B sha256 {obs_exe['sha256'][:12]}…")
    check("distinct-builds", native_exe["sha256"] != obs_exe["sha256"], "native and reference OBS bytes must differ")
    check("five-inputs", len(meta["inputs"]) == 5, f"{len(meta['inputs'])} declared inputs")
    check("five-h265", meta["workload"] == "five-real-h265" if not diagnostic else True,
          f"workload={meta['workload']}")
    check("declarations", all_declared or diagnostic,
          f"{sum(declarations.values())}/{len(declarations)} confirmed" + (" (placeholders allowed)" if diagnostic else ""))
    cpu = probe.get("cpu") or ""
    check("cpu", bool(cpu), cpu or "CPU name unavailable")
    check("gpu", bool(probe.get("adapters")), ", ".join(a["name"] for a in probe.get("adapters", [])) or "no adapter")
    memory_bytes = int(probe.get("memoryBytes") or 0)
    check("memory", memory_bytes >= min_memory_gb * 1024 ** 3,
          f"{memory_bytes / 1024 ** 3:.1f} GiB >= {min_memory_gb} GiB")
    check("monitors", int(probe.get("monitors") or 0) >= min_monitors,
          f"{probe.get('monitors')} monitor(s) >= {min_monitors}")
    status = "pass" if all(item["passed"] for item in checks) else "fail"
    receipt = {
        "schemaVersion": SCHEMA,
        "kind": "native-p5-preflight",
        "status": status,
        "qualified": False,
        "strictTotal": False,
        "coverageIncomplete": True,
        "diagnostic": bool(diagnostic),
        "generatedAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "environment": probe,
        "executables": {"native": native_exe, "obs": obs_exe},
        "metadata": {"campaignId": meta["campaignId"], "runId": meta["runId"], "pairId": meta["pairId"],
                     "workload": meta["workload"], "allDeclarationsTrue": all_declared,
                     "metadataSha256": digest(metadata_path)},
        "checks": checks,
        "boundaries": BOUNDARIES,
    }
    new_private_directory(output)
    write_json(output / "preflight.json", receipt)
    if diagnostic:
        # The example metadata is public; the receipt must not be mistaken for a campaign.
        (output / "README.txt").write_text(
            "Diagnostic preflight only. Not a P5 campaign receipt and not performance evidence.\n", encoding="utf-8")
    return receipt


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="Check target-machine P5 prerequisites; never qualifies performance.")
    result.add_argument("--native-exe", type=Path, required=True)
    result.add_argument("--obs-exe", type=Path, required=True)
    result.add_argument("--metadata", type=Path, required=True)
    result.add_argument("--output", type=Path, required=True)
    result.add_argument("--min-memory-gb", type=int, default=16)
    result.add_argument("--min-monitors", type=int, default=1)
    result.add_argument("--diagnostic", action="store_true",
                        help="Allow fixture/placeholder metadata for tooling checks; receipt stays non-qualifying")
    return result


def main() -> int:
    args = parser().parse_args()
    try:
        receipt = run(args.native_exe, args.obs_exe, args.metadata, args.output,
                      args.min_memory_gb, args.min_monitors, args.diagnostic)
    except (ValueError, OSError, RuntimeError) as error:
        print(f"preflight failed: {error}", file=sys.stderr)
        return 2
    print(json.dumps({"status": receipt["status"], "checks": len(receipt["checks"]),
                      "failed": [c["id"] for c in receipt["checks"] if not c["passed"]]}, ensure_ascii=False))
    return 0 if receipt["status"] == "pass" else 4


if __name__ == "__main__":
    raise SystemExit(main())
