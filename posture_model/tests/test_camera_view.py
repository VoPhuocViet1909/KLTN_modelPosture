"""Kiểm thử cửa sổ 'Xem camera': hình hiển thị phải chứa TRỌN khung gốc (không cắt trái/phải), giữ tỉ lệ, co theo cửa sổ,
cửa sổ hẹp thì xếp dọc.   python tests/test_camera_view.py   (chạy offscreen, không cần camera)"""
import os
import sys

import numpy as np

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from PySide6.QtCore import QSize  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from ui.camera_view import CameraView, frame_images, layout_rects, render  # noqa: E402
from ui.theme import apply_theme  # noqa: E402

app = QApplication.instance() or QApplication([])
apply_theme(app)

# màu đánh dấu ở 4 góc của mỗi khung gốc (BGR): trên-trái đỏ, trên-phải lục, dưới-trái lam, dưới-phải vàng
MARK = {"tl": (0, 0, 255), "tr": (0, 255, 0), "bl": (255, 0, 0), "br": (0, 255, 255)}


def marked_frame(w, h, base=60, m=24):
    f = np.full((h, w, 3), base, np.uint8)
    f[:m, :m] = MARK["tl"]
    f[:m, -m:] = MARK["tr"]
    f[-m:, :m] = MARK["bl"]
    f[-m:, -m:] = MARK["br"]
    return f


def frame(sw=640, sh=480, fw=640, fh=480, front=True):
    return dict(side=marked_frame(sw, sh), front=marked_frame(fw, fh) if front else None, Ls=None, Lf=None, side_idx=0)


def inside(r, w, h, eps=0.01):
    x, y, rw, rh = r
    return x >= -eps and y >= -eps and x + rw <= w + eps and y + rh <= h + eps


def overlap(a, b):
    return not (a[0] + a[2] <= b[0] + 0.01 or b[0] + b[2] <= a[0] + 0.01 or a[1] + a[3] <= b[1] + 0.01 or b[1] + b[3] <= a[1] + 0.01)


def test_layout_trong_hop_giu_ti_le_khong_chong():
    cases = [[(640, 480), (640, 480)], [(1280, 720), (480, 640)], [(640, 480)], [(1920, 1080), (640, 480)]]
    for sizes in cases:
        for box in [(560, 300), (1000, 400), (300, 700), (480, 480), (240, 180), (1600, 900)]:
            rects = layout_rects(sizes, *box)
            assert len(rects) == len(sizes)
            for (w, h), r in zip(sizes, rects):
                assert inside(r, *box), (sizes, box, r)
                assert abs(r[2] / r[3] - w / h) < 1e-6, (sizes, box, r)
            for i in range(len(rects)):
                for j in range(i + 1, len(rects)):
                    assert not overlap(rects[i], rects[j]), (sizes, box, rects)


def test_xep_ngang_khi_rong_xep_doc_khi_hep():
    two = [(640, 480), (640, 480)]
    a, b = layout_rects(two, 1000, 400)
    assert b[0] >= a[0] + a[2] and abs(a[1] - b[1]) < 1e-6          # cạnh nhau
    a, b = layout_rects(two, 300, 700)
    assert b[1] >= a[1] + a[3] and abs(a[0] - b[0]) < 1e-6          # trên dưới
    # cửa sổ cũ rộng ~560: ghép ngang 2 hình cao 300 cần ~1070 px bị cắt; nay phải thấy đủ cả hai và hình to hơn bản cắt
    a, b = layout_rects(two, 528, 400)
    assert a[3] > 150 and b[3] > 150 and inside(a, 528, 400) and inside(b, 528, 400)


def _px(img, x, y):
    c = img.pixelColor(int(x), int(y))
    return (c.blue(), c.green(), c.red())


def _near(c1, c2, tol=70):
    return all(abs(a - b) <= tol for a, b in zip(c1, c2))


def check_markers(pixmap, rects, m=24):
    """4 góc của mỗi hình gốc phải xuất hiện đủ màu đánh dấu ở 4 góc của hình hiển thị (chứng minh không bị cắt)."""
    img = pixmap.toImage()
    for r in rects:
        x, y, w, h = r
        k = w / 640.0 if abs(w / h - 4 / 3) < 0.01 else w / 640.0
        d = 6                                            # lấy mẫu sâu vào trong khối đánh dấu ~ vài px
        pts = {"tl": (x + d, y + d), "tr": (x + w - d - 1, y + d), "bl": (x + d, y + h - d - 1), "br": (x + w - d - 1, y + h - d - 1)}
        for name, (px, py) in pts.items():
            assert _near(_px(img, px, py), MARK[name]), (name, _px(img, px, py), r)


def test_anh_hien_thi_chua_tron_khung_goc():
    imgs = frame_images(frame())
    for size in (QSize(560, 300), QSize(1000, 420), QSize(300, 700)):
        px = render(imgs, size)
        rects = layout_rects([(i.width(), i.height()) for i in imgs], size.width(), size.height())
        assert all(inside(r, size.width(), size.height()) for r in rects)
        # khối đánh dấu phải đủ lớn để lấy mẫu: bỏ qua nếu hình co quá nhỏ (không xảy ra với các cỡ trên)
        check_markers(px, rects)


def test_cua_so_thuc_te_thay_du_hai_hinh_va_co_theo_kich_thuoc():
    cv = CameraView()
    cv.show()
    cv.show_frame(frame())
    for w, h in ((960, 560), (560, 420), (340, 640)):
        cv.resize(w, h)
        app.processEvents()
        view = cv.view
        grab = view.grab()
        rects = layout_rects([(i.width(), i.height()) for i in view.images], view.width(), view.height())
        assert all(inside(r, view.width(), view.height()) for r in rects)
        check_markers(grab, rects)
        # hình nhìn thấy to đủ để đọc (không bị co về điểm)
        assert min(r[2] for r in rects) > 100
    # mặc định (960x560): hai hình cạnh nhau, hẹp: xếp dọc
    cv.resize(960, 560)
    app.processEvents()
    a, b = layout_rects([(640, 480)] * 2, cv.view.width(), cv.view.height())
    assert b[0] > a[0] + a[2] - 1
    cv.resize(340, 640)
    app.processEvents()
    a, b = layout_rects([(640, 480)] * 2, cv.view.width(), cv.view.height())
    assert b[1] > a[1] + a[3] - 1
    cv.close()


def test_chi_mot_camera_va_kich_thuoc_khac_nhau():
    imgs = frame_images(frame(1280, 720, 480, 640, front=True))
    px = render(imgs, QSize(900, 500))
    rects = layout_rects([(i.width(), i.height()) for i in imgs], 900, 500)
    assert all(inside(r, 900, 500) for r in rects)
    for img, r in zip(imgs, rects):
        assert abs(r[2] / r[3] - img.width() / img.height()) < 1e-6
    only = frame_images(frame(front=False))
    assert len(only) == 1
    px = render(only, QSize(400, 400))
    r = layout_rects([(640, 480)], 400, 400)[0]
    check_markers(px, [r])


if __name__ == "__main__":
    fns = [v for k, v in dict(globals()).items() if k.startswith("test_")]
    for fn in fns:
        fn()
        print("OK ", fn.__name__)
    print(f"{len(fns)}/{len(fns)} test đạt")
