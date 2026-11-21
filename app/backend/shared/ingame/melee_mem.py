"""
melee_mem.py -- read the live emulated GameCube RAM of a Slippi Dolphin process.

Locates MEM1 (GC 0x80000000) inside the Dolphin process the same way Dolphin
Memory Engine does -- find the 0x2000000 mapped region that starts with the
"GALE01" game id -- then exposes typed reads of GC addresses. This is the read
half of the memory-feedback harness (input half: melee_pipe.py). No libmelee,
no Slippi stream format; works on whatever Slippi build is running Melee 1.02.

Windows: kernel32 VirtualQueryEx scan + ReadProcessMemory/WriteProcessMemory
via stdlib ctypes (nothing to install).

Linux: /proc/<pid>/maps scan + process_vm_readv/process_vm_writev via libc.
Both need ptrace-level access to the target; the backend launches the
throwaway Dolphin itself, so with Yama ptrace_scope=1 (the usual default) the
parent relationship already grants it.
"""

import ctypes
import os
import struct
import sys

MEM1_REGION_SIZE = 0x2000000
MEM1_VALID = 0x1800000  # 24 MiB of real GC RAM
GC_BASE = 0x80000000
GAME_ID = b"GALE01"

IS_WINDOWS = os.name == "nt"
IS_MACOS = sys.platform == "darwin"

if IS_WINDOWS:
    import ctypes.wintypes as wt

    PROCESS_QUERY_INFORMATION = 0x0400
    PROCESS_VM_READ = 0x0010
    PROCESS_VM_WRITE = 0x0020
    PROCESS_VM_OPERATION = 0x0008
    MEM_MAPPED = 0x40000

    _k32 = ctypes.WinDLL("kernel32", use_last_error=True)

    class MEMORY_BASIC_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("BaseAddress", ctypes.c_ulonglong),
            ("AllocationBase", ctypes.c_ulonglong),
            ("AllocationProtect", wt.DWORD),
            ("__alignment1", wt.DWORD),
            ("RegionSize", ctypes.c_ulonglong),
            ("State", wt.DWORD),
            ("Protect", wt.DWORD),
            ("Type", wt.DWORD),
            ("__alignment2", wt.DWORD),
        ]
else:
    # libc.so.6 is glibc, i.e. Linux only -- on macOS this dlopen raises at
    # IMPORT time, which took down every module that merely imports the ingame
    # package (xdelta, bundles, ...) even though none of them read memory.
    # process_vm_readv has no macOS equivalent anyway (see MACOS notes), so the
    # reader is simply unavailable there; anything that tries to use it gets a
    # clear error instead of an import crash.
    _libc = ctypes.CDLL("libc.so.6", use_errno=True) if sys.platform.startswith("linux") else None

    class _iovec(ctypes.Structure):
        _fields_ = [("iov_base", ctypes.c_void_p), ("iov_len", ctypes.c_size_t)]

    if IS_MACOS:
        # macOS has no process_vm_readv. The equivalent is the Mach VM API:
        # take a send right on the target's task port, then mach_vm_read/write.
        #
        # task_for_pid is gated by the TARGET's signature. A hardened-runtime
        # binary without com.apple.security.get-task-allow refuses everyone --
        # root included -- which is how Slippi ships Dolphin, and why sudo does
        # not help. Against a copy re-signed ad-hoc WITH get-task-allow it
        # succeeds as the ordinary user: measured on macOS 26.x, full read AND
        # write, CSS at 59.9fps, no root anywhere.
        _libsys = ctypes.CDLL("/usr/lib/libSystem.B.dylib", use_errno=True)

        _mach_port_t = ctypes.c_uint
        _kern_return_t = ctypes.c_int
        _mach_vm_address_t = ctypes.c_uint64
        _mach_vm_size_t = ctypes.c_uint64

        _libsys.mach_task_self.restype = _mach_port_t
        _libsys.task_for_pid.restype = _kern_return_t
        _libsys.task_for_pid.argtypes = [_mach_port_t, ctypes.c_int,
                                         ctypes.POINTER(_mach_port_t)]
        _libsys.mach_vm_read_overwrite.restype = _kern_return_t
        _libsys.mach_vm_read_overwrite.argtypes = [
            _mach_port_t, _mach_vm_address_t, _mach_vm_size_t,
            _mach_vm_address_t, ctypes.POINTER(_mach_vm_size_t)]
        _libsys.mach_vm_write.restype = _kern_return_t
        _libsys.mach_vm_write.argtypes = [
            _mach_port_t, _mach_vm_address_t, ctypes.c_void_p, ctypes.c_uint]
        _libsys.mach_vm_region.restype = _kern_return_t
        _libsys.mach_vm_region.argtypes = [
            _mach_port_t, ctypes.POINTER(_mach_vm_address_t),
            ctypes.POINTER(_mach_vm_size_t), ctypes.c_int,
            ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint),
            ctypes.POINTER(_mach_port_t)]

        class _vm_region_basic_info_64(ctypes.Structure):
            _fields_ = [
                ("protection", ctypes.c_int),
                ("max_protection", ctypes.c_int),
                ("inheritance", ctypes.c_uint),
                ("shared", ctypes.c_uint),
                ("reserved", ctypes.c_uint),
                ("offset", ctypes.c_uint64),
                ("behavior", ctypes.c_int),
                ("user_wired_count", ctypes.c_ushort),
            ]

        _VM_REGION_BASIC_INFO_64 = 9
        _VM_PROT_READ, _VM_PROT_WRITE = 1, 2

    if _libc is not None:
        _iov_args = [
            ctypes.c_int, ctypes.POINTER(_iovec), ctypes.c_ulong,
            ctypes.POINTER(_iovec), ctypes.c_ulong, ctypes.c_ulong,
        ]
        _libc.process_vm_readv.restype = ctypes.c_ssize_t
        _libc.process_vm_readv.argtypes = _iov_args
        _libc.process_vm_writev.restype = ctypes.c_ssize_t
        _libc.process_vm_writev.argtypes = _iov_args


def addr_t(v):
    """mach_vm_address_t for a host address (64-bit, unsigned)."""
    return _mach_vm_address_t(v) if IS_MACOS else v


class Dolphin:
    """Attach to a Slippi Dolphin process and read Melee's emulated RAM."""

    def __init__(self, pid):
        if os.name != "nt" and _libc is None and not IS_MACOS:
            raise NotImplementedError(
                "Reading Dolphin's memory is not supported on this platform "
                f"({sys.platform}). The in-game harness is Windows/Linux/macOS.")
        if not pid:
            raise ValueError("Dolphin(pid) requires the Dolphin process id")
        self.pid = int(pid)
        if IS_WINDOWS:
            self.h = _k32.OpenProcess(
                PROCESS_QUERY_INFORMATION | PROCESS_VM_READ | PROCESS_VM_WRITE
                | PROCESS_VM_OPERATION, False, self.pid
            )
            if not self.h:
                raise OSError(f"OpenProcess({self.pid}) failed: {ctypes.get_last_error()}")
        else:
            self.h = None
            if IS_MACOS:
                self.task = _mach_port_t()
                kr = _libsys.task_for_pid(_libsys.mach_task_self(), self.pid,
                                          ctypes.byref(self.task))
                if kr != 0:
                    raise PermissionError(
                        f"task_for_pid({self.pid}) failed (kern_return {kr}). "
                        "On macOS the gate is the TARGET's code signature, not "
                        "your privileges: a hardened-runtime app without the "
                        "get-task-allow entitlement (which is how Slippi ships "
                        "Dolphin) refuses everyone, root included. Re-sign a "
                        "COPY of Dolphin ad-hoc with get-task-allow and point "
                        "NUCLEUS_SLIPPI_PATH at it -- then no sudo is needed. "
                        "See docs/dev/MACOS_BUILD.md.")
            elif not os.path.isdir(f"/proc/{self.pid}"):
                raise OSError(f"no such process: {self.pid}")
        self.base = None
        self.locate()

    # --- MEM1 discovery ------------------------------------------------------
    def locate(self):
        """(Re)find the MEM1 base. Returns False if Melee RAM isn't present."""
        if IS_WINDOWS:
            addr = 0
            mbi = MEMORY_BASIC_INFORMATION()
            while addr < 0x7FFFFFFFFFFF:
                if not _k32.VirtualQueryEx(
                    self.h, ctypes.c_void_p(addr), ctypes.byref(mbi), ctypes.sizeof(mbi)
                ):
                    break
                if mbi.Type == MEM_MAPPED and mbi.RegionSize == MEM1_REGION_SIZE:
                    if self._raw(mbi.BaseAddress, len(GAME_ID)) == GAME_ID:
                        self.base = mbi.BaseAddress
                        return True
                nxt = mbi.BaseAddress + mbi.RegionSize
                if nxt <= addr:
                    break
                addr = nxt
            self.base = None
            return False

        if IS_MACOS:
            # Walk the target's VM regions looking for the MEM1-sized readable
            # mapping that starts with the game id -- the Mach equivalent of the
            # /proc/maps scan below.
            addr = _mach_vm_address_t(0)
            size = _mach_vm_size_t(0)
            info = _vm_region_basic_info_64()
            obj = _mach_port_t()
            while True:
                count = ctypes.c_uint(ctypes.sizeof(info) // 4)
                kr = _libsys.mach_vm_region(
                    self.task, ctypes.byref(addr), ctypes.byref(size),
                    _VM_REGION_BASIC_INFO_64, ctypes.byref(info),
                    ctypes.byref(count), ctypes.byref(obj))
                if kr != 0:
                    break
                if (size.value == MEM1_REGION_SIZE
                        and (info.protection & _VM_PROT_READ)
                        and self._raw(addr.value, len(GAME_ID)) == GAME_ID):
                    self.base = addr.value
                    return True
                addr = _mach_vm_address_t(addr.value + size.value)
            self.base = None
            return False

        # Linux: scan /proc/<pid>/maps for a rw, non-file (or dolphin shm)
        # mapping exactly MEM1-sized whose first bytes are the game id.
        try:
            with open(f"/proc/{self.pid}/maps", "r") as f:
                lines = f.readlines()
        except OSError:
            self.base = None
            return False
        for line in lines:
            fields = line.split()
            if len(fields) < 2:
                continue
            addr_range, perms = fields[0], fields[1]
            if "r" not in perms or "w" not in perms:
                continue
            start_s, end_s = addr_range.split("-")
            start, end = int(start_s, 16), int(end_s, 16)
            if end - start != MEM1_REGION_SIZE:
                continue
            if self._raw(start, len(GAME_ID)) == GAME_ID:
                self.base = start
                return True
        self.base = None
        return False

    def alive(self):
        if IS_WINDOWS:
            code = wt.DWORD()
            if not _k32.GetExitCodeProcess(self.h, ctypes.byref(code)):
                return False
            return code.value == 259  # STILL_ACTIVE
        try:
            os.kill(self.pid, 0)
            return True
        except OSError:
            return False

    # --- raw access ------------------------------------------------------------
    def _raw(self, host_addr, size):
        if IS_WINDOWS:
            buf = ctypes.create_string_buffer(size)
            n = ctypes.c_size_t(0)
            ok = _k32.ReadProcessMemory(
                self.h, ctypes.c_void_p(host_addr), buf, size, ctypes.byref(n)
            )
            return buf.raw[: n.value] if ok else None
        if IS_MACOS:
            buf = ctypes.create_string_buffer(size)
            got = _mach_vm_size_t(0)
            kr = _libsys.mach_vm_read_overwrite(
                self.task, addr_t(host_addr), size,
                ctypes.cast(buf, ctypes.c_void_p).value, ctypes.byref(got))
            return buf.raw[:got.value] if kr == 0 else None
        buf = ctypes.create_string_buffer(size)
        local = _iovec(ctypes.cast(buf, ctypes.c_void_p), size)
        remote = _iovec(ctypes.c_void_p(host_addr), size)
        n = _libc.process_vm_readv(self.pid, ctypes.byref(local), 1,
                                   ctypes.byref(remote), 1, 0)
        if n < 0:
            return None
        return buf.raw[:n]

    def _write_raw(self, host_addr, data):
        if IS_WINDOWS:
            n = ctypes.c_size_t(0)
            ok = _k32.WriteProcessMemory(
                self.h, ctypes.c_void_p(host_addr), data, len(data), ctypes.byref(n)
            )
            return bool(ok) and n.value == len(data)
        if IS_MACOS:
            payload = bytes(data)
            buf = ctypes.create_string_buffer(payload, len(payload))
            kr = _libsys.mach_vm_write(self.task, addr_t(host_addr),
                                       ctypes.cast(buf, ctypes.c_void_p),
                                       len(payload))
            return kr == 0
        buf = ctypes.create_string_buffer(bytes(data), len(data))
        local = _iovec(ctypes.cast(buf, ctypes.c_void_p), len(data))
        remote = _iovec(ctypes.c_void_p(host_addr), len(data))
        n = _libc.process_vm_writev(self.pid, ctypes.byref(local), 1,
                                    ctypes.byref(remote), 1, 0)
        return n == len(data)

    # --- typed reads (big-endian, as the GameCube stores them) ---------------
    def host(self, gc_addr):
        return self.base + (gc_addr - GC_BASE)

    def bytes(self, gc_addr, size):
        if self.base is None:
            return None
        return self._raw(self.host(gc_addr), size)

    def snapshot(self, size=MEM1_VALID):
        """Read a contiguous block of MEM1 from the start (for diffing)."""
        return self._raw(self.base, size)

    def u8(self, gc_addr):
        b = self.bytes(gc_addr, 1)
        return b[0] if b else None

    def u16(self, gc_addr):
        b = self.bytes(gc_addr, 2)
        return struct.unpack(">H", b)[0] if b else None

    def u32(self, gc_addr):
        b = self.bytes(gc_addr, 4)
        return struct.unpack(">I", b)[0] if b else None

    def s32(self, gc_addr):
        b = self.bytes(gc_addr, 4)
        return struct.unpack(">i", b)[0] if b else None

    def f32(self, gc_addr):
        b = self.bytes(gc_addr, 4)
        return struct.unpack(">f", b)[0] if b else None

    def deref(self, pointer_addr, offset=0):
        """Follow a GC pointer (a u32 holding a 0x8xxxxxxx address) + offset."""
        p = self.u32(pointer_addr)
        if not p or not (GC_BASE <= p < GC_BASE + MEM1_VALID):
            return None
        return p + offset

    # --- typed writes (big-endian) -------------------------------------------
    # Write access lets the harness poke menu state (e.g. SSSData.force_stage_id)
    # directly. Used sparingly -- reads remain the primary feedback path.
    def write_bytes(self, gc_addr, data):
        if self.base is None:
            return False
        return self._write_raw(self.host(gc_addr), bytes(data))

    def write_u8(self, gc_addr, value):
        return self.write_bytes(gc_addr, struct.pack(">B", value & 0xFF))

    def write_s8(self, gc_addr, value):
        return self.write_bytes(gc_addr, struct.pack(">b", value))

    def write_u16(self, gc_addr, value):
        return self.write_bytes(gc_addr, struct.pack(">H", value & 0xFFFF))

    def write_u32(self, gc_addr, value):
        return self.write_bytes(gc_addr, struct.pack(">I", value & 0xFFFFFFFF))

    def write_f32(self, gc_addr, value):
        return self.write_bytes(gc_addr, struct.pack(">f", value))

    def close(self):
        if IS_WINDOWS and getattr(self, "h", None):
            try:
                _k32.CloseHandle(self.h)
            except Exception:
                pass
            self.h = None
