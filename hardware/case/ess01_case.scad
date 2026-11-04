// ESS-01 화재 감지기 케이스 (보조배터리 벤치 구성, 2026-11-04)
//
// 부품
//   box_base   제어함 본체: Pi 5 + 풀 브레드보드(MB-102 830), USB-C 전원 구멍, microSD 홈, 케이블 그랜드(PG9)
//   box_lid    제어함 뚜껑: 신호등 LED 창과 레일, 부저 자리, 래치 해제 버튼 구멍(16 mm), Pi 위 환기구
//   head_body  센서 헤드 본체: AMG8833 앞 창(60° 화각을 막지 않는 후드), SHT31 따로 떨어진 통풍 상자, 삼각대 1/4" 너트 자리
//   head_lid   센서 헤드 뚜껑: MQ-2 구멍과 보호 캡, 케이블타이 구멍
//   fit_test   맞춤 시험 조각: 큰 부품 전에 먼저 뽑아 구멍, 레일 치수를 확인
//   assembly   조립 미리보기 (출력용 아님)
//
// 내보내기: openscad -o box_base.stl -D 'part="box_base"' ess01_case.scad
// 치수는 아래 [ ] 묶음의 변수만 고치면 된다. 모듈 실물을 캘리퍼로 재서 맞출 것 (README 3장).
// 좌표: X 오른쪽, Y 안쪽(뒤), Z 위. 각 부품의 바깥 왼쪽 앞 아래 모서리가 원점.

part = "assembly";   // box_base, box_lid, head_body, head_lid, fit_test, assembly

/* [공통] */
$fn = 48;
tol = 0.3;           // 끼워 맞춤 여유 (한쪽)
wall = 2.4;          // 벽 (0.4 노즐 6 줄)
floor_t = 2.4;
lid_t = 2.4;
corner_r = 4;
screw_pilot = 2.6;   // M3 셀프태핑 나사 자리. 열 인서트(M3 x 5)를 쓰면 4.0
screw_clear = 3.4;   // 뚜껑의 M3 구멍
boss_d = 8;

/* [Raspberry Pi 5] */
pi_size = [85, 56];
pi_holes = [[3.5, 3.5], [61.5, 3.5], [3.5, 52.5], [61.5, 52.5]];
pi_pos = [1.5, 1.5];       // 제어함 안쪽 왼쪽 앞 모서리에서 Pi 기판 모서리까지
pi_standoff_h = 5;
pi_standoff_d = 6;
pi_pilot = 2.2;            // M2.5 셀프태핑 나사 자리
pi_pcb_t = 1.4;
pi_usbc_x = 11.2;          // Pi 왼쪽(microSD 쪽) 끝에서 USB-C 중심까지
usbc_cut = [13, 8.5];      // USB-C 플러그 몸통이 들어갈 구멍 (가로, 세로)
sd_cut = [15, 5.5];

/* [브레드보드 MB-102 830] */
bb_size = [165.1, 54.6];
bb_guide_h = 2;

/* [제어함] */
box_in = [182, 119, 42];   // 안쪽 길이, 폭, 높이
box_bosses = [[98, 4], [box_in[0] - 4, 4], [4, box_in[1] - 4], [box_in[0] - 4, box_in[1] - 4]];  // 뚜껑 나사 (Pi 모서리는 비움)
gland_d = 15.6;            // PG9 케이블 그랜드 (나사 지름 15.2)
gland_yz = [28, 21];       // +X 벽에서의 위치 (y, z)
ear_l = 13; ear_w = 22; ear_t = 3;   // 벽걸이 귀
lip_h = 3;                 // 뚜껑 안쪽 테두리 높이
lip_t = 1.6;

/* [뚜껑: 신호등 LED, 부저, 버튼] */
led_pcb = [56, 21];        // LED 모듈 기판 (가로, 세로)
led_pcb_t = 1.6;
led_window = [46, 10];     // LED 빛이 나오는 창
led_center = [135, 40];
led_standoff = 9;          // 뚜껑 안쪽 면에서 기판 윗면까지 (LED 높이보다 크게)
buzzer_d = 12;             // TMB12A05
buzzer_pos = [112, 16];
button_on = true;          // HX16-B1 래치 해제 버튼 (지금 설정은 안 씀, 구멍만)
button_d = 16.2;
button_pos = [150, 16];
lid_text = "ESS-01";

/* [센서 헤드] */
amg_pcb = [26, 18];        // AMG8833 모듈 기판 (가로, 세로)
amg_pcb_t = 1.6;
amg_pkg = [11.6, 8.0];     // 센서 몸통 (Panasonic Grid-EYE)
amg_pkg_h = 4.3;
amg_pkg_off = [0, 0];      // 기판 중심에서 센서 중심까지 (x, z)
hood_depth = 3;
hood_angle = 35;           // 화각 60° (반각 30°) 보다 넓게
mq2_can_d = 19.9;          // MQ-2 금속망 지름
mq2_y = 24;                // 헤드 안쪽 앞벽에서 MQ-2 중심까지
mq2_cap_h = 12;            // 뚜껑 위 보호 캡 높이 (센서가 튀어나온 만큼 + 여유)
mq2_tie_dx = 8;            // 케이블타이 구멍 (MQ-2 중심에서 x 로 ±)
mq2_tie_dy = 12;           //                 (y 로 ±)
sht_pod = [24, 22, 16];    // SHT31 통풍 상자 바깥 (x, y, z)
sht_neck = 8;              // 헤드와 상자 사이 거리 (MQ-2 열을 덜 받게)
head_in = [max(44, amg_pcb[0] + 18), 42, 34];
head_gland_d = 15.6;
head_gland_z = 14;
tripod = true;             // 바닥 1/4"-20 카메라 삼각대 너트 자리
head_bosses = [[3, 3], [head_in[0] - 3, 3], [3, head_in[1] - 3], [head_in[0] - 3, head_in[1] - 3]];   // 벽에 0.25 mm 파고듦
head_boss_d = 6.5;

e = 0.01;

// ------------------------------------------------------------------ 공통 도형
module rrect(size, r) {          // 모서리가 둥근 직육면체 (z 방향)
    r2 = min(r, size[0] / 2, size[1] / 2);
    hull() for (x = [r2, size[0] - r2], y = [r2, size[1] - r2]) translate([x, y, 0]) cylinder(r = r2, h = size[2]);
}

module slot2d(l, w) {            // 끝이 둥근 홈 (x 방향 길이 l)
    hull() { translate([-l / 2 + w / 2, 0]) circle(d = w); translate([l / 2 - w / 2, 0]) circle(d = w); }
}

module rounded_cut(w, h, r = 2) {  // xz 면의 둥근 사각 구멍 (y 로 뚫음), 중심 기준
    rotate([90, 0, 0]) linear_extrude(height = 20, center = true)
        offset(r = r) square([w - 2 * r, h - 2 * r], center = true);
}

// ------------------------------------------------------------------ 제어함 본체
box_out = [box_in[0] + 2 * wall, box_in[1] + 2 * wall, box_in[2] + floor_t];

module box_base() {
    difference() {
        union() {
            difference() {
                rrect(box_out, corner_r);
                translate([wall, wall, floor_t]) rrect([box_in[0], box_in[1], box_in[2] + 1], corner_r - wall + 1);
            }
            translate([wall, wall, floor_t]) box_inside_parts();
            box_ears();
        }
        translate([wall, wall, floor_t]) box_cuts();
    }
}

module box_inside_parts() {
    // 뚜껑 나사 기둥 (가까운 벽까지 붙임)
    for (p = box_bosses) {
        r = boss_d / 2;
        nx = p[0] <= r + 1 ? 0 : (p[0] >= box_in[0] - r - 1 ? box_in[0] : undef);
        ny = p[1] <= r + 1 ? 0 : (p[1] >= box_in[1] - r - 1 ? box_in[1] : undef);
        hull() {
            translate([p[0], p[1], -e]) cylinder(r = r, h = box_in[2] + e);
            if (nx != undef) translate([min(nx, p[0]), p[1] - r, -e]) cube([abs(nx - p[0]) + e, 2 * r, box_in[2] + e]);
            if (ny != undef) translate([p[0] - r, min(ny, p[1]), -e]) cube([2 * r, abs(ny - p[1]) + e, box_in[2] + e]);
        }
    }
    // Pi 5 받침
    for (h = pi_holes) translate([pi_pos[0] + h[0], pi_pos[1] + h[1], -e]) cylinder(d = pi_standoff_d, h = pi_standoff_h + e);
    // 브레드보드 자리: 네 모서리 바깥에 ㄱ 자 턱 (양면테이프로 붙이기 전 자리 잡기)
    bb0 = [(box_in[0] - bb_size[0]) / 2 - tol, box_in[1] - 2 - bb_size[1] - tol];
    bb1 = [bb0[0] + bb_size[0] + 2 * tol, bb0[1] + bb_size[1] + 2 * tol];
    for (cx = [0, 1], cy = [0, 1]) {
        x = cx == 0 ? bb0[0] : bb1[0];
        y = cy == 0 ? bb0[1] : bb1[1];
        translate([cx == 0 ? x - 1.6 : x - 6, cy == 0 ? y - 1.6 : y, -e]) cube([7.6, 1.6, bb_guide_h + e]);
        translate([cx == 0 ? x - 1.6 : x, cy == 0 ? y - 1.6 : y - 6, -e]) cube([1.6, 7.6, bb_guide_h + e]);
    }
}

module box_ears() {           // 양 옆 벽걸이 귀 (바닥과 같은 면, M4 나사)
    for (s = [0, 1]) difference() {
        translate([s == 0 ? -ear_l + 1 : box_out[0] - 1, box_out[1] / 2 - ear_w / 2, 0]) rrect([ear_l, ear_w, ear_t], 3);
        translate([s == 0 ? -ear_l / 2 + 0.5 : box_out[0] + ear_l / 2 - 0.5, box_out[1] / 2, -1]) {
            cylinder(d = 4.5, h = ear_t + 2);
            translate([0, 0, ear_t - 1.6 + 1]) cylinder(d1 = 4.5, d2 = 8.5, h = 2);  // 접시머리
        }
    }
}

module box_cuts() {
    // 나사 자리
    for (p = box_bosses) translate([p[0], p[1], box_in[2] - 12]) cylinder(d = screw_pilot, h = 13);
    // Pi 나사 자리
    for (h = pi_holes) translate([pi_pos[0] + h[0], pi_pos[1] + h[1], -1]) cylinder(d = pi_pilot, h = pi_standoff_h + 1.5);
    // USB-C (앞벽)
    translate([pi_pos[0] + pi_usbc_x, -wall / 2, pi_standoff_h + pi_pcb_t + 1.6]) rounded_cut(usbc_cut[0], usbc_cut[1]);
    // microSD (왼쪽 벽)
    translate([-wall / 2, pi_pos[1] + pi_size[1] / 2, pi_standoff_h - 2]) rotate([0, 0, 90]) rounded_cut(sd_cut[0], sd_cut[1], 1.5);
    // 앞벽 아래 흡기 홈 (Pi 앞)
    for (x = [32 : 5 : 80]) translate([x, -wall / 2, 11]) rounded_cut(2.4, 12, 1);
    // 케이블 그랜드 (+X 벽, 센서 헤드로)
    translate([box_in[0] + wall / 2, gland_yz[0], gland_yz[1]]) rotate([0, 90, 0]) cylinder(d = gland_d, h = wall + 2, center = true);
}

// ------------------------------------------------------------------ 제어함 뚜껑
// 바깥 면을 바닥에 두고 출력한다. 본체에 얹을 때 X 축으로 뒤집으므로 출력 좌표의 y 는 본체 y 를 뒤집은 값.
function ly(y) = box_out[1] - wall - y;          // 본체 안쪽 y -> 뚜껑 출력 좌표 y

module box_lid() {
    difference() {
        union() {
            rrect([box_out[0], box_out[1], lid_t], corner_r);
            // 안쪽 테두리 (본체에 끼워 맞춤), 나사 기둥 자리는 비움
            translate([0, 0, lid_t - e]) difference() {
                translate([wall + tol, wall + tol, 0]) rrect([box_in[0] - 2 * tol, box_in[1] - 2 * tol, lip_h], corner_r - wall);
                translate([wall + tol + lip_t, wall + tol + lip_t, -1]) rrect([box_in[0] - 2 * tol - 2 * lip_t, box_in[1] - 2 * tol - 2 * lip_t, lip_h + 2], 1);
                for (p = box_bosses) translate([wall + p[0], ly(p[1]), -1]) cylinder(d = boss_d + 2 * tol + 1, h = lip_h + 2);
            }
            translate([0, 0, lid_t - e]) led_rails();
            // 부저 테
            translate([wall + buzzer_pos[0], ly(buzzer_pos[1]), lid_t - e]) difference() {
                cylinder(d = buzzer_d + 2 * tol + 3.2, h = 4);
                translate([0, 0, -1]) cylinder(d = buzzer_d + 2 * tol, h = 6);
            }
        }
        for (p = box_bosses) translate([wall + p[0], ly(p[1]), -1]) cylinder(d = screw_clear, h = lid_t + lip_h + 2);
        // LED 창
        translate([wall + led_center[0], ly(led_center[1]), -1])
            linear_extrude(lid_t + 2) offset(r = 1.5) square([led_window[0] - 3, led_window[1] - 3], center = true);
        // 부저 소리 구멍
        translate([wall + buzzer_pos[0], ly(buzzer_pos[1]), -1]) {
            cylinder(d = 2, h = lid_t + 2);
            for (a = [0 : 60 : 300]) rotate([0, 0, a]) translate([3.2, 0, 0]) cylinder(d = 1.8, h = lid_t + 2);
        }
        if (button_on) translate([wall + button_pos[0], ly(button_pos[1]), -1]) cylinder(d = button_d, h = lid_t + 2);
        // Pi 위 배기 홈
        for (x = [14 : 6 : 80]) translate([wall + pi_pos[0] + x, ly(pi_pos[1] + 31.5), -1])
            linear_extrude(lid_t + 2) rotate([0, 0, 90]) slot2d(36, 2.6);
        // 글자: 바깥 면(출력 바닥)에 0.6 mm 오목. 뒤집혀 보이므로 y 로 거울
        if (len(lid_text) > 0) translate([wall + 24, ly(92), -e]) mirror([0, 1, 0]) linear_extrude(0.6 + e)
            text(lid_text, size = 9, font = "Liberation Sans:style=Bold", halign = "left", valign = "center");
    }
}

module led_rails() {
    // 기판 긴 변 두 곳에 ㄷ 자 레일. 설치하면 기판이 레일 턱 위에 얹혀 LED 가 창 바로 밑에 온다.
    // 기판은 +X 쪽 열린 끝에서 밀어 넣는다.
    c = [wall + led_center[0], ly(led_center[1])];
    x0 = c[0] - led_pcb[0] / 2 - tol;
    len_x = led_pcb[0] + 2 * tol;
    d = led_standoff + led_pcb_t + tol + 1.2;
    for (s = [-1, 1]) {
        ye = c[1] + s * (led_pcb[1] / 2 + tol);                 // 기판 긴 변 (여유 포함)
        translate([x0 - 2, s < 0 ? ye - 2 : ye, 0]) cube([len_x + 2, 2, d]);            // 옆벽
        translate([x0 - 2, s < 0 ? ye - 2 : ye - 1.5, led_standoff + led_pcb_t + tol])
            cube([len_x + 2, 3.5, 1.2]);                                                 // 기판 받침 턱 (1.5 mm 걸침)
    }
    translate([x0 - 2, c[1] - led_pcb[1] / 2 - tol - 2, 0]) cube([2, led_pcb[1] + 2 * tol + 4, d]);   // -X 멈춤턱
}

// ------------------------------------------------------------------ 센서 헤드 본체
head_out = [head_in[0] + 2 * wall, head_in[1] + 2 * wall, head_in[2] + floor_t];
amg_x0 = (head_in[0] - amg_pcb[0]) / 2;               // 기판 왼쪽 끝 (헤드 안쪽 좌표)
amg_z0 = (head_in[2] - amg_pcb[1]) / 2;
amg_gap = amg_pkg_h - wall;                            // 앞벽 안쪽 면에서 기판 앞면까지 (센서 앞면이 바깥 면과 맞게)

module head_body() {
    difference() {
        union() {
            difference() {
                rrect(head_out, 3);
                translate([wall, wall, floor_t]) rrect([head_in[0], head_in[1], head_in[2] + 1], 1.5);
            }
            translate([wall, wall, floor_t]) head_inside_parts();
            amg_hood();
            sht_pod_part();
        }
        translate([wall, wall, floor_t]) head_cuts();
        // 후드 안쪽 (나팔 모양으로 넓어짐)
        translate([wall + amg_x0 + amg_pcb[0] / 2 + amg_pkg_off[0], 0, floor_t + amg_z0 + amg_pcb[1] / 2 + amg_pkg_off[1]]) amg_aperture();
    }
}

module head_inside_parts() {
    for (p = head_bosses) translate([p[0], p[1], -e]) cylinder(d = head_boss_d, h = head_in[2] + e);
    // AMG8833 기판 레일 두 개 (위에서 밀어 넣음, 아래 멈춤턱)
    for (side = [0, 1]) {
        xe = side == 0 ? amg_x0 : amg_x0 + amg_pcb[0];            // 기판 끝
        xr = side == 0 ? xe - tol - 1.8 : xe - 1.2;                 // 레일 시작 x
        difference() {
            translate([xr, -e, -e]) cube([1.8 + tol + 1.2, amg_gap + amg_pcb_t + tol + 1.6, head_in[2] - 0.5]);
            // 기판 끝이 들어가는 홈 (아래 멈춤턱 위만)
            translate([side == 0 ? xe - tol : xe - 1.2 - e, amg_gap, amg_z0]) cube([1.2 + tol + e, amg_pcb_t + tol, head_in[2]]);
        }
    }
    // 삼각대 너트 받침
    if (tripod) translate([head_in[0] / 2, head_in[1] / 2 + 4, -e]) cylinder(d = 16, h = 4 + e);
}

module head_cuts() {
    for (p = head_bosses) translate([p[0], p[1], head_in[2] - 10]) cylinder(d = screw_pilot, h = 11);
    // 케이블 그랜드 (뒷벽)
    translate([head_in[0] / 2, head_in[1] + wall / 2, head_gland_z]) rotate([90, 0, 0]) cylinder(d = head_gland_d, h = wall + 2, center = true);
    // SHT31 상자로 가는 선 구멍 (왼쪽 벽)
    translate([-wall / 2, head_in[1] / 2, 8 - floor_t]) rotate([0, 0, 90]) rounded_cut(6, 5, 1);
    // 삼각대 1/4"-20 너트 (맞변 11.1 mm) 와 나사 구멍
    if (tripod) translate([head_in[0] / 2, head_in[1] / 2 + 4, 0]) {
        translate([0, 0, 4 - 5.6]) cylinder(d = (11.1 + 2 * tol) / cos(30), h = 10, $fn = 6);
        translate([0, 0, -floor_t - 1]) cylinder(d = 6.8, h = floor_t + 6);
    }
    // 바닥 배수, 통기 구멍 (앞쪽)
    for (x = [head_in[0] / 2 - 12, head_in[0] / 2 + 12]) translate([x, 12, -floor_t - 1]) cylinder(d = 3, h = floor_t + 2);
}

module amg_aperture() {     // 원점: 앞벽 바깥 면(y=0)의 센서 중심
    a = [amg_pkg[0] + 1, amg_pkg[1] + 1];
    grow = 2 * (hood_depth + 0.01) * tan(hood_angle);
    // 벽을 지나는 곧은 구멍
    translate([0, wall / 2, 0]) cube([a[0], wall + 2, a[1]], center = true);
    // 후드 안쪽 나팔
    hull() {
        translate([0, 0.01, 0]) cube([a[0], 0.02, a[1]], center = true);
        translate([0, -hood_depth - 0.01, 0]) cube([a[0] + grow, 0.02, a[1] + grow], center = true);
    }
}

module amg_hood() {
    a = [amg_pkg[0] + 1, amg_pkg[1] + 1];
    grow = 2 * hood_depth * tan(hood_angle);
    c = [wall + amg_x0 + amg_pcb[0] / 2 + amg_pkg_off[0], floor_t + amg_z0 + amg_pcb[1] / 2 + amg_pkg_off[1]];
    translate([c[0], 0, c[1]]) hull() {
        translate([0, 0.5, 0]) cube([a[0] + 4, 1, a[1] + 4], center = true);
        translate([0, -hood_depth + 0.5, 0]) cube([a[0] + grow + 3.2, 1, a[1] + grow + 3.2], center = true);
    }
}

module sht_pod_part() {    // 헤드 왼쪽에 떨어진 통풍 상자 (윗면 열림, 바닥은 격자). SHT31 은 케이블타이로
    p = sht_pod;
    yc = head_out[1] / 2;
    x1 = -sht_neck;          // 상자 오른쪽 바깥 면
    t = 1.6;
    difference() {
        translate([x1 - p[0], yc - p[1] / 2, 0]) cube([p[0], p[1], p[2]]);
        translate([x1 - p[0] + t, yc - p[1] / 2 + t, t]) cube([p[0] - 2 * t, p[1] - 2 * t, p[2]]);
        // 네 옆면 통풍 홈
        for (z = [4 : 3.2 : p[2] - 3]) {
            translate([x1 - p[0] - 1, yc - p[1] / 2 + 4, z]) cube([p[0] + 2, p[1] - 8, 1.6]);
            translate([x1 - p[0] + 4, yc - p[1] / 2 - 1, z]) cube([p[0] - 8, p[1] + 2, 1.6]);
        }
        // 바닥 격자
        for (x = [x1 - p[0] + 4 : 3.2 : x1 - 4]) translate([x, yc - p[1] / 2 + 4, -1]) cube([1.6, p[1] - 8, t + 2]);
        // 목 구멍
        translate([x1 - t / 2, yc, 8]) cube([t + 2, 6, 5], center = true);
    }
    // 목 (속이 빈 관, 선이 지나감)
    difference() {
        translate([x1 - e, yc - 5, 8 - 4]) cube([sht_neck + 2 * e + 0.5, 10, 8]);
        translate([x1 - 1, yc - 3, 8 - 2.5]) cube([sht_neck + 3, 6, 5]);
    }
}

// ------------------------------------------------------------------ 센서 헤드 뚜껑 (바깥 면을 위로 출력)
module head_lid() {
    c = [wall + head_in[0] / 2, wall + mq2_y];
    difference() {
        union() {
            rrect([head_out[0], head_out[1], lid_t], 3);
            // MQ-2 보호 캡 (옆과 위에 구멍)
            translate([c[0], c[1], lid_t - e]) difference() {
                cylinder(d = mq2_can_d + 2 * tol + 2 + 3.2, h = mq2_cap_h);
                translate([0, 0, -1]) cylinder(d = mq2_can_d + 2 * tol + 2, h = mq2_cap_h - 1.6 + 1);
                for (a = [0 : 30 : 330]) rotate([0, 0, a]) translate([0, -0.9, 2.5]) cube([40, 1.8, mq2_cap_h - 5.5]);   // 옆 홈 (중심을 지나 양쪽)
                for (p = [[0, 0], [6, 0], [-6, 0], [0, 6], [0, -6]]) translate([p[0], p[1], mq2_cap_h - 3]) cylinder(d = 3.2, h = 4);
            }
        }
        for (p = head_bosses) translate([wall + p[0], wall + p[1], -1]) cylinder(d = screw_clear, h = lid_t + 2);
        translate([c[0], c[1], -1]) cylinder(d = mq2_can_d + 2 * tol + 0.4, h = lid_t + 2);
        // 케이블타이 구멍 (MQ-2 기판을 뚜껑 밑에 묶음)
        for (sx = [-1, 1], sy = [-1, 1]) translate([c[0] + sx * mq2_tie_dx, c[1] + sy * mq2_tie_dy, -1])
            linear_extrude(lid_t + 2) square([4, 1.8], center = true);
        // 뚜껑 쪽 통기 홈 (뒤쪽, MQ-2 열이 빠지게)
        for (x = [-12 : 6 : 12]) translate([c[0] + x, wall + head_in[1] - 0.5, -1]) linear_extrude(lid_t + 2) rotate([0, 0, 90]) slot2d(4, 2);
    }
}

// ------------------------------------------------------------------ 맞춤 시험 조각
// 실제 부품에서 맞춤이 중요한 곳만 잘라 낸 조각들 (같은 코드라 치수가 똑같다). 약 1 시간
module fit_test() {
    // A. 제어함 왼쪽 앞 모서리: USB-C 구멍, microSD 홈, Pi 받침 두 개
    intersection() { box_base(); translate([-1, -1, -1]) cube([wall + 72, wall + 40, floor_t + 16]); }
    // B. 뚜껑의 LED 레일, 창, 부저 테, 버튼 구멍
    translate([84 - (wall + 100), -(ly(58)) + 0, 0]) intersection() {
        box_lid(); translate([wall + 100, ly(58), -1]) cube([76, 56, 30]);
    }
    // C. 센서 헤드 앞벽: AMG8833 레일, 창, 후드
    translate([170 - (wall + amg_x0 - 6), 6 + hood_depth + 2, 0]) intersection() {
        head_body();
        translate([wall + amg_x0 - 6, -hood_depth - 2, -1]) cube([amg_pcb[0] + 12, wall + hood_depth + 2 + amg_gap + amg_pcb_t + 5, floor_t + amg_z0 + amg_pcb[1] + 4]);
    }
    // D. 센서 헤드 뚜껑의 MQ-2 구멍, 캡, 케이블타이 구멍
    translate([-(wall + head_in[0] / 2 - 17), 70 - (wall + mq2_y - 17), 0]) intersection() {
        head_lid(); translate([wall + head_in[0] / 2 - 17, wall + mq2_y - 17, -1]) cube([34, 34, 30]);
    }
    // E. 케이블 그랜드 구멍과 삼각대 너트 자리
    translate([45, 70, 0]) difference() {
        union() { rrect([44, 26, 2.4], 3); translate([33, 13, 2.4 - e]) cylinder(d = 16, h = 4); }
        translate([13, 13, -1]) cylinder(d = gland_d, h = 5);
        translate([33, 13, 2.4 + 4 - 5.6]) cylinder(d = (11.1 + 2 * tol) / cos(30), h = 10, $fn = 6);
        translate([33, 13, -1]) cylinder(d = 6.8, h = 10);
    }
}

// ------------------------------------------------------------------ 부품 모형 (미리보기, 간섭 확인용. 실물 대략 크기)
module dummies_box() {       // 제어함 안쪽 좌표 (translate([wall, wall, floor_t]) 안에서)
    g = 0.05;
    // Pi 5 기판과 윗면 부품(쿨러, USB, 이더넷) 높이 17 mm, +X 쪽 USB, 이더넷 2 mm 튀어나옴
    color("Green") translate([pi_pos[0], pi_pos[1], pi_standoff_h + g]) cube([pi_size[0], pi_size[1], pi_pcb_t]);
    color("Silver") translate([pi_pos[0] + 2, pi_pos[1] + 2, pi_standoff_h + pi_pcb_t + g]) cube([pi_size[0], pi_size[1] - 4, 15.5]);
    // microSD (기판 아래, 왼쪽으로 2.5 mm 튀어나옴)
    color("Black") translate([pi_pos[0] - 2.5, pi_pos[1] + pi_size[1] / 2 - 6, pi_standoff_h - 1.4]) cube([14, 12, 1.0]);
    // 브레드보드와 점퍼선 높이
    color("White") translate([(box_in[0] - bb_size[0]) / 2, box_in[1] - 2 - bb_size[1], g]) cube([bb_size[0], bb_size[1], 9.5]);
    color("Orange", 0.4) translate([(box_in[0] - bb_size[0]) / 2 + 2, box_in[1] - 2 - bb_size[1] + 2, 9.6]) cube([bb_size[0] - 4, bb_size[1] - 4, 12]);
    // LED 모듈 (기판 + LED 8.6 mm + 아래 핀 3 mm)
    zl = box_in[2] - led_standoff;
    color("Red") translate([led_center[0] - led_pcb[0] / 2, led_center[1] - led_pcb[1] / 2, zl - led_pcb_t]) cube([led_pcb[0], led_pcb[1], led_pcb_t]);
    color("Red") translate([led_center[0] - led_window[0] / 2 + 3, led_center[1] - 2.5, zl + g]) cube([led_window[0] - 6, 5, 8.6]);
    color("Gray") translate([led_center[0] + led_pcb[0] / 2 - 12, led_center[1] - 6, zl - led_pcb_t - 3]) cube([3, 12, 3]);
    // 부저, 버튼 몸통, 너트
    color("Black") translate([buzzer_pos[0], buzzer_pos[1], box_in[2] - 9.5 - g]) cylinder(d = buzzer_d, h = 9.5);
    if (button_on) color("Silver") translate([button_pos[0], button_pos[1], box_in[2] - 22 - g]) { cylinder(d = 16, h = 22); translate([0, 0, 22 - 3 - g]) cylinder(d = 20, h = 3); }
    // 그랜드 안쪽 너트
    color("DimGray") translate([box_in[0] - 5 - g, gland_yz[0], gland_yz[1]]) rotate([0, 90, 0]) cylinder(d = 19, h = 5);
}

module dummies_head() {      // 헤드 안쪽 좌표
    g = 0.05;
    color("Blue") translate([amg_x0, amg_gap + g, amg_z0 + g]) cube([amg_pcb[0], amg_pcb_t - 2 * g, amg_pcb[1] - 2 * g]);
    color("Black") translate([amg_x0 + amg_pcb[0] / 2 + amg_pkg_off[0] - amg_pkg[0] / 2, amg_gap - amg_pkg_h, amg_z0 + amg_pcb[1] / 2 + amg_pkg_off[1] - amg_pkg[1] / 2])
        cube([amg_pkg[0], amg_pkg_h, amg_pkg[1]]);
    color("Gray") translate([amg_x0 + 3, amg_gap + amg_pcb_t + tol + 1.7, amg_z0 + 1]) cube([amg_pcb[0] - 6, 8, amg_pcb[1] - 2]);     // 뒤쪽 부품, 핀
    // MQ-2: 기판 32 x 22, 금속망 지름 20 높이 16 (기판 윗면 뚜껑 7 mm 아래)
    zt = head_in[2] - 7;
    color("Purple") translate([head_in[0] / 2 - 16, mq2_y - 11, zt - 1.6]) cube([32, 22, 1.6]);
    color("Silver") translate([head_in[0] / 2, mq2_y, zt]) cylinder(d = 19.9, h = 16);
    color("Gray") translate([head_in[0] / 2 - 5, mq2_y + 11 - 3, zt - 1.6 - 8]) cube([10, 2.5, 8]);
    color("DimGray") translate([head_in[0] / 2, head_in[1] - 5 - g, head_gland_z]) rotate([-90, 0, 0]) cylinder(d = 19, h = 5);
}

module clearance_box() { intersection() { box_base(); translate([wall, wall, floor_t]) dummies_box(); } }
module clearance_lid() { intersection() { translate([0, box_out[1], box_out[2] + lid_t]) rotate([180, 0, 0]) box_lid(); translate([wall, wall, floor_t]) dummies_box(); } }
module clearance_head() { intersection() { union() { head_body(); translate([0, 0, head_out[2]]) head_lid(); } translate([wall, wall, floor_t]) dummies_head(); } }

// ------------------------------------------------------------------ 조립 미리보기
module assembly() {
    color("WhiteSmoke") box_base();
    translate([wall, wall, floor_t]) dummies_box();
    color("LightGray", 0.6) translate([0, box_out[1], box_out[2] + lid_t + 25]) rotate([180, 0, 0]) box_lid();
    translate([box_out[0] + 60, 20, 0]) {
        color("Gainsboro") head_body();
        translate([wall, wall, floor_t]) dummies_head();
        color("LightGray", 0.6) translate([0, 0, head_out[2] + 18]) head_lid();
    }
}

if (part == "box_base") box_base();
else if (part == "box_lid") box_lid();
else if (part == "head_body") head_body();
else if (part == "head_lid") head_lid();
else if (part == "fit_test") fit_test();
else if (part == "clearance_box") clearance_box();
else if (part == "clearance_lid") clearance_lid();
else if (part == "clearance_head") clearance_head();
else assembly();
