"""Workflow navigation definitions for MED-SETU.

Single source of truth for the two primary staff workflows.  The sidebar
sections themselves are unchanged; these constants only drive the on-screen
workflow trail so each step is explicit:

    Doctor:        My Queue -> Patient Case -> Prescription & Notes -> Referral
    Receptionist:  Dashboard -> Patients -> Visit / Token -> Queue -> Referrals
"""

DOCTOR_WORKFLOW = [
    ("My Queue", "queue"),
    ("Patient Case", "case"),
    ("Prescription & Notes", "rx"),
    ("Referral", "referral"),
]

RECEPTIONIST_WORKFLOW = [
    ("Dashboard", "dashboard"),
    ("Patients", "patients"),
    ("Visit / Token", "visit_token"),
    ("Queue", "queue"),
    ("Referrals", "referrals"),
]

WORKFLOWS = {
    "doctor": DOCTOR_WORKFLOW,
    "receptionist": RECEPTIONIST_WORKFLOW,
}


def workflow_index(workflow, step_key):
    """Return the index of a step key in the workflow, or None."""
    for i, (_label, key) in enumerate(workflow):
        if key == step_key:
            return i
    return None


def workflow_trail(workflow, step_key):
    """Return the labels for the workflow path up to and including step_key."""
    idx = workflow_index(workflow, step_key)
    if idx is None:
        return []
    return [label for label, _ in workflow[: idx + 1]]


def trail_text(workflow, step_key):
    """Return a display string for the step's workflow path."""
    return " → ".join(workflow_trail(workflow, step_key))


def trail_text_with_current(workflow, step_key):
    """Return the workflow path string with the current step wrapped in **bold**."""
    idx = workflow_index(workflow, step_key)
    if idx is None:
        return ""
    parts = [
        label if i != idx else f"**{label}**"
        for i, (label, _) in enumerate(workflow[: idx + 1])
    ]
    return " → ".join(parts)