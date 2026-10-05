# Journal_new — Sionna RT baseline

This repository contains the curated, source-only Sionna RT baseline for the RUP-CHO high-speed-rail journal project. It is the Phase 0 reproducibility package: code, configuration, provenance contracts, issue register, and compact baseline evidence.

Large generated scenes, meshes, ray-tracing CSV files, images, logs, caches, and local paths are deliberately excluded. Their identity is tracked with manifests and SHA-256 checksums instead.

## Repository map

- `phase1_pipeline/`: reusable Sionna RT, Blender scene preparation, post-processing, analysis, and temporal-resolution experiment source.
- `docs/phase0/`: Phase 0 audit and reproducibility records.
- `docs/baseline_evidence/`: compact evidence retained from the existing baseline.
- `scripts/`: repository and baseline-integrity checks.

## Quick verification

```powershell
python scripts/validate_repository.py
python scripts/verify_baseline_integrity.py --source-root "<path-to-original-phase1_pipeline>"
```

The first command is self-contained. The second verifies the original large baseline assets without committing them.

## Reproduction boundary

Phase 0 locks the current implementation and identifies what can be reproduced. It does **not** yet establish publication-grade validity for mobility/handover claims. In particular, 25 m spatial sampling at 350 km/h corresponds to about 257 ms, and idealized RRC/HOF/RLF behavior remains a Phase 1 blocker.

See `docs/phase0/PHASE0_STATUS.md` for the exact completion state and gates.
