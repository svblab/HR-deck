# E2E Mechanics Report

- **success:** True
- **seed:** `20260927`
- **duration:** 1446.3s (target 1440s)
- **started:** 2026-09-27T20:21:43Z
- **finished:** 2026-09-27T20:45:50Z

## Transport
- exports A→B: 253
- exports B→A: 252
- imports A→B ok: 253
- imports B→A ok: 252
- corrupted-package rejections: 1

## Conversion (EPIC-018)
- sessions: 261
- rows saved: 768
- rows skipped: 261
- FIO collisions observed (no auto-link): 261

## Requires attention (EPIC-007)
- raised: 163
- cleared: 163

## Other
- employees created: 1939
- status assignments: 501
- restore verified: True

## Notes
- initial backup A=personnel-20260915T090000Z.db B=personnel-20260915T090000Z.db
- corrupt reject: TransportPackageMalformedError: transport package: truncated field payload (no product rejection audit row; assert unchanged snapshots)
- A restore matches post-bootstrap snapshot
- B restore matches post-bootstrap snapshot
- ticks=501
