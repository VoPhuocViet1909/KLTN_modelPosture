"""Sinh recording/script_v2.json từ TaiLieu/KichBan_Quay_DataTrain_10Nguoi_v2.xlsx (sheet "Kịch bản clip"). Chỉ đọc file Excel.

    pip install -r requirements-dev.txt
    python recording/make_script.py [--xlsx <đường dẫn>] [--out recording/script_v2.json]

Cột Excel cho: id, clip, thời lượng, cam chính, hiệu lệnh, mức cần đạt. Phần máy đọc được (các mức / mốc đổi / điều kiện đạt) khó
suy ra từ chữ tự do nên nằm ở bảng PHASES / CHECKS dưới đây, đối chiếu từng dòng với cột "Mức cần đạt" và sheet "Lớp tư thế".
Điều kiện (check) = danh sách điều kiện AND, mỗi điều kiện {m: số đo, min, max, abs}; số đo:
  neck, trunk  : góc cổ / thân (độ) so với baseline A1, cam hông
  tilt         : lệch vai tiltRel (độ) so với baseline, cam laptop (abs = lấy trị tuyệt đối)
  raise        : raiseRel = (raise_base - raise) / raise_base, cam laptop (dương = vai nâng)
"""
import argparse
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_XLSX = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(HERE))), "TaiLieu",
                            "KichBan_Quay_DataTrain_10Nguoi_v2.xlsx")
CAM = {"hông": "side", "laptop": "front", "cả hai": "both"}


def c(m, lo=None, hi=None, ab=False):
    d = {"m": m}
    if lo is not None:
        d["min"] = lo
    if hi is not None:
        d["max"] = hi
    if ab:
        d["abs"] = True
    return d


GOOD = [c("neck", hi=10)]
FWD = [c("neck", lo=20)]
LEAN = [c("trunk", lo=20)]
SLOUCH = [c("trunk", lo=20), c("neck", lo=20)]
BACK = [c("trunk", hi=-15)]

# id -> điều kiện đạt (một mức). Không có = "theo hiệu lệnh".
CHECKS = {
    "A2": GOOD, "A3": GOOD,
    "B1": [c("neck", 20, 30)], "B2": [c("neck", lo=30)],
    "B3": [c("trunk", 20, 30)], "B4": [c("trunk", lo=30)],
    "B5": SLOUCH, "B6": SLOUCH,                      # Excel chỉ ghi "rõ hơn L1": tạm dùng cùng ngưỡng L1
    "B7": [c("trunk", -25, -15)], "B8": [c("trunk", hi=-25)],
    "B9": [c("neck", hi=-15)],
}
# clip 2 mức (giây 15 đổi mức): (điều kiện mức 1, điều kiện mức 2)
TWO_LEVEL = {
    "E1": ([c("tilt", 3, 5, True)], [c("tilt", lo=5, ab=True)]),
    "E2": ([c("tilt", 3, 5, True)], [c("tilt", lo=5, ab=True)]),
    "E3": (None, None), "E4": (None, None), "E5": (None, None), "E6": (None, None),
    "E9": (None, [c("tilt", lo=3.5, ab=True)]), "E10": (None, [c("tilt", lo=3.5, ab=True)]),
    "E11": (None, None),                             # chọn ngưỡng raiseRel từ dữ liệu này, chưa có số
}
TRANSITION = [("GOOD", GOOD), ("FORWARD_HEAD", FWD), ("GOOD", GOOD), ("LEAN_FORWARD", LEAN),
              ("GOOD", GOOD), ("SLOUCH", SLOUCH), ("GOOD", GOOD), ("LEAN_BACKWARD", BACK)]
DISTANCE = ["70 cm", "60 cm", "50 cm", "40 cm"]


def phases(cid, dur):
    if cid == "C1":
        return [dict(start=15 * i, label=name, check=chk) for i, (name, chk) in enumerate(TRANSITION)]
    if cid == "E7":
        return [dict(start=15 * i, label=name, check=None, cm=int(name.split()[0])) for i, name in enumerate(DISTANCE)]
    if cid in TWO_LEVEL:
        a, b = TWO_LEVEL[cid]
        return [dict(start=0, label="MỨC NHẸ", check=a), dict(start=15, label="MỨC RÕ HƠN", check=b)]
    return [dict(start=0, label="", check=CHECKS.get(cid))]


def build(xlsx):
    import openpyxl
    ws = openpyxl.load_workbook(xlsx, data_only=False)["Kịch bản clip"]
    clips = []
    for block, cid, name, dur, cam, cue, goal in ws.iter_rows(min_row=5, max_col=7, values_only=True):
        if not (cid and name and isinstance(dur, (int, float))):
            continue
        clips.append(dict(id=cid, block=block, clip=name, duration=int(dur), cam=CAM[cam], cam_text=cam,
                          cue=cue, goal=goal, phases=phases(cid, int(dur))))
    return dict(_source="TaiLieu/KichBan_Quay_DataTrain_10Nguoi_v2.xlsx, sheet 'Kịch bản clip' (sinh bởi recording/make_script.py)",
                margin_sec=3, clips=clips)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--xlsx", default=DEFAULT_XLSX)
    ap.add_argument("--out", default=os.path.join(HERE, "script_v2.json"))
    a = ap.parse_args()
    data = build(a.xlsx)
    with open(a.out, "w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
        f.write("\n")
    print(f"Đã ghi {len(data['clips'])} clip, tổng {sum(x['duration'] for x in data['clips'])} s -> {a.out}")


if __name__ == "__main__":
    main()
