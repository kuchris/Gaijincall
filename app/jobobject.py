"""將本 process 放入 Windows Job Object（KILL_ON_JOB_CLOSE）。

之後開嘅子 process（llama-server、TTS worker、ProcLoopback）會自動加入同一個 job；
本 process 點樣結束（包括被強制終止）都會連帶結束佢哋，唔會留低孤兒霸住 VRAM。
"""

import ctypes
from ctypes import wintypes

JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
JobObjectExtendedLimitInformation = 9


class _IoCounters(ctypes.Structure):
    _fields_ = [(name, ctypes.c_ulonglong) for name in (
        "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
        "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]


class _BasicLimit(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_longlong), ("PerJobUserTimeLimit", ctypes.c_longlong),
        ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
        ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD), ("SchedulingClass", wintypes.DWORD),
    ]


class _ExtendedLimit(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", _BasicLimit), ("IoInfo", _IoCounters),
        ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


_job = None  # 保持 handle 開住；process 結束時由系統關閉，觸發 KILL_ON_JOB_CLOSE


def kill_children_on_exit() -> bool:
    global _job
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    job = kernel32.CreateJobObjectW(None, None)
    if not job:
        return False
    info = _ExtendedLimit()
    info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    ok = kernel32.SetInformationJobObject(wintypes.HANDLE(job), JobObjectExtendedLimitInformation,
                                          ctypes.byref(info), ctypes.sizeof(info))
    ok = ok and kernel32.AssignProcessToJobObject(wintypes.HANDLE(job), wintypes.HANDLE(kernel32.GetCurrentProcess()))
    if ok:
        _job = job
    return bool(ok)
