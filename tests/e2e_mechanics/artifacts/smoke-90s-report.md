# E2E Mechanics Report

- **success:** True
- **seed:** `20260927`
- **duration:** 93.6s (target 90s)
- **started:** 2026-09-27T19:27:47Z
- **finished:** 2026-09-27T19:29:21Z

## Transport
- exports A→B: 3
- exports B→A: 27
- imports A→B ok: 3
- imports B→A ok: 27
- corrupted-package rejections: 1

## Conversion (EPIC-018)
- sessions: 35
- rows saved: 105
- rows skipped: 35
- FIO collisions observed (no auto-link): 35

## Requires attention (EPIC-007)
- raised: 20
- cleared: 20

## Other
- employees created: 237
- status assignments: 53
- restore verified: True

## Notes
- initial backup A=personnel-20260915T090000Z.db B=personnel-20260915T090000Z.db
- corrupt reject: TransportPackageMalformedError: transport package: truncated field payload (no product rejection audit row; assert unchanged snapshots)
- A restore matches post-bootstrap snapshot
- B restore matches post-bootstrap snapshot
- ticks=53
