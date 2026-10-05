# Native 350 km/h Speed Verification

Verification date: 2026-06-18

## Conclusion

All six final-physics OSM railway scenes are now generated directly with:

- Train speed: `350 km/h` (`97.2222 m/s`)
- Carrier frequency: `30 GHz`
- Nominal UE trajectory spacing: `25 m`
- Expected time increment for a 25 m step: `0.257142857 s`
- Theoretical maximum Doppler: approximately `9729 Hz`

The four scenes that previously originated from 120 km/h traces were rerun
directly with the 350 km/h SionnaRT configuration on 2026-06-18:

- `do_thi_day_dac_GiaiPhong-GiapBat`
- `dong_bang_cong_nghiep_HaiDuong-PhuThai`
- `do_thi_cang_bien_HaiPhong-ThuongLy`
- `dam_pha_ven_bien_LangCo-HaiVanBac`

Long Bien and Hai Van were already generated directly at 350 km/h and were
not rerun in this correction.

## Direct CSV Verification

| Scene | Snapshots | Duration (s) | Median timestamp step (s) | Max absolute Doppler (Hz) | Status |
|---|---:|---:|---:|---:|---|
| Giai Phong - Giap Bat | 86 | 21.849587 | 0.257142746 | 9726.552 | READY |
| Long Bien - Gia Lam | 69 | 17.407389 | 0.257142753 | 9728.750 | READY |
| Hai Duong - Phu Thai | 522 | 133.822227 | 0.257142754 | 9728.952 | READY |
| Hai Phong - Thuong Ly | 246 | 62.861472 | 0.257142480 | 9728.925 | READY |
| Lang Co - Hai Van Bac | 169 | 43.133901 | 0.257142448 | 9728.590 | READY |
| Hai Van Bac - Hai Van Nam | 317 | 81.374682 | 0.257152583 | 9728.921 | READY |

The small variation in timestamp increments is caused by the actual distance
between consecutive points on the OSM-derived trajectory. It is not a speed
configuration mismatch.

## Provenance and Backups

- The rescaled pre-rerun outputs are preserved in:
  `native350_before_rerun_20260618`
- The original 120 km/h outputs are preserved in:
  `speed120_backup_20260615`
- The current authoritative datasets are the six top-level directories named:
  `output_*_full_sionna_final_physics`

The old `speed350_rescale_audit.json` records the earlier mathematical
rescaling operation. It is retained only for traceability and must not be used
as evidence that the current final outputs are rescaled traces.

## Scientific Interpretation

For snapshot-based static ray tracing, scaling timestamp and Doppler is
mathematically defensible because path geometry and complex amplitudes at a
fixed UE position do not depend on train speed. However, direct rerunning at
350 km/h provides cleaner experimental provenance and removes ambiguity in the
thesis methodology.

The thesis should state that all final datasets were generated using a common
350 km/h configuration. Historical 120 km/h and rescaled datasets must not be
mixed with the final datasets used for ns-3 evaluation.
