"""Optional read-only PDH diagnostics; no GPU total, hardware-decode or parity verdict."""
from __future__ import annotations

import ctypes as C
import math
import os
import re

INSTANCE = re.compile(
    r"pid_([0-9]{1,10})_luid_(0x[0-9a-f]{1,8})_(0x[0-9a-f]{1,8})_phys_([0-9]{1,3})"
    r"(?:_eng_([0-9]{1,5})_engtype_([A-Za-z0-9_ -]{1,80}))?\Z", re.I)
PATHS = {
    "engines": r"\GPU Engine(*)\Utilization Percentage",
    "dedicated": r"\GPU Process Memory(*)\Dedicated Usage",
    "shared": r"\GPU Process Memory(*)\Shared Usage",
}
MAX_BYTES = 16 * 1024 * 1024
MAX_ITEMS = 100000


class PdhError(Exception):
    def __init__(self, code):
        self.code = int(code) & 0xFFFFFFFF
        super().__init__(f"PDH status 0x{self.code:08x}")


class Pdh:
    """Language-neutral counters, bounded wildcard buffers and deterministic query cleanup."""
    def __init__(self):
        if os.name != "nt" or C.sizeof(C.c_void_p) != 8:
            raise ValueError("PDH GPU sampling requires Windows x64")
        self.dll = C.WinDLL("pdh")
        self.query = C.c_void_p()
        self.counters = {}
        self.errors = {}

        class Number(C.Union):
            _fields_ = [("doubleValue", C.c_double), ("largeValue", C.c_int64)]

        class Value(C.Structure):
            _anonymous_ = ("number",)
            _fields_ = [("status", C.c_uint32), ("number", Number)]

        class Item(C.Structure):
            _fields_ = [("name", C.c_wchar_p), ("value", Value)]

        self.Item = Item
        signatures = {
            "PdhOpenQueryW": [C.c_wchar_p, C.c_size_t, C.POINTER(C.c_void_p)],
            "PdhAddEnglishCounterW": [C.c_void_p, C.c_wchar_p, C.c_size_t, C.POINTER(C.c_void_p)],
            "PdhCollectQueryData": [C.c_void_p],
            "PdhGetFormattedCounterArrayW": [C.c_void_p, C.c_uint32, C.POINTER(C.c_uint32),
                                             C.POINTER(C.c_uint32), C.c_void_p],
            "PdhCloseQuery": [C.c_void_p],
        }
        for name, arguments in signatures.items():
            function = getattr(self.dll, name)
            function.argtypes = arguments
            function.restype = C.c_uint32
        status = self.dll.PdhOpenQueryW(None, 0, C.byref(self.query))
        if status:
            raise PdhError(status)
        try:
            for kind, path in PATHS.items():
                handle = C.c_void_p()
                status = self.dll.PdhAddEnglishCounterW(self.query, path, 0, C.byref(handle))
                if status:
                    self.errors[kind] = int(status)
                else:
                    self.counters[kind] = handle
        except BaseException:
            self.close()
            raise

    def _array(self, kind, handle):
        # Rates need two collections; item status is still checked individually.
        fmt = 0x200 | 0x8000 if kind == "engines" else 0x400  # DOUBLE|NOCAP100 / LARGE
        for _ in range(3):
            size, count = C.c_uint32(), C.c_uint32()
            status = self.dll.PdhGetFormattedCounterArrayW(handle, fmt, C.byref(size), C.byref(count), None)
            if status == 0 and count.value == 0:
                return []
            if status != 0x800007D2:  # PDH_MORE_DATA
                raise PdhError(status)
            capacity = size.value
            if not 0 < capacity <= MAX_BYTES:
                raise PdhError(0xC0000BBD)  # bounded/invalid data
            buffer = C.create_string_buffer(capacity)
            status = self.dll.PdhGetFormattedCounterArrayW(handle, fmt, C.byref(size), C.byref(count), buffer)
            if status == 0x800007D2:
                continue  # instances grew; restart with a fresh zero-size query
            if status:
                raise PdhError(status)
            if count.value > MAX_ITEMS or count.value * C.sizeof(self.Item) > capacity:
                raise PdhError(0xC0000BBD)
            items = C.cast(buffer, C.POINTER(self.Item))
            return [(items[i].name or "", int(items[i].value.status),
                     items[i].value.doubleValue if kind == "engines" else items[i].value.largeValue)
                    for i in range(count.value)]
        raise PdhError(0x800007D2)

    def read(self):
        if not self.query:
            raise PdhError(0xC0000BBC)
        if not self.counters:
            return {}, self.errors.copy()
        status = self.dll.PdhCollectQueryData(self.query)
        if status:
            return {}, {kind: int(status) for kind in self.counters} | self.errors
        rows, errors = {}, self.errors.copy()
        for kind, handle in self.counters.items():
            try:
                rows[kind] = self._array(kind, handle)
            except PdhError as error:
                errors[kind] = error.code
        return rows, errors

    def close(self):
        if self.query:
            self.dll.PdhCloseQuery(self.query)
            self.query = C.c_void_p()


def select(rows, stable):
    """Retain only verified owned identities; never serialize other processes' instances."""
    result, rejected = [], 0
    seen = set()
    for kind, values in rows.items():
        if kind not in PATHS:
            raise ValueError("Unknown GPU counter kind")
        for name, status, value in values:
            match = INSTANCE.fullmatch(name)
            if not match:
                # Unknown formats cannot safely be attributed; no raw name in output.
                rejected += 1
                continue
            pid = int(match[1])
            if pid not in stable:
                continue
            if (status not in (0, 1) or type(value) not in (int, float)
                    or not 0 <= value <= 2 ** 63 - 1 or not math.isfinite(value)):
                rejected += 1
                continue
            if kind != "engines" and type(value) is not int:
                rejected += 1
                continue
            if (kind == "engines") != (match[5] is not None):
                rejected += 1
                continue
            key = (kind, name.lower())
            if key in seen:
                rejected += 1
                continue
            seen.add(key)
            row = {"identity": stable[pid], "adapterLuid": f"{int(match[2], 16):08x}:{int(match[3], 16):08x}",
                   "physicalAdapter": int(match[4]), "kind": kind}
            if kind == "engines":
                row.update(engine=int(match[5]), engineType=match[6], utilizationPercent=value)
            else:
                row["bytes"] = value
            result.append(row)
    return result, rejected


class Sampler:
    """A newly observed/reused PID must survive two observations before rate attribution."""
    def __init__(self, backend=None):
        self.backend = backend if backend is not None else Pdh()
        self.previous = {}

    def sample(self, processes, verify_alive):
        before = {p["pid"]: p["identity"] for p in processes if not p["exited"]}
        rows, errors = self.backend.read()
        after = {pid: ident for pid, ident in before.items() if verify_alive(ident)}
        stable = {pid: ident for pid, ident in after.items() if self.previous.get(pid) == ident}
        values, rejected = select(rows, stable)
        priming = not self.previous
        self.previous = after
        return {"status": "priming" if priming else "sampled" if values else "unavailable",
                "method": "PDH-English-per-process-adapter-engine", "qualified": False,
                "coverageIncomplete": True, "rows": values, "rejectedRows": rejected,
                "counterErrors": {kind: f"0x{code:08x}" for kind, code in errors.items()}}

    def close(self):
        self.backend.close()
