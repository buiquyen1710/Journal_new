# Phase 0 status — baseline audit and scope lock

Audit date: 2026-10-05

| Plan item | Status | Evidence / gate |
|---|---|---|
| P0.0 Existing baseline asset set | Complete | `ASSET_INVENTORY.md`; six native-350 km/h scenes inventoried. |
| P0.1 Journal branch and version lock | Complete locally | `VERSION_MANIFEST.json`, Git commit and tag `phase0-sionnart-baseline-v0.1.0`. Remote push depends on GitHub connectivity. |
| P0.2 Reproduce controlled VietnamRT-A baseline | Partial | Existing Giai Phong evidence retained. A clean-checkout full RT rerun and numerical regression report are still required. |
| P0.3 Reproduce Long Bien / Hai Van / Hai Duong | Partial | Long Bien and Hai Van source assets have a create-once SHA-256 lock; Hai Duong and one-command clean reruns remain open. |
| P0.4 Technical issue tracker | Complete | `TECHNICAL_ISSUES.md` records ten issues, evidence, risk, owner role, and acceptance test. |
| P0.5 Run manifest and metadata | Complete as contract | `RUN_MANIFEST_SCHEMA.json`; adoption by all future runs is mandatory. |
| P0.6 M0 supervisor meeting | Ready, not complete | `M0_MEETING.md`; supervisor decision and Phase 1 scope freeze require a real meeting. |

## Quantitative conclusion

- Curated package: source/config/documentation only; heavy generated assets are excluded.
- Existing scenario foundation: 6 Vietnamese railway environments, 1,409 receiver samples, and 40 gNB placements in the reported native-350 km/h baseline.
- Reproducibility evidence: two key scenes (Long Bien and Hai Van) have file-level SHA-256 locks; four scenes, including Hai Duong and the controlled Giai Phong case, still need equivalent locked regression packages.
- Phase 0 is therefore **documentation/code-lock complete, experimental reproduction incomplete**. Publication experiments must not begin until the P0.2/P0.3 rerun gates pass.

## Recommended next action

Run one small Giai Phong smoke/regression case from a clean environment, generate a schema-compliant manifest, and compare receiver count, trajectory length, path gain/SINR proxy, Doppler range, outage proxy, and runtime against the retained baseline. Only then scale to Long Bien, Hai Van, and Hai Duong.
