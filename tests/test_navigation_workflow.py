"""Phase 1 navigation refinement tests for MED-SETU.

Covers:
- Pure unit tests for the canonical workflow step definitions (doctor &
  receptionist) and trail helpers.
- AppTest tests that the selected patient/visit/doctor context survives
  navigation between workflow steps, that the workflow trail renders, and that
  explicit logout terminates the session.

The Streamlit AppTest cases reuse the primary database (read queries only),
exactly like `test_phase1_stability.py` already does.
"""
import os
import pytest

from services.navigation import (
    DOCTOR_WORKFLOW,
    RECEPTIONIST_WORKFLOW,
    WORKFLOWS,
    workflow_index,
    workflow_trail,
    trail_text,
    trail_text_with_current,
)

APP_PATH = os.path.join(os.path.dirname(__file__), "..", "app.py")


# ──────────────────────────────────────────────────────
# 1. Workflow definition units (no Streamlit / no DB)
# ──────────────────────────────────────────────────────

class TestWorkflowDefinitions:
    def test_doctor_workflow_order(self):
        assert [key for _label, key in DOCTOR_WORKFLOW] == [
            "queue", "case", "rx", "referral"
        ]

    def test_doctor_workflow_labels(self):
        assert [label for label, _ in DOCTOR_WORKFLOW] == [
            "My Queue", "Patient Case", "Prescription & Notes", "Referral"
        ]

    def test_receptionist_workflow_order(self):
        assert [key for _label, key in RECEPTIONIST_WORKFLOW] == [
            "dashboard", "patients", "visit_token", "queue", "referrals"
        ]

    def test_receptionist_workflow_labels(self):
        assert [label for label, _ in RECEPTIONIST_WORKFLOW] == [
            "Dashboard", "Patients", "Visit / Token", "Queue", "Referrals"
        ]

    def test_workflows_register_both_roles(self):
        assert WORKFLOWS["doctor"] == DOCTOR_WORKFLOW
        assert WORKFLOWS["receptionist"] == RECEPTIONIST_WORKFLOW

    def test_workflow_index(self):
        assert workflow_index(DOCTOR_WORKFLOW, "rx") == 2
        assert workflow_index(DOCTOR_WORKFLOW, "queue") == 0
        assert workflow_index(DOCTOR_WORKFLOW, "missing") is None

    def test_workflow_trail_is_prefix(self):
        assert workflow_trail(DOCTOR_WORKFLOW, "case") == [
            "My Queue", "Patient Case"
        ]
        assert workflow_trail(DOCTOR_WORKFLOW, "referral") == [
            "My Queue", "Patient Case", "Prescription & Notes", "Referral"
        ]

    def test_trail_text(self):
        assert trail_text(RECEPTIONIST_WORKFLOW, "visit_token") == (
            "Dashboard → Patients → Visit / Token"
        )

    def test_trail_text_with_current_bolds_only_current(self):
        trail = trail_text_with_current(RECEPTIONIST_WORKFLOW, "visit_token")
        assert "**Visit / Token**" in trail
        assert "**Dashboard**" not in trail
        assert "**Patients**" not in trail

    def test_trail_text_with_current_first_step(self):
        trail = trail_text_with_current(DOCTOR_WORKFLOW, "queue")
        assert trail == "**My Queue**"


# ──────────────────────────────────────────────────────
# 2. AppTest: doctor & receptionist workflow navigation
# ──────────────────────────────────────────────────────

class _BaseAppTest:
    @staticmethod
    def _ss(at, key, default=None):
        return at.session_state[key] if key in at.session_state else default

    @staticmethod
    def _button_by_label(at, substring):
        matches = [b for b in at.button if substring.lower() in b.label.lower()]
        assert matches, (
            f"No button found containing {substring!r}; "
            f"labels={[b.label for b in at.button]}"
        )
        return matches[0]

    @staticmethod
    def _has_trail(at):
        return any("🧭 Workflow" in c.value for c in at.caption)

    @staticmethod
    def _no_exceptions(at):
        assert len(at.exception) == 0, (
            f"App raised exceptions: {[str(e.value) for e in at.exception]}"
        )


def _real_drkhan_token_id():
    """Read-only lookup of a Dr. Khan token in the primary database."""
    from database.db import get_session
    from database.models import Token, Doctor, User
    db = get_session()
    try:
        doc = db.query(Doctor).join(User).filter(User.username == "drkhan").first()
        if not doc:
            return None
        tok = db.query(Token).filter(Token.doctor_id == doc.id).order_by(Token.id.desc()).first()
        return tok.id if tok else None
    finally:
        db.close()


def _real_patient_id():
    """Read-only lookup of an arbitrary patient in the primary database."""
    from database.db import get_session
    from database.models import Patient
    db = get_session()
    try:
        p = db.query(Patient).order_by(Patient.id.desc()).first()
        return p.id if p else None
    finally:
        db.close()


def _real_token_id():
    """Read-only lookup of an arbitrary token in the primary database."""
    from database.db import get_session
    from database.models import Token
    db = get_session()
    try:
        tok = db.query(Token).order_by(Token.id.desc()).first()
        return tok.id if tok else None
    finally:
        db.close()


class TestDoctorNavigation(_BaseAppTest):
    def test_doctor_workflow_steps_preserve_patient_context(self):
        token_id = _real_drkhan_token_id()
        if token_id is None:
            pytest.skip("No Dr. Khan token present in the primary database")
        from streamlit.testing.v1 import AppTest

        at = AppTest.from_file(APP_PATH, default_timeout=60)
        at.run()
        at.text_input[0].set_value("drkhan")
        at.text_input[1].set_value("password123")
        self._button_by_label(at, "Sign In").click()
        at.run()

        assert self._ss(at, "logged_in") is True
        assert self._ss(at, "user_role") == "doctor"
        assert self._ss(at, "doctor_nav") == "My Queue"
        assert self._has_trail(at)
        self._no_exceptions(at)

        # My Queue -> Patient Case (context is the selected token)
        at.session_state["doctor_nav"] = "Patient Case"
        at.session_state["selected_token_id"] = token_id
        at.run()
        assert self._ss(at, "selected_token_id") == token_id
        assert self._has_trail(at)
        self._no_exceptions(at)

        # Patient Case -> Prescription & Notes (context preserved)
        at.session_state["doctor_nav"] = "Prescription & Notes"
        at.run()
        assert self._ss(at, "selected_token_id") == token_id
        assert self._has_trail(at)
        self._no_exceptions(at)

        # Prescription & Notes -> Referral (context preserved)
        at.session_state["doctor_nav"] = "Referrals"
        at.run()
        assert self._ss(at, "selected_token_id") == token_id
        assert self._has_trail(at)
        self._no_exceptions(at)

        # Back to My Queue (context preserved, queue renders again)
        at.session_state["doctor_nav"] = "My Queue"
        at.run()
        assert self._ss(at, "selected_token_id") == token_id
        assert self._has_trail(at)
        self._no_exceptions(at)

    def test_doctor_logout_terminates_session_and_context(self):
        from streamlit.testing.v1 import AppTest
        from services.session_service import PARAM_KEY

        at = AppTest.from_file(APP_PATH, default_timeout=60)
        at.run()
        at.text_input[0].set_value("drkhan")
        at.text_input[1].set_value("password123")
        self._button_by_label(at, "Sign In").click()
        at.run()
        assert self._ss(at, "logged_in") is True

        at.session_state["doctor_nav"] = "Patient Case"
        at.session_state["selected_token_id"] = 999999
        at.run()

        at.button(key="doc_logout_btn").click()
        at.run()
        assert self._ss(at, "logged_in") is False
        assert PARAM_KEY not in at.query_params
        assert self._ss(at, "selected_token_id") is None


class TestReceptionistNavigation(_BaseAppTest):
    def test_receptionist_workflow_state_preserved_across_sections(self):
        patient_id = _real_patient_id()
        if patient_id is None:
            pytest.skip("No patient present in the primary database")
        from streamlit.testing.v1 import AppTest

        at = AppTest.from_file(APP_PATH, default_timeout=60)
        at.run()
        at.text_input[0].set_value("receptionist")
        at.text_input[1].set_value("password123")
        self._button_by_label(at, "Sign In").click()
        at.run()

        assert self._ss(at, "logged_in") is True
        assert self._ss(at, "receptionist_nav") == "Dashboard"
        assert self._has_trail(at)
        self._no_exceptions(at)

        # Dashboard -> Patients -> Visit / Token stage
        at.session_state["receptionist_nav"] = "Patients"
        at.session_state["patient_workflow_stage"] = "create_visit"
        at.session_state["selected_patient_id"] = patient_id
        at.run()
        assert self._ss(at, "selected_patient_id") == patient_id
        assert self._has_trail(at)
        self._no_exceptions(at)

        # Hop to Queue and back: selected patient context must survive
        at.session_state["receptionist_nav"] = "Queue"
        at.run()
        assert self._ss(at, "selected_patient_id") == patient_id
        self._no_exceptions(at)

        at.session_state["receptionist_nav"] = "Patients"
        at.run()
        assert self._ss(at, "selected_patient_id") == patient_id
        assert self._ss(at, "patient_workflow_stage") == "create_visit"
        assert self._has_trail(at)
        self._no_exceptions(at)

        # Hop to Referrals and back: context preserved, trail present
        at.session_state["receptionist_nav"] = "Referrals"
        at.run()
        assert self._ss(at, "selected_patient_id") == patient_id
        self._no_exceptions(at)

        at.session_state["receptionist_nav"] = "Patients"
        at.run()
        assert self._ss(at, "selected_patient_id") == patient_id
        assert self._ss(at, "patient_workflow_stage") == "create_visit"
        self._no_exceptions(at)

    def test_token_confirmation_back_to_patient_search(self):
        token_id = _real_token_id()
        if token_id is None:
            pytest.skip("No token present in the primary database")
        from streamlit.testing.v1 import AppTest
        from database.db import get_session
        from database.models import Token

        db = get_session()
        try:
            tok = db.query(Token).filter(Token.id == token_id).first()
            patient_id = tok.visit.patient_id
            visit_id = tok.visit_id
        finally:
            db.close()

        at = AppTest.from_file(APP_PATH, default_timeout=60)
        at.run()
        at.text_input[0].set_value("receptionist")
        at.text_input[1].set_value("password123")
        self._button_by_label(at, "Sign In").click()
        at.run()

        # Simulate just-generated token confirmation card
        at.session_state["receptionist_nav"] = "Patients"
        at.session_state["generated_token_id"] = token_id
        at.session_state["selected_patient_id"] = patient_id
        at.session_state["selected_visit_id"] = visit_id
        at.session_state["patient_workflow_stage"] = "create_visit"
        at.run()
        assert self._ss(at, "generated_token_id") == token_id
        self._no_exceptions(at)

        # Back to Patient Search clears the one-shot confirmation and returns
        # the receptionist to the search screen without losing the workflow.
        self._button_by_label(at, "Back to Patient Search").click()
        at.run()
        assert self._ss(at, "generated_token_id") is None
        assert self._ss(at, "patient_workflow_stage") == "search"
        assert self._ss(at, "receptionist_nav") == "Patients"
        assert self._no_exceptions(at) is None

    def test_receptionist_logout_terminates_session(self):
        from streamlit.testing.v1 import AppTest
        from services.session_service import PARAM_KEY

        at = AppTest.from_file(APP_PATH, default_timeout=60)
        at.run()
        at.text_input[0].set_value("receptionist")
        at.text_input[1].set_value("password123")
        self._button_by_label(at, "Sign In").click()
        at.run()
        assert self._ss(at, "logged_in") is True

        at.button(key="rec_logout_btn").click()
        at.run()
        assert self._ss(at, "logged_in") is False
        assert PARAM_KEY not in at.query_params