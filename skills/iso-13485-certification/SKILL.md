---
name: iso-13485-certification
description: Prepare and structurally review ISO 13485 QMS scope, controlled documentation, and local evidence manifests. Use for ISO 13485 certification-readiness documentation or for separating related FDA QMSR, MDSAP, and EU MDR/IVDR evidence boundaries; not for legal applicability, compliance, or certification decisions.
license: MIT
compatibility: Python 3.11+; bundled CLIs use only the standard library and bounded local JSON/Markdown files, with no network access or credentials.
allowed-tools: Read, Write, Bash, Glob
metadata:
  version: "1.1"
  skill-author: K-Dense Inc.
---

# ISO 13485 QMS Evidence Preparation

## Purpose

Use this skill to organize QMS scope, controlled documents, implementation records,
traceability, and readiness evidence for substantive review. It summarizes process
workflows and provides deterministic local checks; it does not contain ISO clause
text or perform an audit.

## Non-negotiable boundary

This skill cannot:

- certify a QMS, issue or validate a certificate, or promise an audit result;
- determine legal/regulatory applicability, device classification, reportability,
  conformity route, product authorization, market access, or compliance;
- replace authorized management, the management representative, RA/QA, legal
  counsel, regulatory/competent authorities, a notified body, an MDSAP Auditing
  Organization, an accreditation body, or a certification body; or
- infer implementation, conformity, compliance, or readiness from a template,
  checklist, filename, keyword, document count, percentage, or script result.

Always label outputs **draft evidence-preparation material for authorized human
review**. Preserve unresolved decisions as blockers.

## ISO copyright

ISO standards are copyrighted. Obtain ISO 13485 and related standards from
[ISO](https://www.iso.org/standard/59752.html), an ISO national member, or another
authorized source. Do not retrieve, paste, reproduce, or generate clause text.
Summarize the organization's process and cite the controlled authorized copy.
See [ISO copyright](https://www.iso.org/copyright.html).

## Current baseline (researched 2026-07-23)

- **ISO 13485:** ISO 13485:2016, Edition 3, was confirmed after its 2025
  systematic review and remains current.
- **European amendment:** EN ISO 13485:2016/A11:2021 is a European EN amendment,
  not an ISO international “Amendment 1:2021.” Track AC:2018/A11:2021 only where
  the European source basis applies.
- **FDA QMSR:** effective and enforced since **2026-02-02**. Current Part 820 is
  titled *Quality Management System Regulation*. FDA stopped using QSIT and uses
  Compliance Program **7382.850**. Treat this as implemented, not a future
  transition.
- **MDSAP:** current official Audit Approach is **MDSAP AU P0002.010**, version
  date **2026-02-02**.
- **EU:** use current consolidated MDR/IVDR texts, current OJEU harmonised-standard
  decisions, current MDCG guidance, and the product-specific conformity route.
- **Risk management:** ISO 14971:2019, Edition 3, was confirmed in 2025. For
  European work, distinguish EN ISO 14971:2019/A11:2021.

Read `references/source-ledger.md` before making a time-sensitive statement.

## Keep five lanes separate

### 1. ISO 13485 certification

A certification body evaluates the defined management-system scope against the
authorized standard and certification scheme. A certificate is limited to its stated
organization, sites, activities, technical/product scope, edition, and validity.

### 2. FDA QMSR inspection/compliance

FDA assesses applicable FDA requirements. ISO certification does not exempt a
manufacturer from inspection, and FDA does not issue ISO 13485 certificates. Use the
current eCFR and FDA supplemental provisions; do not use the former QSR section
structure as a current requirements map.

### 3. MDSAP audit

An MDSAP-recognized Auditing Organization conducts a regulatory audit using the
current MDSAP approach and applicable participating-jurisdiction requirements. An
ISO-only audit is not MDSAP; an FDA inspection does not follow the MDSAP audit plan.

### 4. EU MDR/IVDR conformity assessment

EU conformity assessment includes product, technical-documentation, postmarket,
vigilance, economic-operator, and notified-body requirements beyond generic QMS
documentation. Verify a notified body's current legislation/task/designation-code
scope in NANDO. ISO certification/accreditation alone is not notified-body
designation or EU product conformity.

### 5. Product- and jurisdiction-specific controls

Classification, intended purpose, claims, software/cybersecurity, clinical or
performance evidence, biocompatibility, electrical safety, sterilization, UDI,
registration, reporting, and other controls require separate authorized analysis.

## Core workflow

### Step 1: Define purpose and authorized owners

State whether the work supports internal QMS development, ISO certification
preparation, FDA inspection preparation, MDSAP, EU conformity assessment, or a
specific combination. Name the management representative, RA/QA owner, legal/
applicability owner, process owners, approvers, and escalation route.

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 scripts/validate_scope_intake.py \
  assets/templates/scope-intake-template.json
```

The distributed template intentionally fails closed. Copy it outside the skill and
complete it with controlled organizational evidence.

### Step 2: Freeze source/version evidence

For every standard, regulation, guidance, audit model, and product source, record:

- publisher, official title, edition/version/date, and authorized location;
- access and currency-review dates;
- scope/applicability owner;
- impact assessment, status, evidence, and approval.

Do not use search snippets as controlled requirements. Do not silently update an
incorporated edition when a publisher releases a new edition.

### Step 3: Inventory controlled documents and records

Do not count named procedures or scan keywords. Build an explicit register linking
documents, records, source versions, owners, approvals, effective dates, retention
bases, training, and change records.

```bash
PYTHONDONTWRITEBYTECODE=1 python3 scripts/audit_document_records.py \
  assets/templates/document-register-template.json
```

Read `references/mandatory-documents.md` for the evidence architecture.

### Step 4: Review process implementation

Assess controlled procedures **and sampled records** for:

- scope, governance, roles, and management authority;
- document/record/external-source control;
- risk management;
- design/development, transfer, and changes;
- suppliers, purchasing, and outsourced processes;
- production/service, infrastructure, environment, acceptance, and release;
- process, equipment, test-method, and software validation;
- identification, traceability, preservation, installation, and service;
- feedback, complaints, postmarket surveillance, and vigilance;
- nonconformity, CAPA, and effectiveness;
- internal audit and management review;
- competence/training; and
- integrated change control.

Each item needs owner, status, evidence IDs, source/version, approval, and open-gap
links. Read `references/iso-13485-requirements.md`.

### Step 5: Build traceability and focused checks

Risk/design/production/postmarket:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 scripts/check_traceability.py \
  assets/templates/traceability-matrix-template.json
```

CAPA/effectiveness:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 scripts/check_capa.py \
  assets/templates/capa-record-template.json
```

Supplier controls:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 scripts/check_supplier_controls.py \
  assets/templates/supplier-controls-template.json
```

Pending or ineffective CAPA effectiveness evidence blocks closure. Critical supplier
controls stay blocked until risk-based controls and approvals are evidenced.

### Step 6: Address current QMSR evidence separately

```bash
PYTHONDONTWRITEBYTECODE=1 python3 scripts/check_qmsr_transition.py \
  assets/templates/qmsr-transition-template.json
```

Review current Part 820/FDA source basis, supplemental provisions, obsolete
QSR/QSIT references, pre-effective-date records, inspection-accessible management/
quality/supplier-audit records, current inspection-process training, complaint and
servicing records, labeling/packaging controls, supplier/software/change evidence,
and prohibited certificate-equivalence claims.

Do not build an old-820-to-ISO clause map as the current control framework.

### Step 7: Assemble a bounded readiness manifest

Copy the evidence template outside the skill. Use relative paths to local `.json`,
`.md`, or `.markdown` evidence only.

```bash
PYTHONDONTWRITEBYTECODE=1 python3 scripts/validate_evidence_manifest.py \
  /path/to/evidence-manifest.json \
  --base-dir /path/to/controlled-export \
  --verify-files \
  --output /path/to/manifest-report.json
```

Then generate a domain-level gap view:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 scripts/gap_analyzer.py \
  /path/to/evidence-manifest.json \
  --base-dir /path/to/controlled-export \
  --verify-files \
  --output /path/to/gap-report.json
```

The analyzer uses explicit manifest labels. It does not infer evidence from filenames,
keywords, or proprietary standard text and does not calculate a compliance score.

### Step 8: Human review and controlled handoff

Present:

- declared scope, assurance lanes, and unresolved applicability decisions;
- exact source/version baseline;
- evidence sampled and limitations;
- structural findings grouped by process and risk;
- actions/change/CAPA owners and dates;
- approval state; and
- the authorized party responsible for the next decision.

Never title the result “certificate,” “compliance report,” “audit pass,” or “ready for
inspection.” A suitable title is **Draft QMS evidence review for authorized human
assessment**.

## CLI behavior and safety

All bundled CLIs:

- use the Python standard library only;
- perform no network requests;
- accept bounded local JSON; optional evidence verification accepts only bounded
  local JSON/Markdown;
- reject symbolic-link inputs, duplicate JSON keys, non-finite numbers, excessive
  size/nesting/items, and unsafe evidence paths;
- use no dynamic evaluation, executable deserialization, pickle, or shell execution;
- refuse to overwrite reports unless `--force` is explicit; and
- produce deterministic sorted JSON.

Treat the manifest itself as a controlled organizational record. An optional SHA-256
comparison detects a local file mismatch only; it does not establish provenance,
authenticity, adequacy, or trust in a user-supplied manifest. Values in JSON
`local_path` and `evidence.location` fields refer to the user's controlled export,
not to bundled skill resources; unresolved placeholders must never be opened.

Exit codes:

- `0`: no structural finding for the supplied fields; **not a compliance result**;
- `1`: structural/evidence gaps found;
- `2`: invalid or unsafe input/output.

Run `python3 scripts/<name>.py --help` for each interface.

## Templates

- `assets/templates/quality-manual-template.md`
- `assets/templates/procedures/CAPA-procedure-template.md`
- `assets/templates/procedures/document-control-procedure-template.md`
- `assets/templates/scope-intake-template.json`
- `assets/templates/document-register-template.json`
- `assets/templates/capa-record-template.json`
- `assets/templates/traceability-matrix-template.json`
- `assets/templates/qmsr-transition-template.json`
- `assets/templates/evidence-manifest-template.json`
- `assets/templates/supplier-controls-template.json`

Every template is deliberately `draft`/`pending`, uses placeholders, and includes
owner/status/evidence/approval fields. Copy and control it; never edit a distributed
template into a purported approved record.

## References

- `references/iso-13485-requirements.md` — process/evidence framework and assurance boundaries
- `references/mandatory-documents.md` — documentation and record architecture
- `references/gap-analysis-checklist.md` — fail-closed evidence review questions
- `references/quality-manual-guide.md` — controlled manual development
- `references/source-ledger.md` — dated authoritative official-source baseline
