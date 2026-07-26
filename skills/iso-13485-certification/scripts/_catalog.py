#!/usr/bin/env python3
"""Public-process labels used by the local evidence checks.

The labels are workflow topics, not ISO clause text or a substitute for an
authorized copy of any standard.
"""

from __future__ import annotations

PROCESS_DOMAINS = (
    "scope-and-roles",
    "document-and-record-control",
    "risk-management",
    "design-and-development",
    "supplier-controls",
    "production-and-service",
    "process-and-software-validation",
    "identification-and-traceability",
    "complaints-and-feedback",
    "postmarket-and-vigilance",
    "nonconformity-and-capa",
    "internal-audit",
    "management-review",
    "training-and-competence",
    "change-control",
)

QMSR_TRANSITION_ITEMS = (
    "qmsr-source-basis",
    "applicability-owner",
    "fda-supplemental-provisions",
    "legacy-qsr-reference-disposition",
    "pre-effective-date-record-review",
    "inspection-accessible-records",
    "inspection-process-training",
    "qsit-retirement",
    "complaint-and-servicing-records",
    "labeling-and-packaging-controls",
    "software-validation-impact",
    "supplier-and-outsourced-process-controls",
    "certificate-claims-review",
    "change-control-approval",
)

TRACEABILITY_LINKS = (
    "intended_use",
    "hazard_or_signal",
    "risk_evaluation",
    "risk_control",
    "design_input",
    "design_output",
    "verification",
    "validation",
    "production_control",
    "postmarket_source",
)
