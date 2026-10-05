# RT spatial-resolution sensitivity experiment

This isolated experiment tests whether the principal joint HOM–TTT Event-A3 conclusions remain stable when Sionna RT receiver sampling is refined from the legacy 25-m grid to grids no coarser than 5 m and 2 m.

The source baseline directories are never overwritten. Fine cases reuse the exact baseline Mitsuba scene, meshes and gNB placements, then insert receiver samples on the same baseline trajectory polyline.

## Current status

- Repository audit: complete for Windows/Sionna and the archived ns-3.44/5G-LENA Group-B source.
- Trajectory preparation and validation: complete for E2/E6 at 25/5/2 m.
- Pilot RT: complete for E2 and E6 at 2 m using three representative positions and one gNB, with unchanged RT physics.
- Full RT: launched in the background in order E2 5 m, E2 2 m, E6 5 m, E6 2 m.
- ns-3-ready conversion: exact Group-B converter is wired; 25-m sets can be converted now and 5/2-m sets are added after their RT manifests complete.
- ns-3 18-case matrix: exact native runner/parser and portable Ubuntu handoff are ready. The failed WSL1 `eventfd` pilot remains excluded. The isolated `docker-desktop` WSL2 bridge completed a detached E2/25-m/Aggressive pilot with exit 0 and exactly reproduced the expected 7.225% post-warm-up outage, 6 completed HOs and 2 ping-pongs. While fine RT continues, the detached matrix watcher pre-fills the six ready 25-m cases; the official verifier currently accepts all three E2 modes and E6/Aggressive is running. After the complete fine-RT handoff it resumes the remaining 12 cases. Its conservative per-case timeout is 48 hours so the 81.37-s E6 runs are not truncated using an E2-scale assumption.
- Paper conclusions: intentionally not written until real ns-3 results exist.

## Runner

Examples:

```powershell
python run_experiment.py --stage validate
python run_experiment.py --scene E2 --resolution 2 --stage pilot
python run_experiment.py --scene E2 --resolution 5 --stage raytrace --resume
python run_experiment.py --scene E6 --resolution 2 --stage raytrace --resume
python run_experiment.py --stage convert --resume
python run_experiment.py --stage ns3 --scene E2 --resolution 2 --a3-mode aggressive --dry-run --resume
python run_experiment.py --stage verify
```

`--force` is required to replace an existing case. The 25-m baseline is reused unless explicitly forced.

`--stage all` completes preparation, RT, validation and conversion on Windows and stops at the verified Ubuntu handoff boundary. On native Linux it additionally runs the filtered/full ns-3 matrix, analysis and the strict completion audit.

## Validation and analysis

```powershell
python validate_rt_traces.py
python analyze_results.py
```

`analyze_results.py` only accepts a per-case `kpi.json` after independently confirming exit code 0, exact scene/resolution/A3 controls, the complete case metadata and every recorded output SHA-256. Events are read only from that verified case inventory. It emits no fabricated KPI rows when those inputs are absent and rejects stale/tampered results instead of silently aggregating them.

`prepare_ns3_package.py` generates the six scene-resolution configs, validates complete MPC unions, materializes isolated raw inputs, invokes the exact audited Group-B converter, and records per-file transfer checksums. `ns3_package/verify_handoff.py` recomputes those checksums plus gNB/timestamp counts before Ubuntu execution. The high-level `--stage ns3` delegates to `ns3_package/run_resolution_matrix.py`, preserving `--scene`, `--resolution`, `--a3-mode`, `--resume` and `--force`. Windows dry-run now materializes all 18 exact JSON command records even before fine traces finish, labeling unavailable hashes as pending. Its companion `.sh` files are host-independent: they derive the experiment root from `commands/`, default the repository to `$HOME/siolena-src`, support explicit `RT_SENSITIVITY_EXPERIMENT_ROOT`/`SIOLENA_NS3_REPO_ROOT` overrides, and reject whitespace-bearing roots before invoking ns-3. The runner additionally supports the optional audited `docker-desktop-wsl2` executor; bridge results must match the recorded WSL2 kernel, glibc loader, 83-file system runtime, five-file private runtime, executable and aggregate of all 39 dynamically linked ns-3 libraries. A real run remains fail-closed until every converted parameter, raw MPC file and finalized Sionna provenance hash exists. The 50-ms value is the hard-coded custom-controller polling period, not a proven independently configurable standard measurement cadence; no 10/20-ms auxiliary hack is included.

`verify_experiment.py --strict` is the fail-closed completion gate. It checks trajectory/physics invariants, the create-once baseline integrity lock, all six RT/conversion sets, the materialized command contract, and all 18 normalized ns-3 cases. For each successful ns-3 case it recomputes the runtime-config, Sionna manifest/config, raw-MPC aggregate, converted-parameter and output hashes and compares the binary/source/Git/version controls to `experiment_manifest.json`. It then checks required analysis tables/figures and result-dependent paper prose, returning nonzero while any required evidence is pending.

Once—and only once—all 18 ns-3 cases pass those provenance checks, the completion gate reruns `analyze_results.py` before checking CSVs, figures, tables and prose. This prevents an older generated artifact from satisfying completion after the underlying verified case set changes.

`analysis/requirements_traceability.md` maps all 35 numbered requirements to current authoritative evidence. It deliberately keeps run-dependent items pending until real fine RT/ns-3 outputs prove them, even when the corresponding implementation or synthetic regression already passes.

Regression reports record SHA-256 values for the exact parser/analyzer/verifier code under test. The completion gate recomputes those hashes and rejects a stale green report after any covered code change.

`post_rt_watcher.py` is launched separately in the background. It accepts no partial CSV as complete: only after all four fine `trace_manifest.json` files exist does it run RT validation, the authoritative six-set conversion, handoff verification, and a fresh dry-run that replaces all pending command provenance with final input hashes before refreshing the completion audit. It records its PID and state under `logs/`.

`station_checkpoint_watcher.py` may run alongside the controller. It creates read-only checkpoint evidence only after a station CSV is known to be closed, polls every five minutes, and never substitutes partial station evidence for the final network-wide trace validation.

```powershell
python station_checkpoint_watcher.py --once
python station_checkpoint_watcher.py --poll-seconds 300
```

The first command performs a reproducible one-shot scan; the second keeps the scanner detached when launched by the host process manager. Atomic state is written to `logs/station_checkpoint_watcher_status.json`.

Run `python test_station_checkpoint_watcher.py` to exercise the closure-state rules without reading experiment traces. The passing report and tested-code hashes are stored in `analysis/station_checkpoint_watcher_regression.json`.

The verified implementation limitations are already written in academic English under `paper_ready/measurement_cadence_note.md` and `paper_ready/trace_replay_note.md`; neither file assumes a sensitivity result that has not yet been measured.
