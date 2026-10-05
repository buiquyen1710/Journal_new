# Phase 0 asset inventory

## Curated source retained

- Core pipeline and scenario helpers.
- Blender preparation/export scripts.
- Sionna RT path computation, Doppler, trace export, post-processing, and analysis scripts.
- YAML/JSON configurations.
- Temporal-resolution sensitivity experiment source and audit notes.
- Compact scientific summaries and integrity manifests.

## Existing native-speed scene foundation

| Scene | Route length (m) | RX samples | gNBs | Role |
|---|---:|---:|---:|---|
| Giai Phong–Giap Bat | 2,124.3 | 86 | 4 | Dense urban controlled baseline |
| Long Bien–Gia Lam | 1,692.4 | 69 | 6 | Bridge/river crossing |
| Hai Duong–Phu Thai | 13,011.0 | 522 | 5 | Flat industrial/suburban baseline |
| Hai Phong–Thuong Ly | 6,111.7 | 246 | 6 | Port-city environment |
| Lang Co–Hai Van Bac | 4,196.4 | 169 | 5 | Lagoon/coastal transition |
| Hai Van Bac–Hai Van Nam | 7,891.8 | 317 | 14 | Mountain/coastal pass |
| **Total** | **35,027.6** | **1,409** | **40** | Six complementary environments |

The retained report states native 350 km/h trajectory timing. This is provenance evidence, not an independent rerun performed during this audit.

## Deliberately excluded

Generated meshes/scenes (`.blend`, `.fbx`, `.obj`), OSM/DEM downloads, raw JSON dumps, ray/path CSVs, images/videos, caches, logs, backups, temporary checkpoints, chat transcripts, and copied runtime binaries. These are large, regenerable, private-path-bearing, or unrelated to the source baseline.
