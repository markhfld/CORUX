"""Step 2 — PII firewall (verify & minimize).

The input arrives already de-identified upstream (pseudonymous `patient_id`,
`age_years`, `sex` — no name/dob). This step's job is therefore minimization, not
stripping: it derives a stable `patient_key` from `patient_id` so panels link
across submissions, and carries only the clinical context the agents need
(sex, age, de-identified notes). The `patient_id` itself is never put into LLM
prompts — only the hashed key is used, and only as a local storage key.
"""

from __future__ import annotations

import hashlib
from typing import Optional

from . import config
from .schemas import DeidentifiedPatient, PatientLabResults


def patient_key(patient_id: Optional[str]) -> str:
    """Deterministic, salted hash of the pseudonymous id. Same id -> same key,
    without using the raw id as a filename or sending it to the model."""
    raw = (patient_id or "").strip()
    digest = hashlib.sha256((config.PATIENT_KEY_SALT + "|" + raw).encode()).hexdigest()
    return digest[:16]


def deidentify(doc: PatientLabResults) -> DeidentifiedPatient:
    p = doc.patient
    return DeidentifiedPatient(
        patient_key=patient_key(p.patient_id),
        sex=(p.sex or "").strip() or None,
        age_years=p.age_years,
        notes=(p.notes or "").strip() or None,
    )
