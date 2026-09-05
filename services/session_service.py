"""Session continuation & authorization helpers for MED-SETU.

Streamlit keeps ``st.session_state`` alive only for the lifetime of one
browser/websocket session.  A full browser refresh can drop that session and
Streamlit then boots the app with an empty session state, which is
indistinguishable from a fresh "logged out" session.

To survive ordinary browser refreshes -- WITHOUT storing passwords, without
weakening authentication, and without any database schema change -- we attach a
short-lived, signed, opaque token to the URL query string.  On the next run, if
session state is empty/absent but a valid token is present, we verify the HMAC
signature, expiry, and re-validate the account directly against the database
before restoring the session.

The token deliberately contains NO credentials: only the numeric user id, role
(or patient portal id), an expiry timestamp, and a random nonce, wrapped in an
HMAC-SHA256 signature bound to a server-side secret (never stored in session
state).
"""

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from typing import Any, Dict, Optional, Set

import streamlit as st

from database.models import User, Patient
from services.auth_service import AuthService

#: Query-string parameter that carries the signed session token.
PARAM_KEY = "medsetu"

#: How long a refresh-survival token stays valid (prototype-appropriate).
SESSION_TTL_SECONDS = 12 * 60 * 60

#: Roles allowed to perform privileged administrative operations.
ADMIN_LIKE_ROLES: Set[str] = {
    "hospital_admin",
    "government_admin",
    "government",
    "admin",
    "super_admin",
    "demo_admin",
}

#: Roles that map to the clinical staff workspace.
STAFF_ROLES: Set[str] = {"receptionist", "doctor"}


def _process_secret() -> bytes:
    """Return the server-side secret used to sign session continuation tokens.

    Prefer the ``MED_SETU_SESSION_SECRET`` environment variable when set (so
    multiple worker processes agree).  Otherwise fall back to a per-process
    secret: it is stable for the life of the server process (so ordinary
    browser refreshes keep working), and it invalidates all tokens on a server
    restart -- which is the safe, expected behaviour.
    """
    from_env = os.environ.get("MED_SETU_SESSION_SECRET")
    if from_env:
        return from_env.encode("utf-8")
    return _PER_PROCESS_SECRET


#: Per-process fallback secret. Generated once at import time and stable across
#: every rerun inside the same Streamlit process.
_PER_PROCESS_SECRET: bytes = hashlib.sha256(os.urandom(32)).digest()


def normalize_role(role: Any) -> str:
    """Normalize a role value to a bare lowercase string (``"receptionist"``).

    Handles enum reprs like ``UserRole.Receptionist`` or ``"UserRole.Receptionist"``
    by taking the final dotted segment, lowercasing and stripping whitespace.
    """
    if role is None:
        return ""
    value = str(role).strip().lower()
    if "." in value:
        value = value.split(".")[-1]
    return value


def is_role_allowed(role: Any, allowed_roles: Set[str]) -> bool:
    """Return True when the (normalized) role is present in allowed_roles."""
    return normalize_role(role) in {normalize_role(r) for r in allowed_roles}


def denial(message: str) -> Dict[str, Any]:
    """Standard "not authorized" result dict used by service methods."""
    return {"success": False, "error": message}


class AuthSessionService:
    """Sign/verify refresh-survival tokens and manage session lifecycle."""

    # ── Token creation & verification (pure, DB-free) ──

    @staticmethod
    def issue_token(
        user_id: Optional[int] = None,
        role: str = "",
        patient_portal_id: Optional[int] = None,
        ttl_seconds: int = SESSION_TTL_SECONDS,
    ) -> str:
        """Issue a signed, expiring session continuation token.

        Used both by the app (on login) and by tests to simulate a browser
        that preserved the URL but lost its in-memory session state.
        """
        now = int(time.time())
        payload = {
            "uid": user_id,
            "role": normalize_role(role),
            "pid": patient_portal_id,
            "exp": now + ttl_seconds,
            "n": secrets.token_hex(8),
        }
        payload_b64 = _b64encode(json.dumps(payload).encode("utf-8"))
        signature = _signature(payload_b64)
        return f"{payload_b64}.{signature}"

    @staticmethod
    def validate_token(token: Optional[str]) -> Optional[Dict[str, Any]]:
        """Verify signature + expiry. Returns payload dict or None.

        This performs NO database access; callers must still re-validate the
        account against the database before trusting the token.
        """
        if not token:
            return None
        try:
            payload_b64, signature = token.rsplit(".", 1)
            if not hmac.compare_digest(_signature(payload_b64), signature):
                return None
            payload = json.loads(_b64decode(payload_b64))
        except (ValueError, TypeError, json.JSONDecodeError):
            return None
        if int(payload.get("exp", 0)) < int(time.time()):
            return None
        return payload

    # ── Session-state helpers (require a running Streamlit script) ──

    @staticmethod
    def attach_token(
        user_id: Optional[int] = None,
        role: str = "",
        patient_portal_id: Optional[int] = None,
    ) -> None:
        """Write the signed token into the URL (query params) if it changed.

        Only writes when the value differs, to avoid needless reruns.
        """
        token = AuthSessionService.issue_token(user_id, role, patient_portal_id)
        try:
            if st.query_params.get(PARAM_KEY) != token:
                st.query_params[PARAM_KEY] = token
        except Exception:
            pass

    @staticmethod
    def detach_token() -> None:
        """Remove the session token from the URL."""
        try:
            if PARAM_KEY in st.query_params:
                del st.query_params[PARAM_KEY]
        except Exception:
            pass

    @staticmethod
    def _read_token() -> str:
        try:
            value = st.query_params.get(PARAM_KEY, "")
            if isinstance(value, list):
                return value[0] if value else ""
            return value or ""
        except Exception:
            return ""

    @staticmethod
    def restore_session(db) -> bool:
        """Rebuild a lost session from a valid URL token (e.g. after refresh).

        Re-validates the account against the database before restoring any
        state. Returns True when a session was restored.
        """
        token = AuthSessionService._read_token()
        payload = AuthSessionService.validate_token(token)
        if not payload:
            AuthSessionService.detach_token()
            return False

        role = normalize_role(payload.get("role"))
        user_id = payload.get("uid")
        patient_portal_id = payload.get("pid")

        if role == "patient":
            patient = None
            if patient_portal_id:
                patient = db.query(Patient).filter(Patient.id == patient_portal_id).first()
            if not patient:
                AuthSessionService.detach_token()
                return False
            st.session_state.logged_in = True
            st.session_state.user_data = None
            st.session_state.user_role = "patient"
            st.session_state.patient_portal_id = patient.id
            _set_nav_defaults(role)
            return True

        user = None
        if user_id:
            user = db.query(User).filter(User.id == user_id).first()
        if not user or not user.is_active:
            AuthSessionService.detach_token()
            return False

        db_role = normalize_role(user.role)
        if db_role != role:
            AuthSessionService.detach_token()
            return False

        user_data = AuthService.build_user_payload(db, user)
        if normalize_role(user_data.get("role")) != role:
            AuthSessionService.detach_token()
            return False

        st.session_state.logged_in = True
        st.session_state.user_role = user_data["role"]
        st.session_state.user_data = user_data
        _set_nav_defaults(role)
        return True

    @staticmethod
    def revalidate_session(db) -> bool:
        """Re-validate an already-logged-in session against the database.

        Runs on every script rerun. Catches stale/partially-reset state,
        deactivated staff accounts, changed roles, and the patient portal
        record disappearing. Force-logs-out only when the account is genuinely
        invalid -- normal reruns and refreshes are untouched.
        """
        if not st.session_state.get("logged_in"):
            return False

        role = normalize_role(st.session_state.get("user_role"))

        if role == "patient":
            patient_portal_id = st.session_state.get("patient_portal_id")
            patient = None
            if patient_portal_id:
                patient = db.query(Patient).filter(Patient.id == patient_portal_id).first()
            if not patient:
                AuthSessionService.logout()
                return False
            return True

        user_data = st.session_state.get("user_data") or {}
        user_id = user_data.get("user_id")
        user = None
        if user_id:
            user = db.query(User).filter(User.id == user_id).first()
        if not user or not user.is_active:
            AuthSessionService.logout()
            return False

        db_role = normalize_role(user.role)
        if db_role != role:
            AuthSessionService.logout()
            return False
        return True

    @staticmethod
    def logout() -> None:
        """Explicitly log out: clear auth + contextual state and drop the URL token."""
        _CLEARABLE_KEYS = (
            "logged_in",
            "user_role",
            "user_data",
            "patient_portal_id",
            "selected_patient_id",
            "selected_visit_id",
            "generated_token_id",
            "selected_token_id",
            "verified_referral_id",
            "quick_fill_phone",
            "quick_fill_code",
            "patient_workflow_stage",
        )
        for key in _CLEARABLE_KEYS:
            st.session_state.pop(key, None)
        AuthSessionService.detach_token()


def _set_nav_defaults(role: str) -> None:
    """Seed role-appropriate navigation defaults without clobbering existing state."""
    if normalize_role(role) == "receptionist":
        if "receptionist_nav" not in st.session_state:
            st.session_state.receptionist_nav = "Dashboard"
    elif normalize_role(role) == "doctor":
        if "doctor_nav" not in st.session_state:
            st.session_state.doctor_nav = "My Queue"


def _b64encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _b64decode(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)


def _signature(payload_b64: str) -> str:
    return hmac.new(_process_secret(), payload_b64.encode("ascii"),
                    hashlib.sha256).hexdigest()