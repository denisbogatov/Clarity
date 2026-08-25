"""Crash-persistent diagnostics for Clarity foliage proxy generation."""

import ctypes
import datetime
import os
import sys
import tempfile
import time


CLARITY_PROXY_LOG_PATH = os.path.join(
    tempfile.gettempdir(), "Clarity_TreeVDL_proxy.log"
)


class _ClarityMemoryStatus(ctypes.Structure):
    _fields_ = (
        ("length", ctypes.c_ulong),
        ("memory_load", ctypes.c_ulong),
        ("total_physical", ctypes.c_ulonglong),
        ("available_physical", ctypes.c_ulonglong),
        ("total_page_file", ctypes.c_ulonglong),
        ("available_page_file", ctypes.c_ulonglong),
        ("total_virtual", ctypes.c_ulonglong),
        ("available_virtual", ctypes.c_ulonglong),
        ("available_extended_virtual", ctypes.c_ulonglong),
    )


class _ClarityProcessMemory(ctypes.Structure):
    _fields_ = (
        ("cb", ctypes.c_ulong),
        ("page_fault_count", ctypes.c_ulong),
        ("peak_working_set_size", ctypes.c_size_t),
        ("working_set_size", ctypes.c_size_t),
        ("quota_peak_paged_pool_usage", ctypes.c_size_t),
        ("quota_paged_pool_usage", ctypes.c_size_t),
        ("quota_peak_non_paged_pool_usage", ctypes.c_size_t),
        ("quota_non_paged_pool_usage", ctypes.c_size_t),
        ("pagefile_usage", ctypes.c_size_t),
        ("peak_pagefile_usage", ctypes.c_size_t),
        ("private_usage", ctypes.c_size_t),
    )


def _clarity_memory_snapshot():
    if sys.platform != "win32":
        return {}
    try:
        clarity_status = _ClarityMemoryStatus()
        clarity_status.length = ctypes.sizeof(clarity_status)
        clarity_kernel = ctypes.windll.kernel32
        clarity_psapi = ctypes.windll.psapi
        clarity_kernel.GetCurrentProcess.restype = ctypes.c_void_p
        clarity_psapi.GetProcessMemoryInfo.argtypes = (
            ctypes.c_void_p,
            ctypes.POINTER(_ClarityProcessMemory),
            ctypes.c_ulong,
        )
        clarity_psapi.GetProcessMemoryInfo.restype = ctypes.c_int
        clarity_kernel.GlobalMemoryStatusEx(ctypes.byref(clarity_status))
        clarity_process = _ClarityProcessMemory()
        clarity_process.cb = ctypes.sizeof(clarity_process)
        clarity_psapi.GetProcessMemoryInfo(
            clarity_kernel.GetCurrentProcess(),
            ctypes.byref(clarity_process),
            clarity_process.cb,
        )
        return {
            "rss_mib": round(clarity_process.working_set_size / (1024 * 1024), 1),
            "private_mib": round(clarity_process.private_usage / (1024 * 1024), 1),
            "available_mib": round(clarity_status.available_physical / (1024 * 1024), 1),
            "memory_load_pct": int(clarity_status.memory_load),
        }
    except Exception:
        return {}


def clarity_proxy_log_reset(**clarity_fields):
    try:
        with open(CLARITY_PROXY_LOG_PATH, "w", encoding="utf-8") as clarity_file:
            clarity_file.write("Clarity TreeVDL proxy diagnostic log\n")
            clarity_file.flush()
            os.fsync(clarity_file.fileno())
        clarity_proxy_log("log-start", **clarity_fields)
    except Exception:
        pass


def clarity_proxy_log(clarity_stage, **clarity_fields):
    try:
        clarity_values = {
            "wall": datetime.datetime.now().isoformat(timespec="milliseconds"),
            "elapsed": round(time.perf_counter(), 3),
            "pid": os.getpid(),
            "stage": clarity_stage,
        }
        clarity_values.update(_clarity_memory_snapshot())
        clarity_values.update(clarity_fields)
        clarity_line = " ".join(
            f"{clarity_key}={str(clarity_value).replace(chr(10), ' ')}"
            for clarity_key, clarity_value in clarity_values.items()
        )
        with open(CLARITY_PROXY_LOG_PATH, "a", encoding="utf-8") as clarity_file:
            clarity_file.write(clarity_line + "\n")
            clarity_file.flush()
            os.fsync(clarity_file.fileno())
    except Exception:
        pass
