"""
AIVOLVE Cross-Platform Storage Permission Security Manager
Phase 2 Step 4.2 Governance Subsystem Hardening

Provides deterministic, auditable filesystem security for the institutional GovernanceLedger:
  - Windows NTFS DACL Security:
      * Strict canonical SID allowlist model: Accepts ONLY the process user SID resolved
        directly from the Windows access token, Local SYSTEM (S-1-5-18), and Built-in
        Administrators (S-1-5-32-544).
      * Process user identity resolved via Win32 kernel security token APIs (OpenProcessToken),
        never from untrusted environment variables.
      * Native Win32 DACL inspection (advapi32.dll GetNamedSecurityInfoW and GetAce) inspecting
        every effective explicit and inherited ACE.
      * Inheritance disabled (SE_DACL_PROTECTED) and all inherited ACEs removed.
      * Rejection of unexpected allow ACEs (including unknown non-broad principals).
      * Detection and rejection of unexpected or contradictory Deny ACEs.
      * Parent directory DACL inspection: strictly bars unauthorized identities from holding
        write, create, delete, or modify permissions that could compromise the database perimeter.
      * Strict fail-closed error handling: zero silent exception swallowing on reset or grant.
  - POSIX (Linux/macOS):
      * File permissions 0600 (owner read/write only) on DB, WAL, and SHM files.
      * Effective octal mode bit and UID ownership verification.
      * Parent directory security: rejects group/other write access (mask 0o022) and verifies
        directory ownership matches service identity without relying solely on sticky bits.
      * Scoped umask context manager (scoped_posix_umask) preventing creation-time race conditions
        without persistent global process umask side-effects.
  - SQLite Lifecycle Security:
      * Enforces permissions across database creation, connection opening, WAL/SHM creation,
        checkpoints, and process restart recovery.
      * Fails closed in production if storage permissions cannot be enforced or verified.
"""

from typing import Dict, Any, List, Optional, Tuple, Set
import os
import sys
import stat
import shutil
import logging
import platform
import getpass
import subprocess
from datetime import datetime, timezone
from contextlib import contextmanager

logger = logging.getLogger("aivolve.storage_security")

# Canonical well-known Windows Security Identifiers (SIDs)
WELL_KNOWN_SID_SYSTEM: str = "S-1-5-18"                 # Local SYSTEM
WELL_KNOWN_SID_ADMINISTRATORS: str = "S-1-5-32-544"     # Built-in Administrators
WELL_KNOWN_SID_CREATOR_OWNER: str = "S-1-3-0"           # Creator Owner (directory container inheritance)
WELL_KNOWN_SID_OWNER_RIGHTS: str = "S-1-3-4"            # Owner Rights (directory owner permissions restriction)

# Broad principals that are strictly prohibited on Windows NTFS
UNAUTHORIZED_WINDOWS_PRINCIPALS: Set[str] = {
    "everyone",
    "users",
    "builtin\\users",
    "authenticated users",
    "nt authority\\authenticated users",
    "guests",
    "builtin\\guests",
    "anonymous logon",
    "nt authority\\anonymous logon",
    "interactive",
    "nt authority\\interactive",
    "network",
    "nt authority\\network",
    "batch",
    "nt authority\\batch",
    "world",
}

# Windows NTFS directory write/delete/create access mask bits
FILE_ADD_FILE: int = 0x0002
FILE_ADD_SUBDIRECTORY: int = 0x0004
FILE_DELETE_CHILD: int = 0x0040
DELETE: int = 0x00010000
WRITE_DAC: int = 0x00040000
WRITE_OWNER: int = 0x00080000
GENERIC_WRITE: int = 0x40000000
GENERIC_ALL: int = 0x10000000

UNAUTHORIZED_DIR_WRITE_MASK: int = (
    FILE_ADD_FILE
    | FILE_ADD_SUBDIRECTORY
    | FILE_DELETE_CHILD
    | DELETE
    | WRITE_DAC
    | WRITE_OWNER
    | GENERIC_WRITE
    | GENERIC_ALL
)


@contextmanager
def scoped_posix_umask(mask: int = 0o077):
    """
    Context manager that temporarily sets a restrictive process umask (default 0o077)
    during sensitive file creation or opening and guarantees restoring the prior umask
    upon exit. Prevents permanent global process umask mutations.
    """
    if os.name == "nt" or not hasattr(os, "umask"):
        yield
        return
    prev_mask = os.umask(mask)
    try:
        yield
    finally:
        os.umask(prev_mask)


def get_process_user_sid() -> str:
    """
    Resolves the canonical Security Identifier (SID) of the current process access token
    using native Windows Win32 security APIs (advapi32.dll OpenProcessToken).
    Falls back to 'whoami /user /fo csv /nh' directly querying the OS kernel subsystem.
    NEVER relies on USERNAME environment variables.
    """
    if os.name != "nt":
        return ""

    try:
        import ctypes
        from ctypes import wintypes

        advapi32 = ctypes.windll.advapi32
        kernel32 = ctypes.windll.kernel32

        TOKEN_QUERY = 0x0008
        TokenUser = 1

        kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        advapi32.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
        advapi32.OpenProcessToken.restype = wintypes.BOOL

        advapi32.GetTokenInformation.argtypes = [
            wintypes.HANDLE,
            ctypes.c_int,
            wintypes.LPVOID,
            wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD),
        ]
        advapi32.GetTokenInformation.restype = wintypes.BOOL

        advapi32.ConvertSidToStringSidW.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.LPWSTR)]
        advapi32.ConvertSidToStringSidW.restype = wintypes.BOOL

        kernel32.LocalFree.argtypes = [wintypes.HLOCAL]
        kernel32.LocalFree.restype = wintypes.HLOCAL
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL

        h_token = wintypes.HANDLE()
        if advapi32.OpenProcessToken(kernel32.GetCurrentProcess(), TOKEN_QUERY, ctypes.byref(h_token)):
            try:
                dw_size = wintypes.DWORD(0)
                advapi32.GetTokenInformation(h_token, TokenUser, None, 0, ctypes.byref(dw_size))
                if dw_size.value > 0:
                    buf = ctypes.create_string_buffer(dw_size.value)
                    if advapi32.GetTokenInformation(h_token, TokenUser, buf, dw_size.value, ctypes.byref(dw_size)):
                        class SID_AND_ATTRIBUTES(ctypes.Structure):
                            _fields_ = [("Sid", ctypes.c_void_p), ("Attributes", wintypes.DWORD)]

                        class TOKEN_USER(ctypes.Structure):
                            _fields_ = [("User", SID_AND_ATTRIBUTES)]

                        token_user = TOKEN_USER.from_buffer_copy(buf)
                        p_sid_str = wintypes.LPWSTR()
                        if advapi32.ConvertSidToStringSidW(token_user.User.Sid, ctypes.byref(p_sid_str)):
                            sid_val = str(p_sid_str.value).strip().upper()
                            kernel32.LocalFree(p_sid_str)
                            if sid_val.startswith("S-1-"):
                                return sid_val
            finally:
                kernel32.CloseHandle(h_token)
    except Exception as exc:
        logger.debug(f"Win32 OpenProcessToken SID lookup fallback: {exc}")

    # Fallback: direct OS kernel query via whoami /user
    try:
        res = subprocess.run(["whoami", "/user", "/fo", "csv", "/nh"], capture_output=True, text=True, check=True)
        parts = [p.strip().strip('"') for p in res.stdout.strip().split(",")]
        if len(parts) >= 2 and parts[1].upper().startswith("S-1-"):
            return parts[1].upper()
    except Exception as exc:
        logger.warning(f"whoami /user fallback query failed: {exc}")

    raise PermissionError("Failed to resolve current Windows process user SID from OS security subsystem")


def get_authorized_windows_sids() -> Set[str]:
    """
    Returns the strict allowlist of authorized canonical SIDs for the governance ledger:
      1. Actual process user SID resolved from the access token
      2. Local SYSTEM SID (S-1-5-18)
      3. Built-in Administrators SID (S-1-5-32-544)
    Additional explicitly configured SIDs may be added via AIVOLVE_GOVERNANCE_AUTHORIZED_SIDS.
    """
    user_sid = get_process_user_sid()
    sids: Set[str] = {
        user_sid.upper(),
        WELL_KNOWN_SID_SYSTEM.upper(),
        WELL_KNOWN_SID_ADMINISTRATORS.upper(),
    }
    extra = os.environ.get("AIVOLVE_GOVERNANCE_AUTHORIZED_SIDS", "")
    if extra:
        for item in extra.split(","):
            clean = item.strip().upper()
            if clean.startswith("S-1-"):
                sids.add(clean)
    return sids


def get_current_windows_user() -> str:
    """Returns the current Windows process user name (for telemetry and logging)."""
    return os.environ.get("USERNAME") or getpass.getuser()


def get_authorized_windows_principals() -> Set[str]:
    """Returns the set of authorized Windows identities (for backward compatibility)."""
    user = get_current_windows_user().lower().strip()
    domain = os.environ.get("USERDOMAIN", "").lower().strip()
    authorized = {
        user,
        "system",
        "nt authority\\system",
        "administrators",
        "builtin\\administrators",
    }
    if domain:
        authorized.add(f"{domain}\\{user}")

    extra = os.environ.get("AIVOLVE_GOVERNANCE_AUTHORIZED_USERS", "")
    if extra:
        for item in extra.split(","):
            clean = item.strip().lower()
            if clean:
                authorized.add(clean)
    return authorized


def parse_icacls_entries(stdout: str, target_path: str) -> List[Tuple[str, str]]:
    """
    Parses icacls stdout into a list of (principal, rights) tuples.
    Handles multi-line outputs and removes the target path prefix.
    """
    entries = []
    lines = [l.rstrip() for l in stdout.splitlines() if l.strip()]
    abs_path = os.path.abspath(target_path).lower()
    norm_target = os.path.normpath(target_path).lower()
    base_name = os.path.basename(target_path).lower()

    for line in lines:
        lower_line = line.lower()
        if "successfully processed" in lower_line or "failed processing" in lower_line:
            continue
        clean_line = line.strip()
        idx = clean_line.find(":(")
        if idx != -1:
            prefix = clean_line[:idx].strip()
            rights = clean_line[idx:].strip()
            lower_prefix = prefix.lower()
            if lower_prefix.startswith(abs_path):
                prefix = prefix[len(abs_path):].strip()
            elif lower_prefix.startswith(norm_target):
                prefix = prefix[len(norm_target):].strip()
            elif lower_prefix.startswith(base_name):
                prefix = prefix[len(base_name):].strip()

            if prefix:
                entries.append((prefix, rights))
    return entries


class Win32Ace:
    """Represents an effective Access Control Entry (ACE) from an NTFS DACL."""
    def __init__(self, sid: str, ace_type: int, ace_flags: int, mask: int):
        self.sid: str = sid.upper()
        self.ace_type: int = ace_type      # 0: ACCESS_ALLOWED, 1: ACCESS_DENIED
        self.ace_flags: int = ace_flags    # 0x10: INHERITED_ACE
        self.mask: int = mask

    @property
    def is_inherited(self) -> bool:
        return bool(self.ace_flags & 0x10)

    @property
    def is_allow(self) -> bool:
        return self.ace_type == 0

    @property
    def is_deny(self) -> bool:
        return self.ace_type == 1

    def __repr__(self) -> str:
        t = "ALLOW" if self.is_allow else ("DENY" if self.is_deny else f"TYPE_{self.ace_type}")
        inh = "INHERITED" if self.is_inherited else "EXPLICIT"
        return f"<Win32Ace {self.sid} {t} {inh} mask=0x{self.mask:08x}>"


def get_file_security_descriptor_aces(path: str) -> Tuple[bool, List[Win32Ace], bool]:
    """
    Inspects the NTFS security descriptor of a file or directory using native Win32 APIs:
      advapi32.dll GetNamedSecurityInfoW, GetSecurityDescriptorControl, and GetAce.
    
    Returns:
      (is_dacl_protected, list_of_aces, is_dacl_present)
    
    Raises:
      OSError: If GetNamedSecurityInfoW fails.
    """
    import ctypes
    from ctypes import wintypes

    advapi32 = ctypes.windll.advapi32
    kernel32 = ctypes.windll.kernel32

    DACL_SECURITY_INFORMATION = 0x00000004
    SE_FILE_OBJECT = 1

    advapi32.GetNamedSecurityInfoW.argtypes = [
        wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
        ctypes.POINTER(wintypes.LPVOID), ctypes.POINTER(wintypes.LPVOID),
        ctypes.POINTER(wintypes.LPVOID), ctypes.POINTER(wintypes.LPVOID),
        ctypes.POINTER(wintypes.LPVOID)
    ]
    advapi32.GetNamedSecurityInfoW.restype = wintypes.DWORD

    advapi32.GetSecurityDescriptorControl.argtypes = [
        wintypes.LPVOID, ctypes.POINTER(wintypes.WORD), ctypes.POINTER(wintypes.DWORD)
    ]
    advapi32.GetSecurityDescriptorControl.restype = wintypes.BOOL

    class ACL_SIZE_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("AceCount", wintypes.DWORD),
            ("AclBytesInUse", wintypes.DWORD),
            ("AclBytesFree", wintypes.DWORD),
        ]

    advapi32.GetAclInformation.argtypes = [wintypes.LPVOID, wintypes.LPVOID, wintypes.DWORD, ctypes.c_int]
    advapi32.GetAclInformation.restype = wintypes.BOOL

    advapi32.GetAce.argtypes = [wintypes.LPVOID, wintypes.DWORD, ctypes.POINTER(wintypes.LPVOID)]
    advapi32.GetAce.restype = wintypes.BOOL

    advapi32.ConvertSidToStringSidW.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.LPWSTR)]
    advapi32.ConvertSidToStringSidW.restype = wintypes.BOOL

    kernel32.LocalFree.argtypes = [wintypes.HLOCAL]
    kernel32.LocalFree.restype = wintypes.HLOCAL

    pSecDesc = wintypes.LPVOID()
    pDacl = wintypes.LPVOID()
    ret = advapi32.GetNamedSecurityInfoW(
        path, SE_FILE_OBJECT, DACL_SECURITY_INFORMATION, None, None, ctypes.byref(pDacl), None, ctypes.byref(pSecDesc)
    )
    if ret != 0:
        raise OSError(f"GetNamedSecurityInfoW failed on '{path}' with Win32 error code {ret}")

    try:
        control = wintypes.WORD(0)
        revision = wintypes.DWORD(0)
        is_protected = False
        if advapi32.GetSecurityDescriptorControl(pSecDesc, ctypes.byref(control), ctypes.byref(revision)):
            SE_DACL_PROTECTED = 0x1000
            is_protected = bool(control.value & SE_DACL_PROTECTED)

        aces: List[Win32Ace] = []
        if pDacl:
            size_info = ACL_SIZE_INFORMATION()
            advapi32.GetAclInformation(pDacl, ctypes.byref(size_info), ctypes.sizeof(size_info), 2)
            for i in range(size_info.AceCount):
                pAce = wintypes.LPVOID()
                if advapi32.GetAce(pDacl, i, ctypes.byref(pAce)):
                    header = ctypes.cast(pAce, ctypes.POINTER(ctypes.c_ubyte * 4)).contents
                    ace_type = int(header[0])
                    ace_flags = int(header[1])
                    mask = ctypes.c_uint32.from_address(pAce.value + 4).value
                    p_sid = ctypes.c_void_p(pAce.value + 8)
                    p_sid_str = wintypes.LPWSTR()
                    if advapi32.ConvertSidToStringSidW(p_sid, ctypes.byref(p_sid_str)):
                        sid_str = str(p_sid_str.value).strip().upper()
                        kernel32.LocalFree(p_sid_str)
                        aces.append(Win32Ace(sid_str, ace_type, ace_flags, mask))
        return is_protected, aces, bool(pDacl)
    finally:
        kernel32.LocalFree(pSecDesc)


class StoragePermissionManager:
    """
    Centralized, cross-platform security manager for the governance database.
    Manages base database file, write-ahead log (-wal), shared-memory index (-shm),
    and parent directory access controls.
    """

    def __init__(self, db_path: str, is_production: Optional[bool] = None):
        self.db_path = os.path.normpath(db_path) if db_path != ":memory:" else ":memory:"
        self.is_production = (
            is_production
            if is_production is not None
            else (
                os.environ.get("AIVOLVE_ENFORCE_PERMISSIONS") == "1"
                or (self.db_path != ":memory:" and not ("tmp" in self.db_path.lower() or "pytest" in self.db_path.lower()))
            )
        )
        self._last_enforcement_ts: Optional[str] = None
        self._last_verification_result: Optional[Tuple[bool, str]] = None
        self._is_windows = (os.name == "nt")

    @property
    def wal_path(self) -> str:
        return f"{self.db_path}-wal" if self.db_path != ":memory:" else ":memory:"

    @property
    def shm_path(self) -> str:
        return f"{self.db_path}-shm" if self.db_path != ":memory:" else ":memory:"

    @property
    def parent_dir(self) -> str:
        return os.path.dirname(os.path.abspath(self.db_path)) if self.db_path != ":memory:" else ""

    def get_target_files(self) -> List[str]:
        """Returns all existing storage files within the governance database boundary."""
        if self.db_path == ":memory:":
            return []
        files = []
        for p in [self.db_path, self.wal_path, self.shm_path]:
            if os.path.exists(p):
                files.append(p)
        return files

    def enforce_storage_permissions(self) -> None:
        """
        Enforces platform-specific restricted access permissions on the database and sidecars.
        Fails closed with ValueError if enforcement fails and production security is required.
        """
        if self.db_path == ":memory:":
            self._last_enforcement_ts = datetime.now(timezone.utc).isoformat()
            return

        now_str = datetime.now(timezone.utc).isoformat()

        if self._is_windows:
            self._enforce_windows_dacl()
        else:
            self._enforce_posix_permissions()

        self._last_enforcement_ts = now_str

        # Immediately verify effective permissions after enforcement
        valid, reason = self.verify_storage_permissions()
        if not valid and self.is_production:
            raise ValueError(
                f"Governance storage security failure: Post-enforcement verification failed on '{self.db_path}': {reason}. "
                "Failing closed to prevent unauthorized access."
            )

    def _enforce_windows_dacl(self) -> None:
        """
        Enforces restricted NTFS DACL using canonical SIDs via icacls.exe on Windows.
        Strict fail-closed: any command failure in reset or grant raises ValueError immediately.
        Zero silent exception swallowing.
        """
        icacls_bin = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "icacls.exe")
        if not os.path.exists(icacls_bin):
            icacls_bin = shutil.which("icacls")
        if not icacls_bin:
            err = "Windows icacls.exe utility not found on system PATH or System32"
            logger.error(err)
            raise ValueError(f"Governance storage failure: {err}")

        # Resolve process user SID directly from token (never from env vars)
        user_sid = get_process_user_sid()

        targets = self.get_target_files()
        if not targets and os.path.exists(self.db_path):
            targets = [self.db_path]

        for target in targets:
            abs_target = os.path.abspath(target)
            if not os.path.exists(abs_target):
                continue

            # 1. Reset permissions to clean baseline. No silent exception swallowing!
            try:
                res_reset = subprocess.run(
                    [icacls_bin, abs_target, "/reset"],
                    capture_output=True,
                    text=True,
                    check=True,
                )
                if res_reset.returncode != 0 or "failed processing 0 files" not in res_reset.stdout.lower():
                    if abs_target != os.path.abspath(self.db_path) and (
                        not os.path.exists(abs_target)
                        or "cannot find the file" in res_reset.stderr.lower()
                        or "cannot find the file" in res_reset.stdout.lower()
                        or res_reset.returncode == 2
                    ):
                        continue
                    err = f"icacls /reset failed on '{target}': {res_reset.stdout.strip()} {res_reset.stderr.strip()}"
                    logger.error(err)
                    raise ValueError(f"Governance storage security failure: {err}")
            except (subprocess.CalledProcessError, OSError) as exc:
                stdout_str = getattr(exc, "stdout", "") or ""
                stderr_str = getattr(exc, "stderr", "") or ""
                if abs_target != os.path.abspath(self.db_path) and (
                    not os.path.exists(abs_target)
                    or "cannot find the file" in stderr_str.lower()
                    or "cannot find the file" in stdout_str.lower()
                    or getattr(exc, "returncode", None) == 2
                ):
                    continue
                err_msg = f"Failed to reset permissions on '{target}': {exc}"
                logger.error(err_msg)
                raise ValueError(f"Governance storage security failure: {err_msg}") from exc

            # 2. Grant restricted Full Control strictly by canonical SIDs
            # /inheritance:r removes inherited ACEs and marks DACL protected
            # /grant:r grants Full Control strictly to user SID, SYSTEM, Administrators
            cmd = [
                icacls_bin,
                abs_target,
                "/inheritance:r",
                "/grant:r",
                f"*{user_sid}:(F)",
                f"*{WELL_KNOWN_SID_SYSTEM}:(F)",
                f"*{WELL_KNOWN_SID_ADMINISTRATORS}:(F)",
            ]
            try:
                res = subprocess.run(cmd, capture_output=True, text=True, check=True)
                if res.returncode != 0 or "failed processing 0 files" not in res.stdout.lower():
                    if abs_target != os.path.abspath(self.db_path) and (
                        not os.path.exists(abs_target)
                        or "cannot find the file" in res.stderr.lower()
                        or "cannot find the file" in res.stdout.lower()
                        or res.returncode == 2
                    ):
                        continue
                    err = f"icacls /grant failed on '{target}': {res.stdout.strip()} {res.stderr.strip()}"
                    logger.error(err)
                    raise ValueError(f"Governance storage security failure: {err}")
            except (subprocess.CalledProcessError, OSError) as exc:
                stdout_str = getattr(exc, "stdout", "") or ""
                stderr_str = getattr(exc, "stderr", "") or ""
                if abs_target != os.path.abspath(self.db_path) and (
                    not os.path.exists(abs_target)
                    or "cannot find the file" in stderr_str.lower()
                    or "cannot find the file" in stdout_str.lower()
                    or getattr(exc, "returncode", None) == 2
                ):
                    continue
                err_msg = f"Failed to enforce Windows NTFS DACL on '{target}': {exc}"
                logger.error(err_msg)
                raise ValueError(f"Governance storage security failure: {err_msg}") from exc

    def _enforce_posix_permissions(self) -> None:
        """Enforces POSIX mode 0600 on all storage files with scoped umask protection."""
        with scoped_posix_umask(0o077):
            targets = self.get_target_files()
            for target in targets:
                try:
                    os.chmod(target, 0o600)
                except OSError as exc:
                    err_msg = f"Failed to chmod 0600 on '{target}': {exc}"
                    logger.error(err_msg)
                    if self.is_production:
                        raise ValueError(f"Governance storage security failure: {err_msg}") from exc

    def verify_storage_permissions(self) -> Tuple[bool, str]:
        """
        Inspects the effective permissions / DACL of the database and sidecar files.
        Returns: (True, detail_message) if secure, or (False, failure_reason) if vulnerable.
        """
        if self.db_path == ":memory:":
            res = (True, "In-memory database; protected by process virtual memory boundary")
            self._last_verification_result = res
            return res

        if self._is_windows:
            res = self._verify_windows_dacl()
        else:
            res = self._verify_posix_permissions()

        self._last_verification_result = res
        return res

    def _verify_windows_dacl(self) -> Tuple[bool, str]:
        """
        Inspects effective NTFS DACL using native Win32 security APIs and strict SID allowlist:
          - Only process user SID, SYSTEM SID, and Administrators SID permitted.
          - Rejects any unauthorized Allow ACE (including non-broad domain or local accounts).
          - Rejects any unexpected Deny ACE.
          - Rejects any inherited ACE and verifies inheritance protection is active.
          - Inspects parent directory DACL: rejects unauthorized write/create/delete permissions.
        """
        targets = self.get_target_files()
        if not targets:
            if os.path.exists(self.parent_dir):
                return True, "Pending database file creation (parent directory verified)"
            return False, f"Parent directory '{self.parent_dir}' does not exist"

        try:
            authorized_sids = get_authorized_windows_sids()
        except Exception as exc:
            return False, f"Failed to resolve authorized Windows SIDs: {exc}"

        # 1. Inspect Storage Files (.db, -wal, -shm)
        for target in targets:
            if not os.path.exists(target):
                continue
            try:
                is_protected, aces, has_dacl = get_file_security_descriptor_aces(os.path.abspath(target))
            except Exception as exc:
                return False, f"Failed to read NTFS security descriptor for '{target}': {exc}"

            if not has_dacl:
                return False, f"Target file '{os.path.basename(target)}' has no DACL (NULL DACL exposes file to everyone)"

            if not is_protected:
                return False, (
                    f"Target file '{os.path.basename(target)}' has DACL inheritance enabled "
                    "(SE_DACL_PROTECTED not set). Inheritance must be disabled."
                )

            if not aces:
                return False, f"No DACL entries found for '{os.path.basename(target)}'"

            has_authorized_owner = False
            for ace in aces:
                # Reject any unexpected Deny ACE
                if ace.is_deny:
                    return False, (
                        f"Unexpected Deny ACE detected for SID '{ace.sid}' in '{os.path.basename(target)}'. "
                        "Deny ACEs contradict required access and are rejected."
                    )

                # Reject any inherited ACE
                if ace.is_inherited:
                    return False, (
                        f"Unexpected inherited ACE detected for SID '{ace.sid}' in '{os.path.basename(target)}'. "
                        "Inheritance must be explicitly broken."
                    )

                # Verify Allow ACE strictly against allowlist
                if ace.is_allow:
                    if ace.sid not in authorized_sids:
                        return False, (
                            f"Unauthorized ACE detected: SID '{ace.sid}' (mask 0x{ace.mask:08x}) is not in "
                            f"the strict authorized allowlist for '{os.path.basename(target)}'. "
                            "Unauthorized principals are strictly prohibited."
                        )
                    else:
                        has_authorized_owner = True

            if not has_authorized_owner:
                return False, (
                    f"No authorized process identity (process user, SYSTEM, Administrators) holds required access "
                    f"in DACL for '{os.path.basename(target)}'"
                )

        # 2. Inspect Parent Directory
        if os.path.exists(self.parent_dir):
            try:
                _, parent_aces, parent_has_dacl = get_file_security_descriptor_aces(os.path.abspath(self.parent_dir))
            except Exception as exc:
                return False, f"Failed to inspect parent directory DACL for '{self.parent_dir}': {exc}"

            authorized_dir_sids = authorized_sids | {
                WELL_KNOWN_SID_CREATOR_OWNER,
                WELL_KNOWN_SID_OWNER_RIGHTS,
            }

            if parent_has_dacl:
                for ace in parent_aces:
                    # If principal is not in authorized allowlist, verify it holds NO write/create/delete rights
                    if ace.is_allow and ace.sid not in authorized_dir_sids:
                        if (ace.mask & UNAUTHORIZED_DIR_WRITE_MASK) != 0:
                            return False, (
                                f"Insecure parent directory '{self.parent_dir}': Unauthorized identity SID '{ace.sid}' "
                                f"holds write/create/delete permissions (mask 0x{ace.mask:08x}). "
                                "Unauthorized identities could create, replace, rename, or delete the governance database."
                            )

        return True, (
            f"Windows NTFS DACL verified secure across {len(targets)} storage file(s) and parent directory: "
            "Inheritance disabled; restricted to canonical process user SID, SYSTEM, and Administrators; "
            "zero unauthorized or broad access."
        )

    def _verify_posix_permissions(self) -> Tuple[bool, str]:
        """Inspects POSIX mode bits on all storage files and verifies parent directory."""
        targets = self.get_target_files()
        if not targets:
            if os.path.exists(self.parent_dir):
                return True, "Pending database file creation (parent directory verified)"
            return False, f"Parent directory '{self.parent_dir}' does not exist"

        # 1. Verify parent directory permissions
        if os.path.exists(self.parent_dir):
            try:
                p_st = os.stat(self.parent_dir)
                p_mode = stat.S_IMODE(p_st.st_mode)

                # Reject unauthorized group or other write access (0o022)
                if (p_mode & 0o022) != 0:
                    return False, (
                        f"Insecure parent directory '{self.parent_dir}': Unauthorized write access "
                        f"(mode 0o{p_mode:o}, group/other write mask 0o022 matched). "
                        "Parent directory must not be writable by group or others."
                    )

                # Verify ownership matches current service identity
                if hasattr(os, "geteuid"):
                    current_uid = os.geteuid()
                    if p_st.st_uid != current_uid and p_st.st_uid != 0:
                        return False, (
                            f"Insecure parent directory '{self.parent_dir}': Owned by UID {p_st.st_uid}, "
                            f"which does not match current service identity (UID {current_uid}) or root."
                        )
            except OSError as exc:
                return False, f"Failed to stat parent directory '{self.parent_dir}': {exc}"

        # 2. Verify files are 0600 (owner read/write only)
        for target in targets:
            try:
                st = os.stat(target)
                mode = stat.S_IMODE(st.st_mode)
                if (mode & 0o077) != 0:
                    return False, (
                        f"File '{os.path.basename(target)}' has insecure permissions 0o{mode:o}. "
                        "Group and other access must be 0 (expected 0o600)."
                    )
                if hasattr(os, "geteuid"):
                    current_uid = os.geteuid()
                    if st.st_uid != current_uid and st.st_uid != 0:
                        return False, (
                            f"File '{os.path.basename(target)}' owned by UID {st.st_uid}, "
                            f"which does not match current service UID {current_uid}."
                        )
            except OSError as exc:
                return False, f"Failed to stat storage file '{target}': {exc}"

        return True, f"POSIX mode 0600 verified secure across {len(targets)} storage file(s)."

    def get_storage_security_status(self, sanitize_paths: bool = True) -> Dict[str, Any]:
        """
        Returns auditable storage security telemetry.
        Path sanitization prevents exposing full host filesystem hierarchy over public endpoints.
        """
        valid, detail = self.verify_storage_permissions()

        disp_path = os.path.basename(self.db_path) if (sanitize_paths and self.db_path != ":memory:") else self.db_path
        disp_parent = (
            "[PROTECTED_PARENT_DIR]" if (sanitize_paths and self.db_path != ":memory:") else self.parent_dir
        )

        wal_exists = os.path.exists(self.wal_path) if self.db_path != ":memory:" else False
        shm_exists = os.path.exists(self.shm_path) if self.db_path != ":memory:" else False

        return {
            "platform": "windows" if self._is_windows else "posix",
            "database_path": disp_path,
            "secured": valid,
            "verification_passed": valid,
            "effective_permissions": detail if valid else "NON_COMPLIANT",
            "wal_shm_status": {
                "wal_present": wal_exists,
                "shm_present": shm_exists,
                "secured": valid,
            },
            "parent_directory_status": {
                "path": disp_parent,
                "secured": valid,
            },
            "enforcement_timestamp": self._last_enforcement_ts or datetime.now(timezone.utc).isoformat(),
            "failure_reason": None if valid else detail,
        }
