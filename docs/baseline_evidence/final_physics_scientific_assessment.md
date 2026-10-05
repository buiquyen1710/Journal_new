# Đánh giá tổng hợp Sionna RT full-physics cho 6 scene OSM Việt Nam

Ngày chạy: 2026-06-14

Ghi chú cập nhật 2026-06-15: các config `final_physics` ban đầu bị để `train_speed_kmh: 120.0`. Đã sửa sang `350.0` và scale lại CSV theo đúng mô hình động học: `timestamp_ns *= 120/350`, `doppler_hz *= 350/120`. Hình học ray, delay, amplitude, LOS/NLOS và path count không đổi. Backup bản 120 km/h nằm ở `speed120_backup_20260615`.

## Tóm tắt kỹ thuật

Pipeline đã chạy ray-tracing bằng backend Sionna cho đủ 6 scene. Các scene được export từ blend đã chuẩn bị sẵn, có rail bám theo object OSM, gNB lấy từ metadata scene, không dùng fallback synthetic path khi Sionna trả về rỗng.

Với Long Biên, lần export đầu có 2334 shape và timeout sau 8 giờ. Scene đã được lọc lại để giữ rail, ballast, gNB, mặt nước và công trình lớn trong corridor 220 m, loại footprint OSM nhỏ dưới 80 m2; XML tối ưu còn 373 shape và chạy xong.

Với Hải Vân, đã thêm DEM SRTM tile N16E108 trước khi export XML. Object terrain `RT_DEM_HaiVan_SRTM` dùng material `mat-vn_laterite`, thay thế mặt phẳng ground. Metadata UE/gNB/rail được nâng theo DEM. DEM mesh có grid 134 x 180, cao độ SRTM trong bbox khoảng -24.0 đến 1167.4 m; cao độ UE dọc rail sau quy chiếu khoảng 0.54 đến 110.53 m.

## Trạng thái từng scene

| Scene | Loại địa hình | Chiều dài rail | RX samples | gNB | Trạng thái |
|---|---|---:|---:|---:|---|
| do_thi_day_dac_GiaiPhong-GiapBat | Đô thị dày đặc | 2124.3 m | 86 | 4 | READY_FOR_NS3_HANDOVER_BASELINE |
| do_thi_cau_song_LongBien-GiaLam | Đô thị - cầu sông | 1692.4 m | 69 | 5 | NEEDS_REVIEW |
| dong_bang_cong_nghiep_HaiDuong-PhuThai | Đồng bằng - công nghiệp | 13011.0 m | 522 | 5 | READY_FOR_NS3_HANDOVER_BASELINE |
| do_thi_cang_bien_HaiPhong-ThuongLy | Đô thị cảng biển | 6111.7 m | 246 | 6 | READY_FOR_NS3_HANDOVER_BASELINE |
| dam_pha_ven_bien_LangCo-HaiVanBac | Đầm phá ven biển | 4196.4 m | 169 | 5 | READY_FOR_NS3_HANDOVER_BASELINE |
| deo_nui_ven_bien_HaiVanBac-HaiVanNam | Đèo núi ven biển + DEM | 7891.8 m | 317 | 6 | NEEDS_REVIEW |

## Ý nghĩa cho ns-3/adaptive handover

4 scene sẵn sàng dùng trực tiếp làm baseline handover: Giải Phóng, Hải Dương - Phú Thái, Hải Phòng - Thượng Lý, Lăng Cô - Hải Vân Bắc. Các CSV có đủ snapshot cho từng gNB, có biến thiên best-gNB theo tuyến, phù hợp để tạo trace phục vụ handover/adaptive network simulation.

Long Biên và Hải Vân có snapshot không có path ở một số gNB. Đây không phải lỗi backend vì log đều ghi `backend=sionna` và run hoàn tất; nguyên nhân là full-physics không sinh path khi bị che khuất hoặc ngoài vùng phủ hữu ích. Về mặt nghiên cứu, đây là thông tin có giá trị vì thể hiện coverage gap/outage ở môi trường cầu sông và đèo núi. Tuy nhiên, trước khi đưa trực tiếp vào ns-3, cần quy ước rõ cách biểu diễn outage: hoặc thêm zero-power/outage sample vào trace converter, hoặc cho ns-3 đọc metadata trajectory để hiểu snapshot không có dòng path là mất phủ.

Nếu mục tiêu là mô phỏng handover liên tục không mất kết nối, Long Biên và Hải Vân cần tối ưu thêm vị trí hoặc mật độ gNB. Nếu mục tiêu là đánh giá handover trong điều kiện thực tế có vùng che khuất, hai scene này có giá trị khoa học cao vì tạo ra trường hợp khó, đặc biệt Hải Vân với DEM thật.

## File kết quả chính

- Summary: `output_all_scenes_final_physics_summary.md`
- JSON summary: `output_all_scenes_final_physics_summary.json`
- Mỗi scene: `output_<scene_id>_full_sionna_final_physics/technical_ns3_evaluation.md`
- Hải Vân DEM source: `dem_sources/N16E108.hgt`
- Hải Vân XML có DEM: `output_deo_nui_ven_bien_HaiVanBac-HaiVanNam_full_sionna_final_physics/scene.xml`
