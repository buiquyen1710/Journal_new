# Technical issue register

| ID | Issue / evidence | Risk | Owner role | Acceptance test |
|---|---|---|---|---|
| T1 | 25 m sampling at 350 km/h is ~257 ms between samples. | Critical: cannot resolve typical HO dynamics. | RT lead | 2/5/25 m sensitivity study shows KPI convergence or defines minimum justified resolution. |
| T2 | Channel lookup is nearest-neighbor/snapshot based. | High: discontinuities and timing bias. | Channel lead | Compare nearest, linear/physics-aware interpolation on fixed trajectories. |
| T3 | Current controller uses idealized RRC and proxy HOF/RLF. | Critical: invalid mobility claims. | ns-3 lead | Implement delays/timers/failure states and pass deterministic event tests. |
| T4 | UMi fallback is used outside a clearly validated range. | High: biased fallback channel. | Channel lead | Document applicability and compare against an appropriate railway/open-area model. |
| T5 | Some historical traces were speed-rescaled. | High: Doppler/time provenance ambiguity. | Data lead | All main results use native timing and record speed provenance. |
| T6 | Missing measurements may hold old values. | High: optimistic link persistence. | Integration lead | Explicit missing-data policy; inject gaps and verify deterministic outcomes. |
| T7 | Single CBR/simple interference assumptions. | Medium-high: weak load realism. | ns-3 lead | Add multi-load/interference scenarios and report sensitivity. |
| T8 | No measurement calibration against field/reference data. | High: absolute validity is limited. | PI/channel lead | Calibrate at least path loss/shadowing/delay metrics or narrow claims explicitly. |
| T9 | Unreal linkage is one-way visualization. | Medium: cannot claim closed-loop digital twin. | System lead | Either implement feedback or remove closed-loop language. |
| T10 | Novelty may overlap predictive/robust CHO literature. | High: publication positioning risk. | PI/algorithm lead | Updated systematic literature matrix and claim-to-evidence map approved at M0/M1. |

Priority order: T1 → T3 → T5/T6 → T2 → T8 → T7 → T4 → T10 → T9.
