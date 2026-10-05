# Phan tich khoa hoc bo output Sionna RT 6 scene

> Historical report generated before the native 350 km/h rerun on 2026-06-18.
> Do not use its detailed path/power statistics as the final thesis values.
> Use `final_scene_scientific_figures/final_scene_figures_analysis.md` and
> `native350_speed_verification_20260618.md` for the current final outputs.

Ngay danh gia: 2026-06-16

## 1. Ket luan tong quan

Bo output hien tai phu hop de dua vao ns-3/adaptive handover baseline. Sau cac lan sua cau hinh va rerun:

- 6/6 scene dat `READY_FOR_NS3_HANDOVER_BASELINE`.
- Tat ca scene chay bang backend `sionna`, khong dung synthetic fallback.
- Toc do tau da dung `350 km/h`.
- Doppler cuc dai sau rerun khoang `9726.6-9729.0 Hz`, phu hop voi `30 GHz` va `350 km/h`.
- Moi RX snapshot tren moi scene deu co it nhat mot gNB co path Sionna.

Tieu chi READY hien tai dung cho bai toan handover hon tieu chi cu: khong yeu cau moi gNB phai co path tren toan tuyen, vi trong mang cellular thuc te moi gNB chi phu trach mot doan. Dieu quan trong la tai moi vi tri UE phai co it nhat mot cell usable.

## 2. Bang tong hop dinh luong

| Scene | Moi truong | Chieu dai | RX | Network covered | gNB | Path median range | Power median range | LOS ratio | Max Doppler | Status |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| do_thi_day_dac_GiaiPhong-GiapBat | Do thi day dac | 2124.3 m | 86 | 86/86 | 4 | 5.0-37.0 | -153.0..-97.9 dB | 76.2% | 9726.6 Hz | READY |
| do_thi_cau_song_LongBien-GiaLam | Cau song/do thi | 1692.4 m | 69 | 69/69 | 6 | 8.0-40.0 | -104.4..-96.6 dB | 94.1% | 9728.8 Hz | READY |
| dong_bang_cong_nghiep_HaiDuong-PhuThai | Dong bang/cong nghiep | 13011.0 m | 522 | 522/522 | 5 | 43.0-55.0 | -116.8..-111.8 dB | 100.0% | 9729.0 Hz | READY |
| do_thi_cang_bien_HaiPhong-ThuongLy | Do thi/cang bien | 6111.7 m | 246 | 246/246 | 6 | 27.0-64.5 | -111.7..-107.0 dB | 94.6% | 9728.9 Hz | READY |
| dam_pha_ven_bien_LangCo-HaiVanBac | Dam pha/ven bien | 4196.4 m | 169 | 169/169 | 5 | 44.0-58.0 | -107.2..-102.7 dB | 96.4% | 9728.6 Hz | READY |
| deo_nui_ven_bien_HaiVanBac-HaiVanNam | Deo nui/ven bien + DEM | 7891.8 m | 317 | 317/317 | 14 | 2.0-56.0 | -172.8..-101.7 dB | 57.1% | 9728.9 Hz | READY |

Ghi chu: power trong bang la cong suat kenh tinh tu bien do complex trong CSV, nen nen xem la channel power tuong doi, chua phai dBm tuyet doi neu chua gan them TX power, antenna gain va link-budget calibration.

## 3. Danh gia tung scene

### 3.1 Giai Phong - Giap Bat

Scene phu hop lam case do thi day dac. Co 86/86 RX snapshot du path, 4 gNB va cac doan best-gNB thay doi ro.

Diem dang chu y:

- GNB_A yeu hon han: path median 5.0, median power -153.0 dB, LOS chi 16/86 snapshot.
- GNB_B, C, D tot hon nhieu: median power khoang -97.9 den -100.6 dB.
- LOS ratio toan scene 76.2%, thap hon cac scene open-space, phu hop voi do thi bi che khuat.
- RMS delay cua GNB_A/GNB_C co max lon, lan luot 1.423 us va 1.752 us, cho thay multipath/NLOS manh.

Y nghia: day la case tot de test adaptive handover trong urban canyon/trackside clutter. New finding o scene nay la khong phai gNB nao cung co gia tri nhu nhau trong do thi; mot gNB dat sai hoac bi che khuat co the thanh cell bien rat yeu, trong khi cac gNB gan truc ray tao vung phu manh.

### 3.2 Long Bien - Gia Lam

Scene hien READY sau khi rerun voi 6 gNB va receiver height 6 m. Network coverage dat 69/69.

Diem dang chu y:

- Path median tu 8.0 den 40.0, khong qua cao nhu open-space nhung du on.
- Median power tu -104.4 den -96.6 dB, tot hon scene do thi Giai Phong o cac gNB yeu.
- Best-gNB co nhieu doan ngan trong khoang sau 1.1 km, cho thay vung cau/song tao handover churn cuc bo.
- Per-gNB missing van ton tai, nhung khong phai loi: cac gNB khac da phu tai nhung snapshot do.

Y nghia: scene nay phu hop mo phong cau song, noi co chuyen tiep giua bo song, cau va khu do thi. New finding la moi truong cau song khong chi tao reflection mat nuoc, ma con lam vung dominance cua cell bi chia nho, co the lam handover ping-pong neu thuat toan qua nhay.

### 3.3 Hai Duong - Phu Thai

Day la scene sach va on dinh nhat cho baseline dong bang/cong nghiep.

Diem dang chu y:

- 522/522 snapshot du path cho tat ca 5 gNB.
- LOS gan nhu 100%.
- RMS delay median rat nho, 0.0002-0.0003 us.
- Best-gNB chia tuyen kha deu theo chieu dai 13 km.
- Median power yeu hon cac scene ven bien/cau song, khoang -116.8 den -111.8 dB, nhung rat on dinh.

Y nghia: day la baseline LOS/open corridor rat tot. New finding: trong moi truong dong bang, kenh on dinh hon, it multipath nguy hiem, va handover co the duoc quy hoach theo khoang cach cell gan nhu tuyen tinh.

### 3.4 Hai Phong - Thuong Ly

Scene do thi/cang bien cung dat READY tot.

Diem dang chu y:

- 246/246 snapshot du path.
- 6 gNB chia vung dominance tuong doi deu.
- Path median cao, 27.0-64.5.
- Median power kha dong deu, -111.7 den -107.0 dB.
- LOS ratio 94.6%, cho thay du co clutter cong nghiep/cang, corridor van tuong doi thong thoang.

Y nghia: phu hop lam case cong nghiep/cang bien. New finding: clutter cong nghiep khong nhat thiet lam kenh xau hon do thi day dac; neu rail corridor rong va LOS con ton tai, kenh van on dinh va nhieu path.

### 3.5 Lang Co - Hai Van Bac

Scene dam pha/ven bien co ket qua rat on.

Diem dang chu y:

- 169/169 snapshot du path cho tat ca 5 gNB.
- LOS ratio 96.4%.
- Path median cao, 44.0-58.0.
- Median power manh va dong deu: -107.2 den -102.7 dB.
- Best-gNB chia tuyen rat sach: A -> B -> C -> D -> E.

Y nghia: day la case ven bien/open-water adjacency tot. New finding: moi truong dam pha ven bien co the tao kenh rat thuan loi neu track thoang, mat nuoc va it cong trinh cao tang khong tao obstruction nghiem trong.

### 3.6 Hai Van Bac - Hai Van Nam

Day la scene co gia tri khoa hoc cao nhat vi co DEM SRTM that va dia hinh deo nui.

Diem dang chu y:

- 317/317 snapshot co network coverage sau rerun.
- Can 14 gNB cho 7.89 km, mat do cao hon cac scene khac.
- LOS ratio chi 57.1%, thap nhat trong bo scene.
- Path median range rat rong, 2.0-56.0.
- Median power range rat rong, -172.8 den -101.7 dB.
- RMS delay median co the cao den 0.4474 us, max co station len 2.363 us.
- Best-gNB co 21 segment, nhieu hon ro ret cac scene khac.
- Hai targeted gNB `GNB_M` va `GNB_N` can de lap hai diem den do DEM/mesh clearance va che khuat cuc bo.

Y nghia: day la case kho cho adaptive handover. New finding quan trong nhat la dia hinh deo nui lam cell dominance phan manh, gNB macro/trackside thong thuong khong du; can mat do small-cell/relay cao hon va placement theo dia hinh. Neu dua vao ns-3, scene nay rat co gia tri de danh gia handover robustness, outage avoidance va conditional handover.

## 4. New findings co the dua vao bai/nghien cuu

1. Dia hinh Viet Nam tao cac profile kenh rat khac nhau, khong the dung mot model chung cho toan tuyen.

Dong bang va ven bien co kenh LOS on dinh, trong khi do thi va deo nui tao multipath/NLOS/churn manh.

2. Network-level READY khac voi per-gNB READY.

Trong handover, moi gNB khong can phu toan tuyen. Ket qua co y nghia khi moi vi tri UE co it nhat mot gNB usable. Dieu nay quan trong khi convert trace sang ns-3.

3. Hai Van DEM cho thay dia hinh that lam tang manh yeu cau quy hoach gNB.

Scene Hai Van can 14 gNB/relay de dat 317/317 snapshot, trong khi dong bang 13 km chi can 5 gNB van READY. Day la finding rat tot cho lap luan khoa hoc: gNB density phu thuoc manh vao terrain obstruction, khong chi vao chieu dai tuyen.

4. Bridge/river corridor gay handover churn cuc bo.

Long Bien co network coverage day du nhung best-gNB segment bi chia nho o vung 1.1-1.3 km. Day la dau hieu handover ping-pong risk.

5. Doppler validation xac nhan pipeline phu hop toc do cao.

Max Doppler xap xi 9.73 kHz o 30 GHz, dung voi 350 km/h. Day la co so de noi output phu hop bai toan HSR/mmWave.

6. Coastal lagoon/open-water khong nhat thiet la moi truong xau.

Lang Co - Hai Van Bac co path count cao, power on dinh, LOS cao. Moi truong nuoc/thoang co the giup kenh on dinh hon so voi do thi day dac va deo nui.

## 5. Kha nang dua vao ns-3

Phu hop de dua vao ns-3 voi cac dieu kien sau:

- Dung `scene_metadata.json` lam timeline/trajectory goc.
- Dung CSV `mpc_gnb_*.csv` lam multi-path channel trace theo gNB.
- Convert channel power tuong doi sang RSRP/SINR can co buoc calibration TX power/antenna gain.
- Per-gNB missing snapshot nen duoc xem la ngoai vung phu cua cell do, khong phai loi du lieu.
- Handover logic nen dung network-level best gNB theo timestamp, khong bat moi gNB co trace tai moi snapshot.

## 6. Caveat khoa hoc can ghi ro

- OSM building/height/material khong phai survey 3D chinh xac tuyet doi.
- Material radio duoc gan theo nhom doi tuong, nen la engineering approximation.
- Hai Van co hai correction clearance cuc bo trong metadata: sample 74 +0.5 m, sample 101 +3.0 m. Can trinh bay la correction de tranh receiver nam qua sat DEM/mesh, da validate bang Sionna targeted test.
- 14 gNB tren Hai Van la kich ban small-cell/relay cho mmWave 30 GHz, khong nen dien giai nhu macro-cell truyen thong.

## 7. Ket luan

Bo output sau cung la phu hop va co y nghia khoa hoc. No khong chi tao trace cho ns-3, ma con cho thay su khac biet ro giua cac dia hinh duong sat Viet Nam:

- Do thi day dac: NLOS/multipath ro.
- Cau song: churn va ping-pong risk.
- Dong bang/cong nghiep: baseline LOS on dinh.
- Cang bien: clutter cong nghiep nhung coverage lien tuc.
- Dam pha ven bien: kenh thoang, on dinh.
- Deo nui Hai Van + DEM: obstruction manh, can relay/small-cell density cao.

Finding co gia tri nhat: terrain-aware gNB placement la bat buoc cho mmWave railway; neu chi dat gNB theo khoang cach deu, cac doan deo nui/cau song co the tao coverage gap hoac handover churn, trong khi dong bang/ven bien lai khong can mat do qua cao.
