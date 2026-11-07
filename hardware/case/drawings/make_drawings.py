"""
make_drawings.py - ess01_case.scad 의 3D 모델을 잘라(단면) 비추어(투영) 2D 도면 DXF 를 만든다.

    python3 make_drawings.py                 # out/*.dxf  (그다음 preview.py 로 PNG, pdf.py 로 A3 PDF)
필요: openscad, pip install ezdxf (미리보기, PDF 는 matplotlib 와 한글 글꼴 fonts-nanum)

도면은 모델에서 직접 뽑으므로 STL 과 치수가 같다. 치수 숫자는 scad 변수(echo)에서 읽는다.
배치는 KS 제3각법 (평면도 위, 정면도 가운데, 우측면도 오른쪽, 좌측면도 왼쪽, 배면도 맨 오른쪽).
레이어: OUTLINE 외형선, HIDDEN 숨은선(파선), CENTER 중심선, DIM 치수, TEXT 글자, FRAME 도면틀, ENGRAVE 새김 글자.
"""
from __future__ import annotations

import math
import os
import re
import subprocess
import sys
from pathlib import Path

import ezdxf
from ezdxf.enums import TextEntityAlignment

SCAD = str((Path(__file__).resolve().parent.parent / "ess01_case.scad"))
TMP = Path(__file__).resolve().parent / "tmp"
OUT = Path(__file__).resolve().parent / "out"
DATE = "2026-11-04"
FONT = "malgun.ttf"            # 오토캐드(한글 윈도)에서 한글이 보이는 글꼴. 없으면 문자 스타일 KOR 의 글꼴만 바꾸면 됨

# ------------------------------------------------------------------ scad 변수
PARAM_NAMES = ("wall floor_t lid_t tol box_in box_out pi_pos pi_holes pi_standoff_h pi_standoff_d pi_pcb_t pi_usbc_x usbc_cut sd_cut "
               "bb_size gland_d gland_yz ear_l ear_w ear_t box_bosses boss_d led_center led_window led_pcb led_standoff buzzer_pos "
               "buzzer_d button_pos button_d screw_clear screw_pilot pi_pilot head_in head_out amg_x0 amg_z0 amg_pcb amg_pkg "
               "amg_pkg_off amg_gap hood_depth hood_angle mq2_y mq2_can_d mq2_cap_h mq2_tie_dx mq2_tie_dy sht_pod sht_neck "
               "head_gland_d head_gland_z head_bosses lip_h").split()


def params() -> dict:
    TMP.mkdir(exist_ok=True)
    f = TMP / "echo.scad"
    f.write_text(f"include <{SCAD}>\n" + "\n".join(f'echo(V="{n}", {n});' for n in PARAM_NAMES) + "\n", encoding="utf-8")
    r = subprocess.run(["openscad", "-D", 'part="none"', "-o", str(TMP / "echo.csg"), str(f)], capture_output=True, text=True)
    (TMP / "params.txt").write_text("\n".join(l for l in r.stderr.splitlines() if l.startswith("ECHO")), encoding="utf-8")
    p = {}
    for line in (TMP / "params.txt").read_text().splitlines():
        m = re.match(r'ECHO: V = "(\w+)", (.*)$', line.strip())
        if m:
            p[m.group(1)] = eval(m.group(2).replace("true", "True").replace("false", "False"))
    return p


P = params()


# ------------------------------------------------------------------ OpenSCAD 단면, 투영 -> 닫힌 곡선(loop)
def scad2d(name: str, body: str) -> list[list[tuple[float, float]]]:
    f = TMP / f"{name}.scad"
    f.write_text(f"include <{SCAD}>\n{body}\n", encoding="utf-8")
    out = TMP / f"{name}.dxf"
    r = subprocess.run(["openscad", "-D", 'part="none"', "-o", str(out), str(f)], capture_output=True, text=True)
    if not out.exists():
        raise RuntimeError(f"{name}: {r.stderr[-800:]}")
    doc = ezdxf.readfile(out)
    segs = [((round(e.dxf.start.x, 4), round(e.dxf.start.y, 4)), (round(e.dxf.end.x, 4), round(e.dxf.end.y, 4)))
            for e in doc.modelspace() if e.dxftype() == "LINE"]
    return chain(segs)


def chain(segs):
    adj: dict = {}
    for i, (a, b) in enumerate(segs):
        adj.setdefault(a, []).append(i)
        adj.setdefault(b, []).append(i)
    used = [False] * len(segs)
    loops = []
    for i in range(len(segs)):
        if used[i]:
            continue
        used[i] = True
        a, b = segs[i]
        loop = [a, b]
        cur = b
        while cur != a:
            nxt = next((j for j in adj[cur] if not used[j]), None)
            if nxt is None:
                break
            used[nxt] = True
            s0, s1 = segs[nxt]
            cur = s1 if s0 == cur else s0
            loop.append(cur)
        if loop[-1] == loop[0]:
            loop = loop[:-1]
        loops.append(loop)
    return loops


def area(l):
    return 0.5 * sum(l[i][0] * l[(i + 1) % len(l)][1] - l[(i + 1) % len(l)][0] * l[i][1] for i in range(len(l)))


def bbox(l):
    xs = [p[0] for p in l]
    ys = [p[1] for p in l]
    return min(xs), min(ys), max(xs), max(ys)


def inside(pt, poly):
    x, y = pt
    c = False
    for i in range(len(poly)):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % len(poly)]
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1 + 1e-12) + x1:
            c = not c
    return c


def contained(a, b):
    ba, bb = bbox(a), bbox(b)
    if not (ba[0] >= bb[0] - 1e-6 and ba[1] >= bb[1] - 1e-6 and ba[2] <= bb[2] + 1e-6 and ba[3] <= bb[3] + 1e-6):
        return False
    if abs(abs(area(a)) - abs(area(b))) < 1e-6:
        return False
    cx = sum(p[0] for p in a) / len(a)
    cy = sum(p[1] for p in a) / len(a)
    return inside(a[0], b) or inside((cx, cy), b)


def inner_loops(loops):
    """다른 곡선 안에 든 곡선만 (구멍, 섬)"""
    return [l for l in loops if any(contained(l, o) for o in loops if o is not l)]


def same(a, b, eps=0.02):
    return all(abs(u - v) < eps for u, v in zip(bbox(a), bbox(b))) and abs(abs(area(a)) - abs(area(b))) < 0.05 * max(abs(area(a)), 1e-6) + 0.01


def dedupe(base, extra):
    return [l for l in extra if not any(same(l, b) for b in base)]


def circle_of(l):
    if len(l) < 20:
        return None
    cx = sum(p[0] for p in l) / len(l)
    cy = sum(p[1] for p in l) / len(l)
    rs = [math.hypot(p[0] - cx, p[1] - cy) for p in l]
    r = sum(rs) / len(rs)
    if r > 0 and (max(rs) - min(rs)) / r < 0.01:
        return cx, cy, max(rs)              # OpenSCAD 꼭짓점은 원 위
    return None


# ------------------------------------------------------------------ 보기 (view)
MAT = {   # 3D -> (u, v, w): 단면은 w = 0, 투영은 w 방향
    "top": lambda c: f"[[1,0,0,0],[0,1,0,0],[0,0,1,{-c}],[0,0,0,1]]",
    "front": lambda c: f"[[1,0,0,0],[0,0,1,0],[0,1,0,{-c}],[0,0,0,1]]",      # -Y 에서 봄: u = x, v = z
    "right": lambda c: f"[[0,1,0,0],[0,0,1,0],[1,0,0,{-c}],[0,0,0,1]]",      # +X 에서 봄: u = y
    "left": lambda c: f"[[0,-1,0,0],[0,0,1,0],[1,0,0,{-c}],[0,0,0,1]]",      # -X 에서 봄: u = -y
    "back": lambda c: f"[[-1,0,0,0],[0,0,1,0],[0,1,0,{-c}],[0,0,0,1]]",      # +Y 에서 봄: u = -x
}
UV = {
    "top": lambda x, y, z: (x, y), "front": lambda x, y, z: (x, z), "right": lambda x, y, z: (y, z),
    "left": lambda x, y, z: (-y, z), "back": lambda x, y, z: (-x, z),
}


def cut(part, kind, c, name):
    return scad2d(name, f"projection(cut = true) multmatrix({MAT[kind](c)}) {part};")


def sil(part, kind, name):
    return scad2d(name, f"projection(cut = false) multmatrix({MAT[kind](0)}) {part};")


class View:
    def __init__(self, kind, title, visible, hidden=(), engrave=()):
        self.kind, self.title = kind, title
        self.visible, self.hidden, self.engrave = list(visible), list(hidden), list(engrave)
        allp = [p for l in self.visible + self.hidden for p in l]
        self.bb = (min(p[0] for p in allp), min(p[1] for p in allp), max(p[0] for p in allp), max(p[1] for p in allp))
        self.off = (0.0, 0.0)

    def S(self, x, y, z):                         # 3D 점 -> 도면 좌표
        u, v = UV[self.kind](x, y, z)
        return (u + self.off[0], v + self.off[1])

    @property
    def sbb(self):
        return (self.bb[0] + self.off[0], self.bb[1] + self.off[1], self.bb[2] + self.off[0], self.bb[3] + self.off[1])


def layout(front, plan=None, right=None, left=None, back=None, extra=(), gap=30.0):
    """제3각법: 정면도를 기준으로 맞춤"""
    front.off = (0.0, 0.0)
    fb = front.sbb
    if plan:
        plan.off = (0.0, fb[3] + gap - plan.bb[1])
    if right:
        right.off = (fb[2] + gap - right.bb[0], 0.0)
    if left:
        left.off = (fb[0] - gap - left.bb[2], 0.0)
    if back:
        rb = right.sbb if right else fb
        back.off = (rb[2] + gap - back.bb[0], 0.0)
    y = fb[1]
    for v in extra:                               # 정면도 아래로 (u 는 정면도와 맞춤)
        v.off = (0.0, y - gap - v.bb[3])
        y = v.sbb[1]
    return [v for v in (plan, front, right, left, back, *extra) if v]


# ------------------------------------------------------------------ DXF 그리기
class Sheet:
    def __init__(self, scale_text: float):
        self.s = scale_text
        doc = ezdxf.new("R2013", setup=True, units=ezdxf.units.MM)
        doc.header["$INSUNITS"] = 4
        doc.header["$MEASUREMENT"] = 1
        doc.header["$LTSCALE"] = 1.0 * scale_text
        doc.styles.new("KOR", dxfattribs={"font": FONT})
        for name, color, lt, lw in (("OUTLINE", 7, "Continuous", 35), ("HIDDEN", 8, "DASHED", 18), ("CENTER", 1, "CENTER", 13),
                                    ("DIM", 3, "Continuous", 13), ("TEXT", 7, "Continuous", 18), ("FRAME", 7, "Continuous", 50),
                                    ("ENGRAVE", 4, "Continuous", 13), ("CUTLINE", 1, "DASHDOT", 25)):
            doc.layers.add(name, color=color, linetype=lt, lineweight=lw)
        ds = doc.dimstyles.new("KS")
        for k, v in dict(dimtxt=2.5, dimasz=2.5, dimexe=1.5, dimexo=1.0, dimgap=0.8, dimdec=1, dimtad=1, dimzin=8,
                         dimclrd=3, dimclre=3, dimclrt=3, dimscale=scale_text, dimdsep=46, dimtxsty="KOR", dimadec=0, dimtih=0, dimtoh=0).items():
            ds.dxf.set(k, v)
        self.doc, self.msp = doc, doc.modelspace()

    def loops(self, view, loops, layer, centers=True):
        for l in loops:
            c = circle_of(l)
            if c:
                cx, cy = c[0] + view.off[0], c[1] + view.off[1]
                self.msp.add_circle((cx, cy), c[2], dxfattribs={"layer": layer})
                if centers and layer in ("OUTLINE", "HIDDEN") and c[2] >= 1.5:
                    k = c[2] + 1.5 * self.s
                    self.msp.add_line((cx - k, cy), (cx + k, cy), dxfattribs={"layer": "CENTER"})
                    self.msp.add_line((cx, cy - k), (cx, cy + k), dxfattribs={"layer": "CENTER"})
            else:
                pts = [(p[0] + view.off[0], p[1] + view.off[1]) for p in l]
                self.msp.add_lwpolyline(pts, close=True, dxfattribs={"layer": layer})

    def view(self, v: View):
        self.loops(v, v.visible, "OUTLINE")
        self.loops(v, v.hidden, "HIDDEN")
        self.loops(v, v.engrave, "ENGRAVE", centers=False)
        b = v.sbb
        self.text(v.title, ((b[0] + b[2]) / 2, b[1] - 7 * self.s), 3.5, TextEntityAlignment.TOP_CENTER)

    def text(self, s, pos, h, align=TextEntityAlignment.BOTTOM_LEFT, layer="TEXT"):
        t = self.msp.add_text(s, height=h * self.s, dxfattribs={"style": "KOR", "layer": layer})
        t.set_placement(pos, align=align)
        return t

    # 치수 (점은 도면 좌표)
    def dh(self, p1, p2, y_base, text=None):
        d = self.msp.add_linear_dim(base=(p1[0], y_base), p1=p1, p2=p2, angle=0, dimstyle="KS",
                                    override={"dimtxsty": "KOR"}, dxfattribs={"layer": "DIM"})
        if text:
            d.dimension.dxf.text = text
        d.render()

    def dv(self, p1, p2, x_base, text=None):
        d = self.msp.add_linear_dim(base=(x_base, p1[1]), p1=p1, p2=p2, angle=90, dimstyle="KS",
                                    override={"dimtxsty": "KOR"}, dxfattribs={"layer": "DIM"})
        if text:
            d.dimension.dxf.text = text
        d.render()

    def dd(self, c, r, ang=45, text=None):
        d = self.msp.add_diameter_dim(center=c, radius=r, angle=ang, dimstyle="KS", override={"dimtxsty": "KOR"},
                                      dxfattribs={"layer": "DIM"})
        if text:
            d.dimension.dxf.text = text
        d.render()

    def cutline(self, p1, p2, label):
        self.msp.add_line(p1, p2, dxfattribs={"layer": "CUTLINE"})
        for p in (p1, p2):
            self.text(label, (p[0], p[1] + 2 * self.s), 4.0, TextEntityAlignment.BOTTOM_CENTER)

    def frame(self, views, title, part_name, number, scale_label, notes):
        """A3 도면틀(가로)을 그림 묶음에 맞춰 놓는다. 크기는 s 배"""
        s = self.s
        W, H = 420 * s, 297 * s
        from ezdxf import bbox as _bbox
        ext = _bbox.extents(self.msp)             # 치수, 글자까지 실제로 그려진 범위
        bx0, by0, bx1, by1 = ext.extmin.x - 4 * s, ext.extmin.y - 4 * s, ext.extmax.x + 4 * s, ext.extmax.y + 4 * s
        # 도면틀 왼쪽 아래 (그림을 표제란 위 남는 칸 가운데에)
        area_h = H - 20 * s - 44 * s
        fx = (bx0 + bx1) / 2 - (20 * s + (W - 30 * s) / 2)
        fy = (by0 + by1) / 2 - (10 * s + 44 * s + area_h / 2)
        if (bx1 - bx0) > W - 30 * s or (by1 - by0) > area_h:
            print(f"  ! {number}: 그림 묶음 {bx1 - bx0:.0f} x {by1 - by0:.0f} 이 도면틀에 빠듯함", file=sys.stderr)
        m = self.msp
        m.add_lwpolyline([(fx, fy), (fx + W, fy), (fx + W, fy + H), (fx, fy + H)], close=True, dxfattribs={"layer": "FRAME", "lineweight": 13})
        ix0, iy0, ix1, iy1 = fx + 20 * s, fy + 10 * s, fx + W - 10 * s, fy + H - 10 * s
        m.add_lwpolyline([(ix0, iy0), (ix1, iy0), (ix1, iy1), (ix0, iy1)], close=True, dxfattribs={"layer": "FRAME"})
        # 표제란 180 x 40
        tx0, ty0 = ix1 - 180 * s, iy0
        rows = [("도면명", title), ("부품", part_name), ("도면번호", number), ("척도", scale_label), ("단위, 투상법", "mm, 제3각법"),
                ("재료", "PETG (3D 프린트)"), ("작성", f"Claude, {DATE}"), ("검토", "")]
        rh = 40 * s / len(rows)
        m.add_lwpolyline([(tx0, ty0), (ix1, ty0), (ix1, ty0 + 40 * s), (tx0, ty0 + 40 * s)], close=True, dxfattribs={"layer": "FRAME"})
        m.add_line((tx0 + 32 * s, ty0), (tx0 + 32 * s, ty0 + 40 * s), dxfattribs={"layer": "FRAME", "lineweight": 18})
        for i, (k, v) in enumerate(reversed(rows)):
            y = ty0 + i * rh
            if i:
                m.add_line((tx0, y), (ix1, y), dxfattribs={"layer": "FRAME", "lineweight": 18})
            self.text(k, (tx0 + 2 * s, y + rh / 2), 2.5, TextEntityAlignment.MIDDLE_LEFT)
            self.text(v, (tx0 + 34 * s, y + rh / 2), 2.8, TextEntityAlignment.MIDDLE_LEFT)
        # 주기
        ny = iy0 + 3 * s
        for i, line in enumerate(reversed(notes)):
            self.text(line, (ix0 + 4 * s, ny + i * 5 * s), 2.5)
        self.text("주기", (ix0 + 4 * s, ny + len(notes) * 5 * s + 1 * s), 3.0)

    def save(self, path):
        self.doc.saveas(path)


COMMON_NOTES = [
    "1. 3D 모델 ess01_case.scad (" + DATE + ") 에서 단면, 투영으로 뽑은 도면. 치수는 설계값.",
    "2. 끼움부는 한쪽 여유 0.3 mm (tol) 포함. 모듈 치수는 추정치, 맞춤 시험 조각으로 확인 후 바뀔 수 있음.",
    "3. 출력: PETG, 층 0.2 mm, 서포트 없음. 벽 2.4 mm.",
]


def fmt(v):
    return f"{v:.1f}".rstrip("0").rstrip(".")


# ------------------------------------------------------------------ 위치표, 기호
class Table:
    """구멍, 자리 위치표. 그림 묶음 아래에 놓인다"""
    cols = (12, 58, 74, 62)              # 기호, 내용, 위치, 크기 (s 배)
    head = ("기호", "내용", "위치 (원점: 외곽 왼쪽 앞 아래)", "크기")

    def __init__(self, s, rows, title, cols=None):
        self.s, self.rows, self.title = s, rows, title
        if cols:
            self.cols = cols
        self.rh = 6.0 * s
        self.w = sum(self.cols) * s
        self.h = self.rh * (len(rows) + 1) + 7 * s
        self.off = (0.0, 0.0)

    @property
    def sbb(self):
        return (self.off[0], self.off[1], self.off[0] + self.w, self.off[1] + self.h)

    def draw(self, sh):
        s, m = self.s, sh.msp
        x0, y0 = self.off
        top = y0 + self.h - 7 * s
        sh.text(self.title, (x0, top + 2 * s), 3.2)
        n = len(self.rows) + 1
        m.add_lwpolyline([(x0, top), (x0 + self.w, top), (x0 + self.w, top - n * self.rh), (x0, top - n * self.rh)], close=True,
                         dxfattribs={"layer": "FRAME", "lineweight": 25})
        xs = [x0]
        for c in self.cols:
            xs.append(xs[-1] + c * s)
        for x in xs[1:-1]:
            m.add_line((x, top), (x, top - n * self.rh), dxfattribs={"layer": "FRAME", "lineweight": 13})
        for i, row in enumerate([self.head] + list(self.rows)):
            y = top - (i + 1) * self.rh
            if i:
                m.add_line((x0, y + self.rh), (x0 + self.w, y + self.rh), dxfattribs={"layer": "FRAME", "lineweight": 13})
            for j, cell in enumerate(row):
                sh.text(str(cell), (xs[j] + 1.2 * s, y + self.rh / 2), 2.2, TextEntityAlignment.MIDDLE_LEFT)


def tag(sh, pt, label, dx=1.0, dy=1.0):
    """그림 위 기호 (작은 지시선 + 글자)"""
    s = sh.s
    q = (pt[0] + dx * 5 * s, pt[1] + dy * 5 * s)
    sh.msp.add_line(pt, q, dxfattribs={"layer": "DIM"})
    sh.text(label, (q[0] + (0.8 * s if dx >= 0 else -0.8 * s), q[1]), 2.8,
            TextEntityAlignment.BOTTOM_LEFT if dx >= 0 else TextEntityAlignment.BOTTOM_RIGHT, layer="DIM")


def place_table(views, table, gap, where="below"):
    b = [v.sbb for v in views]
    if where == "right":
        table.off = (max(x[2] for x in b) + gap, max(x[3] for x in b) - table.h)
    else:
        table.off = (min(x[0] for x in b), min(x[1] for x in b) - gap - table.h)
    return table


def f1(v):
    return fmt(round(v, 2))


def xy(*v):
    return ", ".join(f1(a) for a in v)


# ------------------------------------------------------------------ 도면 1: 제어함 본체
def sheet_box_base():
    w, ft, t = P["wall"], P["floor_t"], P["tol"]
    bo, bi = P["box_out"], P["box_in"]
    part = "box_base()"
    plan_sil = sil(part, "top", "bb_plan_sil")
    plan_sec = cut(part, "top", ft + 0.1, "bb_plan_sec")
    plan = View("top", "평면도 (바닥 위 0.1 mm 단면)", plan_sil + dedupe(plan_sil, inner_loops(plan_sec)))
    fr = View("front", "정면도 (앞벽)", sil(part, "front", "bb_front_sil") + inner_loops(cut(part, "front", w / 2, "bb_front_sec")))
    rt = View("right", "우측면도", sil(part, "right", "bb_right_sil") + inner_loops(cut(part, "right", bo[0] - w / 2, "bb_right_sec")))
    lf = View("left", "좌측면도", sil(part, "left", "bb_left_sil") + inner_loops(cut(part, "left", w / 2, "bb_left_sec")))
    views = layout(fr, plan=plan, right=rt, left=lf, gap=34)
    sh = Sheet(2.0)
    s = sh.s
    el, ew = P["ear_l"], P["ear_w"]
    # 전체 치수
    top = plan.S(0, bo[1], 0)[1]
    sh.dh(plan.S(0, bo[1], 0), plan.S(bo[0], bo[1], 0), top + 7 * s)
    sh.dh(plan.S(-el + 1, bo[1] / 2 + ew / 2, 0), plan.S(bo[0] + el - 1, bo[1] / 2 + ew / 2, 0), top + 14 * s, text="<> (귀 포함)")
    sh.dv(plan.S(bo[0], 0, 0), plan.S(bo[0], bo[1], 0), plan.S(bo[0] + el, 0, 0)[0] + 7 * s)
    sh.dv(fr.S(bo[0], 0, 0), fr.S(bo[0], 0, bo[2]), fr.S(bo[0] + el, 0, 0)[0] + 7 * s)
    # 기호
    px0, py0 = w + P["pi_pos"][0], w + P["pi_pos"][1]
    ph = [(px0 + h[0], py0 + h[1]) for h in P["pi_holes"]]
    bos = [(w + b[0], w + b[1]) for b in P["box_bosses"]]
    uc = P["usbc_cut"]
    ucx, ucz = px0 + P["pi_usbc_x"], ft + P["pi_standoff_h"] + P["pi_pcb_t"] + 1.6
    sc = P["sd_cut"]
    sdy, sdz = py0 + P["pi_size"][1] / 2 if "pi_size" in P else py0 + 28, ft + P["pi_standoff_h"] - 2
    gy, gz = w + P["gland_yz"][0], ft + P["gland_yz"][1]
    ex = (-el / 2 + 0.5, bo[0] + el / 2 - 0.5)
    bb = P["bb_size"]
    bx0, by0 = w + (bi[0] - bb[0]) / 2 - t, w + bi[1] - 2 - bb[1] - t
    tag(sh, plan.S(*ph[2], 0), "P1")
    tag(sh, plan.S(*bos[0], 0), "B1")
    tag(sh, plan.S(bx0, by0 + bb[1] + 2 * t, 0), "R1", 1, -1)
    tag(sh, plan.S(ex[1], bo[1] / 2, 0), "E1", 1, -1)
    tag(sh, fr.S(ucx, 0, ucz + uc[1] / 2), "U1", 1, 1)
    tag(sh, fr.S(w + 80, 0, ft + 17), "V1", 1, 1)
    tag(sh, lf.S(0, sdy, sdz + sc[1] / 2), "S1", -1, 1)
    tag(sh, rt.S(0, gy, gz + P["gland_d"] / 2), "G1", 1, 1)
    vx = [w + x for x in range(32, 81, 5)]
    rows = [
        ("P1", "Pi 5 받침 4 곳 (M2.5 셀프태핑)", "X, Y = " + " / ".join(xy(*p) for p in ph[:2]) + " ...", f"지름 {f1(P['pi_standoff_d'])}, 높이 {f1(P['pi_standoff_h'])}, 자리 {f1(P['pi_pilot'])}"),
        ("", "", "              " + " / ".join(xy(*p) for p in ph[2:]), "간격 58 x 49"),
        ("B1", "뚜껑 나사 기둥 4 곳 (M3)", "X, Y = " + " / ".join(xy(*b) for b in bos[:2]), f"지름 {f1(P['boss_d'])}, 자리 {f1(P['screw_pilot'])} 깊이 12"),
        ("", "", "              " + " / ".join(xy(*b) for b in bos[2:]), "(Pi 쪽 왼쪽 앞 모서리는 없음)"),
        ("R1", "브레드보드 자리 (네 모서리 턱)", f"X {f1(bx0)} ~ {f1(bx0 + bb[0] + 2 * t)}, Y {f1(by0)} ~ {f1(by0 + bb[1] + 2 * t)}", "턱 높이 2, 두께 1.6"),
        ("U1", "USB-C 구멍 (앞벽)", f"X {f1(ucx)}, Z {f1(ucz)} (중심)", f"{f1(uc[0])} x {f1(uc[1])}, 모서리 R2"),
        ("V1", "흡기 홈 10 개 (앞벽)", f"X {f1(vx[0])} ~ {f1(vx[-1])} 간격 5, Z {f1(ft + 11)} (중심)", "2.4 x 12"),
        ("S1", "microSD 홈 (왼쪽 벽)", f"Y {f1(sdy)}, Z {f1(sdz)} (중심)", f"{f1(sc[0])} x {f1(sc[1])}"),
        ("G1", "케이블 그랜드 PG9 (오른쪽 벽)", f"Y {f1(gy)}, Z {f1(gz)} (중심)", f"지름 {f1(P['gland_d'])}"),
        ("E1", "벽걸이 귀 구멍 2 곳 (M4 접시)", f"X {f1(ex[0])} / {f1(ex[1])}, Y {f1(bo[1] / 2)}", f"지름 4.5, 귀 {f1(el)} x {f1(ew)} x {f1(P['ear_t'])}"),
    ]
    tb = place_table(views, Table(s, rows, "구멍, 자리 위치표 (mm, 외곽 기준. X 오른쪽, Y 뒤, Z 위)"), 18 * s)
    for v in views:
        sh.view(v)
    tb.draw(sh)
    sh.frame(views + [tb], "ESS-01 화재 감지기 케이스", "제어함 본체 (box_base)", "ESS01-CASE-01", "1:2 (A3)",
             COMMON_NOTES + ["4. 벽, 바닥 두께 2.4. 안쪽 182 x 119 x 42. Pi 5 는 왼쪽 앞, 브레드보드(MB-102 830)는 뒤쪽."])
    return sh, "ESS01-CASE-01_제어함본체"


# ------------------------------------------------------------------ 도면 2: 제어함 뚜껑
def sheet_box_lid():
    w, lt, t = P["wall"], P["lid_t"], P["tol"]
    bo = P["box_out"]
    part = f"translate([0, {bo[1]}, {lt}]) rotate([180, 0, 0]) box_lid()"      # 본체에 얹은 방향, 판은 z 0~2.4
    plate = cut(part, "top", lt / 2, "lid_plate")
    under = cut(part, "top", -1.5, "lid_under")
    eng = [l for l in cut(part, "top", lt - 0.3, "lid_eng") if not any(same(l, b) for b in plate)]
    plan = View("top", "평면도 (바깥 면. 파선은 안쪽 테두리, LED 레일, 부저 테)", plate, hidden=under, engrave=eng)
    ya = w + P["led_center"][1]
    sec = View("front", "단면 A-A (LED 레일)", cut(part, "front", ya, "lid_secA"))
    views = layout(sec, plan=plan, gap=40)
    sh = Sheet(1.0)
    s = sh.s
    sh.cutline(plan.S(-6, ya, 0), plan.S(bo[0] + 6, ya, 0), "A")
    top = plan.S(0, bo[1], 0)[1]
    sh.dh(plan.S(0, bo[1], 0), plan.S(bo[0], bo[1], 0), top + 8)
    sh.dv(plan.S(bo[0], 0, 0), plan.S(bo[0], bo[1], 0), plan.S(bo[0], 0, 0)[0] + 12)
    # 단면 A-A 치수
    d = P["led_standoff"] + 1.6 + t + 1.2
    lc = P["led_center"]
    x0 = w + lc[0] - P["led_pcb"][0] / 2 - t - 2
    sh.dv(sec.S(x0, ya, 0), sec.S(x0, ya, lt), sec.S(x0, ya, 0)[0] - 8, text="<>")
    sh.dv(sec.S(x0, ya, 0), sec.S(x0, ya, -d), sec.S(x0, ya, 0)[0] - 18, text="<> (레일)")
    sh.dv(sec.S(bo[0] - w - t, ya, 0), sec.S(bo[0] - w - t, ya, -P["lip_h"]), sec.S(bo[0], ya, 0)[0] + 8, text="<> (테두리)")
    bos = [(w + b[0], w + b[1]) for b in P["box_bosses"]]
    lw_ = P["led_window"]
    cx, cy = w + lc[0], w + lc[1]
    bz, bt = (w + P["buzzer_pos"][0], w + P["buzzer_pos"][1]), (w + P["button_pos"][0], w + P["button_pos"][1])
    vy = w + P["pi_pos"][1] + 31.5
    vx = [w + P["pi_pos"][0] + x for x in range(14, 81, 6)]
    tag(sh, plan.S(*bos[3], 0), "H1", 1, 1)
    tag(sh, plan.S(cx + lw_[0] / 2, cy + lw_[1] / 2, 0), "L1", 1, 1)
    tag(sh, plan.S(bz[0], bz[1] + 6, 0), "Z1", -1, 1)
    tag(sh, plan.S(bt[0] + 6, bt[1] + 6, 0), "K1", 1, 1)
    tag(sh, plan.S(vx[-1], vy + 18, 0), "V1", 1, 1)
    tag(sh, plan.S(w + 24 + 45, w + 92 + 5, 0), "T1", 1, 1)
    rows = [
        ("H1", "나사 구멍 4 곳 (M3)", "X, Y = " + " / ".join(xy(*b) for b in bos[:2]), f"지름 {f1(P['screw_clear'])}"),
        ("", "", "              " + " / ".join(xy(*b) for b in bos[2:]), ""),
        ("L1", "신호등 LED 창", f"X {f1(cx)}, Y {f1(cy)} (중심)", f"{f1(lw_[0])} x {f1(lw_[1])}, 모서리 R1.5"),
        ("", "LED 레일 (안쪽, 파선)", f"기판 {f1(P['led_pcb'][0])} x {f1(P['led_pcb'][1])}, +X 쪽 열림", f"턱 깊이 {f1(P['led_standoff'] + 1.6 + t)}"),
        ("Z1", "부저 소리 구멍 7 개", f"X {f1(bz[0])}, Y {f1(bz[1])} (중심)", "지름 2 (가운데), 1.8"),
        ("", "부저 테 (안쪽, 파선)", "같은 중심", f"안지름 {f1(P['buzzer_d'] + 2 * t)}, 높이 4"),
        ("K1", "래치 해제 버튼 구멍 (HX16-B1)", f"X {f1(bt[0])}, Y {f1(bt[1])} (중심)", f"지름 {f1(P['button_d'])}"),
        ("V1", "배기 홈 12 개 (Pi 위)", f"X {f1(vx[0])} ~ {f1(vx[-1])} 간격 6, Y {f1(vy)} (중심)", "2.6 x 36"),
        ("T1", "새김 글자 'ESS-01'", f"X {f1(w + 24)}, Y {f1(w + 92)} (왼쪽 가운데)", "높이 9, 깊이 0.6"),
    ]
    tb = place_table(views, Table(s, rows, "구멍 위치표 (mm, 얹은 방향, 외곽 기준)", cols=(10, 44, 66, 44)), 24, where="right")
    for v in views:
        sh.view(v)
    tb.draw(sh)
    sh.frame(views + [tb], "ESS-01 화재 감지기 케이스", "제어함 뚜껑 (box_lid)", "ESS01-CASE-02", "1:1 (A3)",
             COMMON_NOTES + ["4. 출력은 바깥 면을 바닥에 두고. 평면도는 본체에 얹은 방향 (아래쪽이 앞)."])
    return sh, "ESS01-CASE-02_제어함뚜껑"


# ------------------------------------------------------------------ 도면 3: 센서 헤드 본체
def sheet_head_body():
    w, ft, t = P["wall"], P["floor_t"], P["tol"]
    ho, hi = P["head_out"], P["head_in"]
    part = "head_body()"
    plan_sil = sil(part, "top", "hb_plan_sil")
    plan = View("top", "평면도 (바닥 위 1 mm 단면)", plan_sil + dedupe(plan_sil, inner_loops(cut(part, "top", ft + 1.0, "hb_plan_sec"))))
    f_sil = sil(part, "front", "hb_front_sil")
    hood = cut(part, "front", -1.5, "hb_hood")
    fr = View("front", "정면도", f_sil + dedupe(f_sil, hood) + dedupe(f_sil + hood, inner_loops(cut(part, "front", w / 2, "hb_front_sec"))))
    bk = View("back", "배면도", sil(part, "back", "hb_back_sil") + inner_loops(cut(part, "back", ho[1] - w / 2, "hb_back_sec")))
    px = -P["sht_neck"] - P["sht_pod"][0]
    l_sil = sil(part, "left", "hb_left_sil")
    lf = View("left", "좌측면도 (SHT31 상자 바깥 벽)", l_sil + dedupe(l_sil, cut(part, "left", px + 0.8, "hb_left_pod")))
    rt = View("right", "우측면도", sil(part, "right", "hb_right_sil"))
    views = layout(fr, plan=plan, right=rt, left=lf, back=bk, gap=26)
    sh = Sheet(1.0)
    s = sh.s
    top = plan.S(0, ho[1], 0)[1]
    sh.dh(plan.S(px, ho[1], 0), plan.S(ho[0], ho[1], 0), top + 16, text="<> (상자 포함)")
    sh.dh(plan.S(0, ho[1], 0), plan.S(ho[0], ho[1], 0), top + 8)
    sh.dv(plan.S(ho[0], 0, 0), plan.S(ho[0], ho[1], 0), plan.S(ho[0], 0, 0)[0] + 8)
    sh.dv(plan.S(ho[0], -P["hood_depth"], 0), plan.S(ho[0], 0, 0), plan.S(ho[0], 0, 0)[0] + 8, text="<>")
    sh.dv(fr.S(ho[0], 0, 0), fr.S(ho[0], 0, ho[2]), fr.S(ho[0], 0, 0)[0] + 8)
    a = [P["amg_pkg"][0] + 1, P["amg_pkg"][1] + 1]
    ax = w + P["amg_x0"] + P["amg_pcb"][0] / 2 + P["amg_pkg_off"][0]
    az = ft + P["amg_z0"] + P["amg_pcb"][1] / 2 + P["amg_pkg_off"][1]
    gx, gz = w + hi[0] / 2, ft + P["head_gland_z"]
    tpx, tpy = w + hi[0] / 2, w + hi[1] / 2 + 4
    pod = P["sht_pod"]
    hb = [(w + b[0], w + b[1]) for b in P["head_bosses"]]
    tag(sh, fr.S(ax + a[0] / 2, 0, az + a[1] / 2), "A1", 1, 1)
    tag(sh, bk.S(gx, 0, gz + P["head_gland_d"] / 2), "G1", -1, 1)
    tag(sh, plan.S(tpx + 6, tpy + 6, 0), "T1", 1, 1)
    tag(sh, plan.S(px, ho[1] / 2 + pod[1] / 2, 0), "S1", -1, 1)
    tag(sh, plan.S(*hb[2], 0), "B1", -1, 1)
    tag(sh, plan.S(w + P["amg_x0"], w + 2, 0), "R1", -1, -1)
    rows = [
        ("A1", "AMG8833 창 (앞벽)", f"X {f1(ax)}, Z {f1(az)} (중심)", f"{f1(a[0])} x {f1(a[1])}"),
        ("", "후드", f"앞으로 {f1(P['hood_depth'])}, 벌어짐 {f1(P['hood_angle'])}° (60° 화각 안 가림)", f"끝 안쪽 {f1(a[0] + 2 * P['hood_depth'] * math.tan(math.radians(P['hood_angle'])))} x {f1(a[1] + 2 * P['hood_depth'] * math.tan(math.radians(P['hood_angle'])))}"),
        ("R1", "AMG8833 기판 레일 2 개 (위에서 넣음)", f"X {f1(w + P['amg_x0'])} ~ {f1(w + P['amg_x0'] + P['amg_pcb'][0])}, 앞벽에서 {f1(P['amg_gap'])}", f"기판 {f1(P['amg_pcb'][0])} x {f1(P['amg_pcb'][1])} x 1.6, 홈 {f1(1.6 + t)}"),
        ("G1", "케이블 그랜드 PG9 (뒷벽)", f"X {f1(gx)}, Z {f1(gz)} (중심)", f"지름 {f1(P['head_gland_d'])}"),
        ("T1", "삼각대 1/4\"-20 너트 자리 (바닥)", f"X {f1(tpx)}, Y {f1(tpy)} (중심)", f"육각 맞변 {f1(11.1 + 2 * t)} 깊이 5.6, 구멍 6.8"),
        ("S1", "SHT31 통풍 상자 (윗면 열림)", f"헤드 왼쪽 {f1(P['sht_neck'])} 떨어짐, 속 빈 목 6 x 5", f"바깥 {f1(pod[0])} x {f1(pod[1])} x {f1(pod[2])}, 벽 1.6"),
        ("B1", "뚜껑 나사 기둥 4 곳 (M3)", "X, Y = " + " / ".join(xy(*b) for b in hb[:2]), f"지름 6.5, 자리 {f1(P['screw_pilot'])} 깊이 10"),
        ("", "", "              " + " / ".join(xy(*b) for b in hb[2:]), ""),
    ]
    tb = place_table(views, Table(s, rows, "구멍, 자리 위치표 (mm, 헤드 외곽 왼쪽 앞 아래 기준. 상자는 X 음수 쪽)"), 16)
    for v in views:
        sh.view(v)
    tb.draw(sh)
    sh.frame(views + [tb], "ESS-01 화재 감지기 케이스", "센서 헤드 본체 (head_body)", "ESS01-CASE-03", "1:1 (A3)",
             COMMON_NOTES + ["4. AMG8833 창 앞은 막지 말 것 (적외선은 플라스틱을 거의 못 지남)."])
    return sh, "ESS01-CASE-03_센서헤드본체"


# ------------------------------------------------------------------ 도면 4: 센서 헤드 뚜껑
def sheet_head_lid():
    w, lt, t = P["wall"], P["lid_t"], P["tol"]
    ho, hi = P["head_out"], P["head_in"]
    part = "head_lid()"
    t_sil = sil(part, "top", "hl_plan_sil")
    cap_top = cut(part, "top", lt + P["mq2_cap_h"] - 0.8, "hl_cap_top")
    plate = cut(part, "top", lt / 2, "hl_plate")
    capc = (w + hi[0] / 2, w + P["mq2_y"])
    capr = (P["mq2_can_d"] + 2 * t + 2 + 3.2) / 2
    hid = [l for l in inner_loops(plate) if (c := circle_of(l)) and math.hypot(c[0] - capc[0], c[1] - capc[1]) < 0.5 and c[2] > 5]
    plan = View("top", "평면도 (파선은 캡 아래 MQ-2 구멍)", t_sil + dedupe(t_sil, cap_top), hidden=hid)
    fr = View("front", "정면도", sil(part, "front", "hl_front_sil"))
    views = layout(fr, plan=plan, gap=18)
    sh = Sheet(0.5)
    s = sh.s
    top = plan.S(0, ho[1], 0)[1]
    sh.dh(plan.S(0, ho[1], 0), plan.S(ho[0], ho[1], 0), top + 6)
    sh.dv(plan.S(ho[0], 0, 0), plan.S(ho[0], ho[1], 0), plan.S(ho[0], 0, 0)[0] + 6)
    sh.dv(fr.S(ho[0], 0, 0), fr.S(ho[0], 0, lt + P["mq2_cap_h"]), fr.S(ho[0], 0, 0)[0] + 6)
    sh.dv(fr.S(0, 0, 0), fr.S(0, 0, lt), fr.S(0, 0, 0)[0] - 6)
    hb = [(w + b[0], w + b[1]) for b in P["head_bosses"]]
    tie = [(capc[0] + sx * P["mq2_tie_dx"], capc[1] + sy * P["mq2_tie_dy"]) for sy in (-1, 1) for sx in (-1, 1)]
    vx = [capc[0] + x for x in range(-12, 13, 6)]
    vy = w + hi[1] - 0.5
    tag(sh, plan.S(*hb[3], 0), "H1", 1, 1)
    tag(sh, plan.S(capc[0] + capr * 0.7, capc[1] + capr * 0.7, 0), "M1", 1, 1)
    tag(sh, plan.S(*tie[1], 0), "C1", 1, -1)
    tag(sh, plan.S(vx[-1], vy + 2, 0), "V1", 1, 1)
    rows = [
        ("H1", "나사 구멍 4 곳 (M3)", "X, Y = " + " / ".join(xy(*b) for b in hb[:2]), f"지름 {f1(P['screw_clear'])}"),
        ("", "", "              " + " / ".join(xy(*b) for b in hb[2:]), ""),
        ("M1", "MQ-2 구멍 (캡 아래)", f"X {f1(capc[0])}, Y {f1(capc[1])} (중심)", f"지름 {f1(P['mq2_can_d'] + 2 * t + 0.4)}"),
        ("", "보호 캡", "같은 중심. 윗면 구멍 5 (지름 3.2), 옆 홈 12", f"바깥 {f1(2 * capr)}, 안 {f1(P['mq2_can_d'] + 2 * t + 2)}, 높이 {f1(P['mq2_cap_h'])}"),
        ("C1", "케이블타이 구멍 4 곳", "X, Y = " + " / ".join(xy(*c) for c in tie[:2]), "4 x 1.8"),
        ("", "", "              " + " / ".join(xy(*c) for c in tie[2:]), ""),
        ("V1", "통기 홈 5 개 (뒤쪽)", f"X {f1(vx[0])} ~ {f1(vx[-1])} 간격 6, Y {f1(vy)} (중심)", "2 x 4"),
    ]
    tb = place_table(views, Table(s, rows, "구멍 위치표 (mm, 외곽 왼쪽 앞 기준)", cols=(10, 40, 66, 52)), 14, where="right")
    for v in views:
        sh.view(v)
    tb.draw(sh)
    sh.frame(views + [tb], "ESS-01 화재 감지기 케이스", "센서 헤드 뚜껑 (head_lid)", "ESS01-CASE-04", "2:1 (A3)",
             COMMON_NOTES + ["4. 출력은 캡이 위로. MQ-2 기판은 뚜껑 아래에 케이블타이 2 개로 묶음."])
    return sh, "ESS01-CASE-04_센서헤드뚜껑"


if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    made = []
    for fn in (sheet_box_base, sheet_box_lid, sheet_head_body, sheet_head_lid):
        sh, name = fn()
        path = OUT / f"{name}.dxf"
        sh.save(path)
        made.append(path)
        print("만듦:", path)
