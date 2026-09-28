# Import / sync error codes (ADR-0013)

Stable codes carried as `(ImportErrorCode, raw_message)` in
`ValidationResult.reject_reasons` / `confirmation_reasons` and
`EmployeePlan.validation_errors`. UI shows `CODE: raw_message`. Longer
explanations live only in this document.

| Code | Meaning | Example |
| --- | --- | --- |
| IMP-001 | Package generation/sequence is stale or already consumed | `stale or out-of-sequence package` |
| IMP-002 | Applying the directory plan would leave an existing employee org-invalid | `employee 42 (Петров И.С.) would become invalid` |
| IMP-003 | Directory plan rejected with no broken-employee detail (fallback) | `directory plan rejected` |
| IMP-004 | Duplicate `external_id` among employee rows in the same package | `duplicate external_id in package: …` |
| IMP-005 | Package assigns an archived branch | `archived branch cannot be assigned ('…')` |
| IMP-006 | Package assigns an archived position | `archived position cannot be assigned ('…')` |
| IMP-007 | Package assigns an archived department | `archived department cannot be assigned ('…')` |
| IMP-008 | Package assigns an archived division | `archived division cannot be assigned ('…')` |
| IMP-009 | Branch `external_id` cannot be resolved (DB or projected plan) | `cannot resolve branch external_id '…'` |
| IMP-010 | Position `external_id` cannot be resolved | `cannot resolve position external_id '…'` |
| IMP-011 | Department `external_id` cannot be resolved | `cannot resolve department external_id '…'` |
| IMP-012 | Division `external_id` cannot be resolved | `cannot resolve division external_id '…'` |
| IMP-013 | Department belongs to a different branch than the employee row | `department external_id '…' belongs to another branch` |
| IMP-014 | Division belongs to a different branch than the employee row | `division external_id '…' belongs to another branch` |
| IMP-015 | Division is not under the resolved department | `division external_id '…' is not under the resolved department` |
| IMP-016 | Employee card / org invariants failed (`EmployeeError` / validation) | message from `EmployeeValidationError` / `EmployeeError` |
| IMP-017 | Hard employee match conflict (`external_id` found, ФИО mismatch) | `conflict: external_id=… name='…'` |
| IMP-018 | Confirmable LOW match (no `external_id`; one FIO+org candidate) | `low: external_id=… name='…'` |
| IMP-019 | Confirmable AMBIGUOUS match (no `external_id`; several candidates) | `ambiguous: external_id=… name='…'` |
