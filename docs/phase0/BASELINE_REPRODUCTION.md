# Baseline reproduction protocol

## Gate A — repository and environment

1. Check out the Phase 0 tag.
2. Create an isolated environment using `requirements-core.txt` plus the documented Sionna source installation.
3. Run `python scripts/validate_repository.py`.
4. Record missing Blender/Sionna version metadata before producing any result.

## Gate B — controlled Giai Phong regression

Run the smallest representative configuration first. Record a run manifest and compare: scene/config hashes, route length, RX/gNB count, native timestamps, path-gain/SINR proxy distribution, Doppler extrema, outage proxy, missing/fallback samples, and runtime. The run passes only if differences are explained and thresholded before looking at the journal result.

## Gate C — multi-scene regression

Repeat for Long Bien, Hai Van, and Hai Duong using one launcher and immutable inputs. Long Bien/Hai Van original assets must first pass `verify_baseline_integrity.py`. Create equivalent locks for Giai Phong and Hai Duong.

## Gate D — Phase 1 release

Phase 1 may begin only after Gates A–C pass, M0 decisions are recorded, and the scope explicitly states that T1 (temporal resolution) and T3 (realistic RRC/HOF/RLF) are mandatory validity work—not optional enhancements.
