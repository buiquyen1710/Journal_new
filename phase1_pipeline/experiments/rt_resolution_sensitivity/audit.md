# Repository audit: RT resolution sensitivity

Audit date: 2026-08-24. The active Ubuntu workspace is not mounted, but a complete read-only Windows archive of the same ns-3/SioLENA source and historical Group-B runs was found and audited.

## Scene mapping

`vietnam_railway_osm_scenes/scene_manifest.json` establishes the mapping used by the experiment:

- E2 / river crossing: `do_thi_cau_song_LongBien-GiaLam` (`terrain_type=do_thi_cau_song`).
- E6 / mountainous pass: `deo_nui_ven_bien_HaiVanBac-HaiVanNam` (`terrain_type=deo_nui_ven_bien`).

The experiment runner selects exactly one manifest record for each requested terrain role (`do_thi_cau_song` and `deo_nui_ven_bien`) and derives the real ID, baseline directory and config filename from that record. E2/E6 remain experiment labels only; they are not filesystem aliases or hard-coded source IDs.

## Trajectory and RT spatial interval

- Source setting: `config/config_<scene>_final_physics.yaml`, key `external_scene.trajectory_spacing_m`, currently `25.0`.
- Source trajectory construction: `blender/prepare_osm_rail_scene_for_sionna.py`.
  - `find_rail_object()` chooses the longest candidate railway curve unless a rail name is supplied.
  - `resample_polyline()` samples by arc length and retains the endpoint.
  - `main()` writes positions to `scene_metadata.json` as `rx_trajectory_samples`.
- Important wiring defect: `tools/run_all_osm_scenes_final_physics.py` writes `trajectory_spacing_m: 25.0`, but its Blender invocation does not pass `--sample-spacing-m`. The Blender script therefore uses its independent CLI default of `25.0`; changing only the YAML key does not change the prepared trajectory in the legacy batch path.
- Important confounder: `create_rt_additions()` chooses gNB positions by indices/fractions of the sampled trajectory. Re-running the legacy prepare step at another sampling interval can move gNBs slightly and rebuild track objects. It would therefore change more than the UE sampling density.
- Controlled experiment implementation: `experiments/rt_resolution_sensitivity/run_experiment.py` reuses the exact baseline `scene.xml`, meshes, gNB metadata and baseline trajectory polyline. It preserves every baseline vertex and inserts samples within each segment. Hence the route geometry, endpoints, scene and gNBs remain fixed; actual interval is at or below the requested resolution.

## Timestamp creation

- `raytracing/run_sionna_rt.py::metadata_trajectory_samples()` accumulates Euclidean 3-D distance between successive receiver positions and sets `time_s = elapsed_distance / speed_m_s`.
- `_append_rows()` converts this value with `timestamp_ns = round(time_s * 1e9)`.
- Timestamp is therefore distance/speed based, not index based.
- At 350 km/h, `speed_m_s = 97.222222...`.

## gNB loading

- For an external-loop scene, `raytracing/run_sionna_rt.py::external_loop_base_stations()` loads `all_gnb_positions_m` and `all_gnb_facing` from the case `scene_metadata.json` and overlays them on the YAML station records.
- E2 baseline contains 6 gNBs. E6 contains 14, including two targeted gap gNBs recorded in its final metadata.
- The experiment copies these arrays unchanged for every resolution.

## Sionna RT computation and stochastic components

- `raytracing/run_sionna_rt.py::run_sionna_backend()` loads the Mitsuba XML with `merge_shapes=False`, sets 30 GHz and the configured planar arrays, then moves one receiver through all trajectory positions for each gNB.
- The `PathSolver` call uses LOS and specular reflection plus configured diffuse reflection, refraction, diffraction and edge diffraction.
- Final configs specify `max_depth=6`, `max_num_paths=3000`, `samples_per_src=2000`, diffuse reflection enabled, refraction disabled, diffraction enabled, edge diffraction enabled, `synthetic_array=true`, 110 dB relative path dynamic range and at most 256 retained paths.
- The only explicit stochastic seed found on the RT side is hard-coded `seed=42` in the `PathSolver` call. No separate YAML seed is consumed by this code.
- Per-path Doppler is recomputed from arrival angle and a velocity vector returned by `train_velocity()`. That velocity is fixed to global +x. This is a pre-existing limitation for curved tracks; it is held unchanged across resolutions.
- Empty Sionna snapshots are not filled because final configs use `fallback_on_empty_sionna_paths=false` and `require_sionna_backend=true`.

## MPC CSV format

`output/export_trace.py::TRACE_HEADER` defines:

`timestamp_ns,path_id,delay_s,amplitude_real,amplitude_imag,phase_rad,aoa_theta_rad,aoa_phi_rad,aod_theta_rad,aod_phi_rad,doppler_hz,los_flag`

One file is written per gNB (`mpc_gnb_*.csv`). A snapshot with no paths produces no CSV row for that timestamp. Consumers must join against the trajectory timestamp set and must not silently drop empty snapshots.

## Existing Windows validation and conversion

- `tools/evaluate_sionna_output_for_ns3.py` reports station path counts, LOS snapshots, received-power statistics, RMS delay spread, Doppler maximum and network timestamp coverage. It treats per-link missing timestamps as warnings if the union across gNBs covers the route.
- It does not check NaN/Inf, exact common timestamp sets, canonical physics hashes, detailed percentiles, or completed handover events. The experiment adds these checks in `validate_rt_traces.py`.
- `postprocess/make_ns3_ready_trace.py` is not a general E2/E6 converter. It is specialized to a 3-km tunnel zoning policy, hard-codes 350 km/h, changes LOS flags in Zone C and copies MPC CSVs. It must not be applied to E2/E6.
- No Windows-side code implements nearest-snapshot replay `argmin |t-tau|`; replay occurs in the audited ns-3/SioLENA source. The downstream audit below verifies that the paper's simple nearest-time equation is **not** the active implementation: the controller uses trajectory-progress-to-index mapping and the PHY uses uniform timestep-index replay.

## ns-3 / 5G-LENA implementation audit

- The authoritative downstream source archive is external to this repository; set `SIOLENA_NS3_REPO_ROOT` to its local path. It is ns-3.44 at Git commit `cc25f66bfd2a0b27d1354a46da7796dadc93f5c9`, with local changes including the trace-channel implementation. This dirty state is material provenance and is not represented as a clean upstream checkout.
- The evaluated program is `scratch/railway-digital-twin-evaluation/railway-digital-twin-evaluation.cc`, built as `build/scratch/railway-digital-twin-evaluation/ns3.44-railway-digital-twin-evaluation-default`. Historical `results_21_6/commands` records confirm this exact executable and flag set.
- The three paper configurations use `--algo=FixedA3`, `--HOM_base={1,3,5}` and `--TTT_base={40,160,320}`. `FixedA3` is a custom A3-like controller mode. It is distinct from the program's `NativeA3` mode and must not be described as the stock 5G-LENA `NrA3RsrpHandoverAlgorithm`.
- `RailwayScenarioConfig::samplingPeriodMs` is hard-coded to 50 ms. The custom controller's `Evaluate` method runs on that polling period. Fresh UE layer-1 RSRP callbacks are preferred when at least two valid, at-most-0.40-s-old measurements exist; otherwise trace-derived metrics remain available. There is no CLI parameter proving a standards-consistent PHY/L3 measurement cadence change.
- A3 entry compares the strongest available neighbor with the serving value plus HOM and requires the condition to persist for TTT, evaluated on the 50-ms controller ticks. Thus the 40-ms TTT cannot be temporally isolated from the 50-ms polling cadence. The configurations are joint HOM-TTT operating points.
- The auxiliary 10/20-ms matrix is intentionally not run. Changing only `samplingPeriodMs` would alter custom-controller polling without establishing a corresponding standard PHY measurement-generation cadence; this fails the user's no-hack condition.
- `NrGnbRrc/HandoverStart` and `NrGnbRrc/HandoverEndOk` are connected to the KPI collector. Successful HO is counted only on `HandoverEndOk`. Start/end records are paired only by exact IMSI/source/target and nonnegative time ordering; no FIFO cross-transition match is allowed. Ping-pong is consecutive completed A->B then B->A within 1 s. Raw handover events do not contain position/SINR, so the normalized event file uses the last time-series sample at or before HO start for `SINR_before` and the first sample at or after `HandoverEndOk` for position, `SINR_after` and coordinates; both joins are labeled as derived. Across RT resolutions, identical directed-transition sequences are paired index-to-index. When sequences differ, only ordered source->target transitions that occur uniquely in both sequences are accepted as timing/position matches; ambiguous repeated transitions are explicitly excluded rather than force-matched.
- Raw `time_series.csv` logs time, track position, UE xyz, serving/best cell, the controller's current serving-link `sinr_db`, fresh `phy_sinr_db`, and throughput. The paper's radio-outage KPI is the fraction of post-warm-up `sinr_db` samples below -6 dB: this exactly explains the provided E2 Aggressive check value of approximately 7.18% before warm-up exclusion. Fresh-PHY outage and the recorded `zero_throughput_or_fresh_phy_sinr_below_threshold` service-outage union are retained as separate diagnostic metrics, never substituted for the paper KPI. The established analysis warm-up exclusion is 0.15 s.

## Trace conversion and replay semantics

- The authoritative converter is `scratch/railway-digital-twin-evaluation/tools/convert_mpc_to_siolena_group_b.py`. It takes the union of per-gNB timestamps. A missing per-link snapshot at a union timestamp is preserved as the established weak-path sentinel, rather than deleting that time index.
- `TraceChannelAdapter::ConfigurePolylineProgressMapping` is the active controller-side mapping. It maps normalized physical trajectory progress to a rounded common timestamp index, then performs an exact per-link lookup at that timestamp; it is not the simple `argmin |t-tau|` fallback.
- The SioLENA `TracesChannelModel` consumes a fixed number of channel blocks and computes `updatePeriod = totalDuration/(N-1)`, then selects a block by uniform timestep index. Explicit irregular RT timestamps are not stored in `paraCfgCurrent.txt`. Therefore PHY replay is uniform-index replay across converted blocks. This limitation is held identical across resolutions and is disclosed rather than described as accidental interpolation or nearest-time replay.
- The same converter is invoked by `prepare_ns3_package.py`, and its SHA-256 is recorded in `ns3_package/readiness.json`. No tunnel-specific Windows converter is used.

## Execution boundary

- The tested WSL Ubuntu 24.04 instance had no downstream source checkout; Ubuntu 22.04 failed to start with `Wsl/Service/CreateInstance/0xd0000022`. A rootless private runtime was assembled for Ubuntu 24.04 with `libzmq5`, `libgsl27`, `libgslcblas0`, `libnorm1t64` and `libpgm-5.3-0t64`; with the archived `build/lib` on `LD_LIBRARY_PATH`, the binary successfully printed its audited CLI.
- A real E2/25-m/Aggressive pilot then completed trace/device/RRC setup and entered the ns-3 event loop, but WSL itself stopped with `Failed to read EventFd`; `wsl --list --verbose` confirms this distribution is WSL1. The zero-length raw CSVs and exit -6 are a failed runtime pilot and are not experiment results.
- Converting the user's distribution to WSL2 is a persistent system-level mutation and was not performed without explicit user authorization. The safer current boundary remains a ready-to-run WSL2/native-Ubuntu handoff.
- The exact handoff is in `ns3_package/run_resolution_matrix.py`. It accepts an arbitrary no-space `--experiment-root`, uses the audited binary/options, produces all 18 commands, normalizes actual outputs, and never substitutes the user's historical baseline hints as new results.
- A non-mutating alternative was subsequently found in the installed `docker-desktop` WSL2 utility distro. A 73.5-MB isolated glibc runtime was assembled from exactly the 83 Ubuntu 24.04 dependencies reported by `ldd`, plus the five previously extracted private GSL/ZMQ payloads. The exact ELF resolves every dependency and prints its audited CLI on kernel `6.6.87.1-microsoft-standard-WSL2`; an E2/25-m/Aggressive pilot has remained CPU-active past the WSL1 failure point and is still explicitly excluded from results until exit 0 and four nonempty CSVs are verified.
- `experiment_manifest.json` now also locks the aggregate SHA-256 of all 39 dynamically linked ns-3.44 shared libraries. Optional bridge execution additionally records and verifies the WSL2 kernel, loader hash and both runtime aggregates; native Ubuntu execution remains portable and uses executor type `native`.

## Baseline audit

- E2 baseline: 69 positions, 6 gNB files, backend `sionna`, complete network timestamp union; individual links have empty snapshots. Baseline CSV payload is about 2.01 MiB.
- E6 baseline: 317 positions, 14 gNB files, backend `sionna`, complete network timestamp union; many individual links have empty snapshots. Baseline CSV payload is about 20.66 MiB.
- Maximum recorded Doppler is approximately 9.73 kHz, consistent with the 30-GHz/350-km/h theoretical magnitude.
- Baseline scene/config provenance predates this experiment and does not contain a full canonical physics dump or Git hash. Fine runs therefore reuse the exact baseline XML/meshes and current final-physics settings, and record their hashes. A three-position pilot confirmed the Sionna backend and scene reuse. The old 25-m traces are reused provisionally and remain explicitly identified as legacy baseline outputs.

## Components held fixed

Within each scene, the experiment fixes: scene XML and meshes; DEM already embedded in E6; materials; gNB positions/facing; receiver height; 30-GHz carrier; 350-km/h speed; endpoints and baseline trajectory polyline; arrays; PathSolver interaction flags; depth; samples per source; seed 42; path filtering; and empty-path policy. Only inserted UE receiver positions/timestamps change.

On the ns-3 side the matrix fixes RNG seed/run 1, 400-MHz configuration bandwidth, numerology 3, 43-dBm program-default gNB transmit power, DirectPath beamforming, 100-ms beam update, ideal RRC, no background UEs, 1-ms/1200-byte UDP traffic, 0.15-s analysis warm-up, FixedA3 implementation and KPI definitions. Only RT resolution and the declared joint HOM-TTT operating point vary. Parser regression against all three real historical E2 operating points reproduces their completed-HO, ping-pong and serving-link outage values (including Aggressive: 6 `HandoverEndOk`, 2 ping-pongs, 7.184% without exclusion and 7.225% after the required 0.15-s exclusion). A synthetic zero-completed-HO regression additionally proves that an empty event file retains the complete analysis schema rather than becoming structurally invalid.

The analysis stage does not trust file presence alone. Before accepting any `kpi.json`, it independently requires exit code 0, matching scene/resolution/A3/RNG/cadence controls, complete case metadata, exact equality with the finalized Sionna output-hash inventory, and successful recomputation of every recorded ns-3 output SHA-256. Event ingestion is restricted to that verified case set. Regression proves that a valid fixture passes while a modified KPI or failed exit code is rejected.

## Repository state

`phase1_pipeline` is not a Git worktree. Case manifests record `git_commit=null` with this reason rather than inventing a commit.
