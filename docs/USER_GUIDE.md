# ESS-01 화재 감지기 사용 가이드 (fire_detect)

- 저장소: https://github.com/selim-drone-proj/fire_detect
- 작성 기준: 2026-11-15, 저장소 `main` (PR #1~#7 의 내용이 모두 합쳐진 상태)
- 대상 장치: `ess_01` (Raspberry Pi 5)

---

## 1. 개요

ESS-01 은 소형 ESS(파워뱅크)를 충전하는 동안 과열과 연기를 1 초 주기로 감시하는 장치이다.
위험으로 판정하면 충전 라인(AC SSR, DC 릴레이)을 차단하고 신호등 LED 와 부저로 알린다.

- **감지와 차단은 Pi 한 대에서 완결된다.** 네트워크나 ROS 가 끊겨도 감시와 차단은 계속된다.
- 판정 결과는 데이터 규격 v0.2 의 `fire_status`, `device_health` 기록으로 남는다.
- 선택 기능으로 서버(`/api/ingest`)에 HTTP 로 송신하거나 ROS 2 토픽으로 발행한다.

### 1.1 구성 형태 두 가지

| 구성 | 전원 | 차단 출력 | 설정 파일 | 문서 |
|---|---|---|---|---|
| 보조배터리 벤치 구성 (현재 시험 중) | USB-C 보조배터리 | 없음 (판정·기록·LED·부저만) | `config.battery.yaml` | `docs/BATTERY_BENCH.md` |
| 220 V 구성 (최종) | 220 V, SMPS | AC SSR, DC 릴레이 | `config.example.yaml` | `README.md`, `CLAUDE.md` |

두 구성은 같은 프로그램(`fire-detect`)을 쓰고 설정 파일만 다르다.

---

## 2. 저장소 이력

| PR | 내용 |
|---|---|
| #1 | 소프트웨어 첫 업로드 (v0.2) |
| #2 | 보드 세팅용 CLAUDE.md, 점검 도구 `hw_check.py` |
| #3 | 접촉 프로브(DS18B20 x3), 적외선 온도계(MLX90614) |
| #4 | 안전 보강 (비정상 종료 시 출력 끄기, 래치 유지, 켠 직후 10 초 차단) |
| #5 | 보조배터리 벤치 구성 (센서 읽기, 기록, 그래프) |
| #6 | 케이스 3D 프린트 파일, 2D 도면 |
| #7 | 서버 송신 (`/api/ingest`), 벤치 전체 기능 시험 `bench_test.py` |

PR #3~#5, #7 은 이어진(stacked) 브랜치로 병합되어 한때 `main` 에 빠져 있었다.
이 문서를 넣은 PR 에서 마지막 커밋(`89dac8c`)까지 `main` 으로 합쳤으므로, 그 PR 이 병합된 뒤에는 `main` 만 받으면 된다.

---

## 3. 하드웨어 구성

### 3.1 센서

| 센서 | 역할 | 연결 | 주소 / 핀 |
|---|---|---|---|
| AMG8833 8x8 열화상 | 표면 온도 분포 (주 감시) | I2C, 3.3 V | 0x69 (AD_SELECT 를 GND 에 묶으면 0x68) |
| SHT31 온습도 | 주변 온도 (판정 기준선) | I2C, 3.3 V | 0x44 |
| ADS1115 ADC | MQ-2 아날로그 전압 읽기 | I2C, **3.3 V**, ADDR → GND | 0x48 |
| MQ-2 연기 | 연기·가연성 가스 | VCC 5 V, AO → 10 kΩ → ADS1115 A0 → 20 kΩ → GND | 분압 2/3, `smoke_divider: 1.5` |
| MLX90614 (GY-906) 적외선 (선택) | 한 점의 표면 온도 | I2C, 3.3 V | 0x5A |
| DS18B20 접촉 프로브 x3 (선택) | 상판·측면·뒷면 접촉 온도 | 1-Wire, DQ → BCM 4 (핀 7), DQ–3.3 V 사이 4.7 kΩ | `28-...` |
| SSD1306 OLED (선택) | 상태 표시 | I2C, 3.3 V | 0x3C |

- VOC 센서(AGS02MA)와 가속도계(MPU6050)는 2026-10 결정으로 제외하였다. I2C 버스는 `i2c-1` 하나만 쓴다.
- MQ-2 의 **DO 핀은 연결하지 않는다** (5 V 출력이라 Pi GPIO 를 손상시킬 수 있다).

### 3.2 출력

| 출력 | BCM GPIO (40핀 번호) | 비고 |
|---|---|---|
| AC 충전 SSR (XSSR-DA2440 + 방열판 XW-60) | 17 (11) | 통전 = 충전 허용. 220 V 구성만 |
| DC 차단 릴레이 (4채널 모듈 CH1) | 27 (13) | NO 접점. 220 V 구성만 |
| 능동 부저 TMB12A05 (5 V) | 22 (15) | NPN 트랜지스터(2N3904 등)를 거쳐 구동 |
| 신호등 LED 적·황·녹 | 5 (29), 6 (31), 13 (33) | 모듈에 저항이 없으면 330 Ω 직렬 |
| 래치 해제 버튼 | 26 (37) | GND 로 누름, 내부 풀업. 220 V 구성만 |

### 3.3 전원 핀

| Pi 핀 | 용도 |
|---|---|
| 1 (3.3 V) | I2C 센서 전체 |
| 17 (3.3 V) | DS18B20 과 4.7 kΩ 풀업 |
| 2 (5 V) | MQ-2 히터 |
| 4 (5 V) | 릴레이 모듈, 부저, SSR 구동 트랜지스터 |
| 6, 9, 14, 20, 25, 30, 34, 39 | GND (어느 것이든 같음) |

### 3.4 하드웨어 주의 사항

- Pi GPIO 는 3.3 V 전용이다. ADS1115 를 5 V 로 켜면 SDA·SCL 이 5 V 가 되어 Pi 가 손상될 수 있다.
- 브레드보드의 3.3 V 레일과 5 V 레일을 혼동하지 않도록 5 V 쪽에 테이프로 표시한다.
- **SDA·SCL 선에 표시해 둔다.** 2026-11-01 에 두 선이 뒤바뀌어 `i2cdetect` 표가 비어 있었던 사례가 있다.
- I2C 선은 30 cm 이내로 둔다. 버스 속도는 기본 100 kHz 를 유지한다 (MLX90614 최대 100 kHz).
- DS18B20 은 3 선(일반 전원)으로 쓴다. 기생 전원(2 선)은 85 ℃ 초기값 오류가 잦다.
- 결선을 바꿀 때는 반드시 전원(보조배터리)을 뺀다.

---

## 4. 판정 로직

| 단계 | 조건 | LED | 부저 | 충전 |
|---|---|---|---|---|
| 0 정상 | 뜨거운 화소·뜨거운 점 센서 없음 | 녹 | - | 허용 |
| 1 주의 | 뜨거운 화소 1~2 개, 또는 프로브·적외선이 주변 + 8 ℃ 초과 | 황 | - | 허용 |
| 2 경고 | 뜨거운 화소 3 개 이상 | 적 점멸 | 2 초마다 0.2 초 | 허용 (`cut_level: 2` 면 차단) |
| 3 위험 | 연기, 또는 어느 화소·프로브·적외선이든 60 ℃ 이상 | 적 | 연속 | **차단, 래치** |
| 감시 불가 | 열화상을 10 초 넘게 읽지 못함 | 황 점멸 | 5 초마다 0.1 초 | **차단** |
| 켠 직후 | 시작 후 10 초 (`start_hold_s`) | 단계대로 | - | **차단** |

- **뜨거운 화소**: 화소 온도 > 주변 온도(SHT31) + 8 ℃. SHT31 을 읽지 못하면 화소 최저값을 주변 온도로 쓴다.
- **깜빡임 방지**: 단계 상승은 조건이 2 초 유지되어야 하고, 하강은 1.5 ℃ 더 식은 상태가 10 초 유지되어야 한다.
- **연기**: MQ-2 전압이 기준선보다 0.3 V 오르면 감지한다. 기준선은 정상 단계에서만 10 분 시정수로 학습하며, 켠 뒤 3 분은 예열로 판정하지 않는다.
- **래치**: 위험은 사람이 해제할 때까지 유지된다. 래치 상태는 `/var/lib/fire-detect/latched` 에 기록되어 재부팅 뒤에도 이어진다. 해제는 버튼 2 초 누름 또는 `fire-detect --reset` 이며, 아직 뜨거우면 해제 요청을 무시한다.
- **점 센서(DS18B20, MLX90614)** 는 보조 센서이다. 끊겨도 충전을 차단하지 않고 `DEGRADED` 로 알린다. 단, 끊기기 직전 값이 뜨거웠으면 단계와 래치를 유지한다.
- **기준값(8 ℃, 60 ℃, 0.3 V)은 임시값이다.** 정상 충전 기록으로 다시 정해야 한다 (8장).

### 4.1 안전 설계 (Fail-safe)

- SSR 과 릴레이는 "통전해야 충전" 방식이다. 프로그램 종료·정지·Pi 전원 상실 시 충전이 끊긴다.
- 루프가 10 초 이상 멈추면 systemd watchdog 이 프로세스를 끝내고 `fire-detect --safe-off` 로 출력을 끈 뒤 다시 시작한다.
- Pi 5 커널의 GPIO 출력 유지 설정(`persist_gpio_outputs`)을 서비스 시작 시 끈다.
- GPIO 를 열지 못하면 감시와 기록만 하고 충전은 켜지 않으며 `DeviceHealth` 를 `ERROR` 로 남긴다.
- SSR 이 끊는 대상은 감지기 자신의 전원이 아니라 **감시 대상 파워뱅크의 충전 라인**이다.

---

## 5. 설치 (Raspberry Pi 5)

### 5.1 OS 설정과 설치

```bash
sudo apt install python3-venv python3-gpiozero python3-lgpio python3-smbus2 python3-yaml i2c-tools
# /boot/firmware/config.txt 에 아래를 넣고 재부팅
#   dtparam=i2c_arm=on
#   dtoverlay=w1-gpio          # DS18B20 을 쓸 때만

git clone https://github.com/selim-drone-proj/fire_detect.git ~/fire_detect
cd ~/fire_detect
python3 -m venv --system-site-packages .venv
.venv/bin/pip install .                  # OLED 를 쓰면 .venv/bin/pip install luma.oled
```

### 5.2 연결 확인

```bash
sudo i2cdetect -y 1          # 44 48 69 (적외선을 달면 5a, OLED 를 달면 3c)
ls /sys/bus/w1/devices/      # DS18B20 을 달면 28-... 세 개
```

### 5.3 부품별 점검 (`tools/hw_check.py`)

서비스가 돌고 있으면 먼저 `sudo systemctl stop fire-detect` 로 끈다.
벤치 구성에서는 모든 명령에 `--config config.battery.yaml` 을 붙인다.

```bash
.venv/bin/python tools/hw_check.py i2c              # I2C 센서 응답
.venv/bin/python tools/hw_check.py w1 --n 20        # 접촉 프로브 개수, 온도 (하나씩 쥐어 위치 구별)
.venv/bin/python tools/hw_check.py sensors --n 10   # 값이 타당한지 (MQ-2 는 3 분 예열)
.venv/bin/python tools/hw_check.py outputs          # LED, 부저, 릴레이, SSR 을 하나씩. SSR 의 AC 쪽을 뺀 뒤에만
.venv/bin/python tools/hw_check.py button           # 래치 해제 버튼
```

### 5.4 서비스 등록 (부팅 시 자동 시작)

```bash
sudo mkdir -p /etc/fire-detect
sudo cp config.example.yaml /etc/fire-detect/config.yaml     # 벤치 구성이면 config.battery.yaml 을 복사
sudo cp systemd/fire-detect.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now fire-detect
journalctl -u fire-detect -f                                 # 동작 기록 보기
```

---

## 6. 보조배터리 벤치 구성 사용법

### 6.1 전원 조건

- USB-C 출력 **5 V 3 A 이상**, 케이블도 3 A 용을 쓴다.
- 소비 전력은 약 4~5 W 이다. 10,000 mAh 는 약 6 시간, 20,000 mAh 는 약 12 시간으로 추정한다 (실측으로 확인 필요).
- `vcgencmd get_throttled` 가 `throttled=0x0` 이면 전압이 정상이다. 입력 전압은 `device_health.supply_v` 에 10 초마다 남는다.
- 충전과 사용을 동시에 하는 패스스루 사용은 피한다 (출력이 잠깐 끊겨 Pi 가 재부팅될 수 있다).
- 끌 때는 `sudo poweroff` 를 쓴다.
- 기록 시각은 UTC 이다. 시작 전에 인터넷에 한 번 연결해 `timedatectl` 이 `System clock synchronized: yes` 인지 확인한다.

### 6.2 MQ-2 준비

- 새 MQ-2 는 **24~48 시간 번인**이 필요하다. MQ-2 의 VCC·GND 만 USB 5 V 에 이어 켜 둔다.
- MQ-2 단독 확인: `.venv/bin/python tools/mq2_check.py --config config.battery.yaml --minutes 30`

### 6.3 실행과 실시간 보기

```bash
# 창 1: 읽기, 판정, 기록 (Ctrl+C 로 종료)
.venv/bin/fire-detect --config config.battery.yaml

# 창 2: 실시간 값 보기
.venv/bin/python tools/live_view.py           # 1 초마다 한 줄
.venv/bin/python tools/live_view.py --grid    # 열화상 8x8 숫자 (* 는 뜨거운 화소)
```

### 6.4 그래프와 분석

```bash
sudo apt install -y python3-matplotlib
.venv/bin/python tools/plot_log.py                 # 오늘 전체 → ~/fire_logs/plots/*.png
.venv/bin/python tools/plot_log.py --last 30       # 마지막 30 분
.venv/bin/python tools/plot_log.py --day 20261101  # 특정 날짜
```

노트북에서 분석할 때는 Pi 의 `~/fire_logs` 폴더를 복사한 뒤 `python tools/plot_log.py --dir ./fire_logs` 를 실행한다.

---

## 7. 시험

### 7.1 전체 기능 시험 (`tools/bench_test.py`, 약 10~15 분)

스크립트가 단계별로 안내하고 판정 결과를 자동으로 확인한다. LED·부저는 사람이 보고 y/n 으로 답한다.
fire-detect 가 돌고 있으면 먼저 끈다.

```bash
.venv/bin/python tools/bench_test.py                  # 모든 단계
.venv/bin/python tools/bench_test.py --skip hot,gas   # 뜨거운 물, 라이터 가스 단계 제외
```

| 단계 | 사람이 할 것 | 자동 확인 항목 |
|---|---|---|
| env | - | Pi 입력 전압, 시각 동기화, GPIO |
| sensors | - | AMG8833, SHT31, ADS1115 응답 |
| baseline | 열화상을 빈 벽 쪽으로 | 30 초 정상 유지, 값 타당성, 녹색 LED |
| caution | 손바닥 20~30 cm | 25 초 안에 주의, 황색 LED |
| warning | 손바닥 5~10 cm | 25 초 안에 경고, 적색 점멸, 부저 간헐 |
| clear | 손을 치움 | 45 초 안에 정상 복귀 |
| hot | 끓인 물 머그컵 10 cm | 위험 래치, 뜨거울 때 해제 무시, 식은 뒤 해제 |
| gas | 라이터 가스 (불 없이) | 예열 3 분 뒤 연기 위험, 가스 제거 뒤 해제 |
| logs | - | CSV, jsonl, 그래프 PNG 생성 |

결과는 `~/fire_logs/bench_<UTC시각>/` 에 `report.md`, 기록, 그래프로 남는다.

### 7.2 하드웨어 없이 시험 (시뮬레이션)

실제 드라이버 코드가 가짜 레지스터 위에서 동작한다.

```bash
fire-detect --simulate overheat    --speed 0 --duration 620 --reset-at 560 --out /tmp/fire
fire-detect --simulate normal      --speed 0 --duration 3600 --out /tmp/fire_normal
fire-detect --simulate sensor_loss --speed 0 --duration 200 --out /tmp/fire_loss
fire-detect --simulate hidden_heat --speed 0 --duration 620 --reset-at 560 --out /tmp/fire_hidden
```

- `overheat`: 143 초 주의 → 167 초 경고 → 254 초 위험(60 ℃, 차단, 래치) → 288 초 연기 확인 → 560 초 해제 → 정상
- `hidden_heat`: 열화상에 보이지 않는 뒷면 발열을 접촉 프로브 3 이 감지. 143 초 주의 → 254 초 위험 → 560 초 해제

### 7.3 단위 시험

```bash
pip install pytest "jsonschema>=4.18"
python3 -m pytest tests
```

드라이버(CRC, 레지스터 형식), 판정(단계 상승·히스테리시스·래치·연기 기준선·센서 끊김), 앱 전체 시나리오, 점검 도구, 서버 송신을 검사한다.

---

## 8. 기준값 정하기

1. 기본 설정으로 평소처럼 파워뱅크를 여러 번 충전하면서 며칠 기록한다.
2. `python3 tools/analyze_log.py ~/fire_logs/fire_*.csv` 를 실행한다.
3. 출력된 정상 분포와 제안값(`delta_c`, `abs_limit_c`, `smoke_dv`, `probe_*`, `ir_*`)을 설정 파일의 `alarm:` 에 넣고 `sudo systemctl restart fire-detect` 를 실행한다.
4. 다시 며칠 기록하여 오경보가 없는지 확인한다.

설치 시 열화상 카메라는 파워뱅크 전체가 화각(60°) 안에 들어오게 두고, 반사가 심한 금속면은 마스킹 테이프로 덮는다.

---

## 9. 기록 파일과 서버 송신

### 9.1 기록 파일 (`~/fire_logs`, 날짜는 UTC, 60 일 보관)

| 파일 | 내용 |
|---|---|
| `fire_YYYYmmdd.csv` | 1 초마다 판정 단계, 주변 온습도, 열화상 최고·평균·최저, 뜨거운 화소 수, 연기 전압과 기준선, 프로브·적외선 값, 판정 이유 |
| `thermal_YYYYmmdd.csv` | 1 초마다 화소 64 개 (하루 약 30 MB) |
| `fire_YYYYmmdd.jsonl` | 규격 v0.2 `fire_status` (10 초마다와 단계 변경 시), `device_health` (10 초마다: 상태, 입력 전압, CPU 온도) |

### 9.2 서버 송신 (선택)

- 설정 `ingest.url` 이 있으면 `fire_status` 를 1 초마다, `device_health` 를 10 초마다 서버로 HTTP POST 한다.
- 송신 주소: `http://221.159.102.58:8070/api/ingest` (Bearer 토큰 인증)
- 송신은 별도 스레드에서 수행하며 감지·차단과 무관하다. 서버가 끊기면 최근 600 건(약 10 분)을 보관했다가 다시 보낸다.
- 토큰 파일이 없으면 송신하지 않고 감시만 한다. 시뮬레이션은 송신하지 않는다.
- `device_id` 가 서버 대시보드의 시험체 ID 이므로 장치마다 다르게 정한다.

```bash
# 토큰은 서버 담당자에게 따로 받아 보드 터미널에서만 넣는다 (채팅·커밋 금지)
mkdir -p ~/.config/fire-detect && install -m 600 /dev/null ~/.config/fire-detect/ingest_token
nano ~/.config/fire-detect/ingest_token
.venv/bin/fire-detect --config config.battery.yaml   # 시작 문구에 "서버 송신: http://..." 가 나오면 정상
```

송신 오류는 journal 에 "서버 송신 오류: ..." 로, 복구는 "서버 송신 정상" 으로 남는다.

---

## 10. 케이스 (3D 프린트, 2026-11-04)

보조배터리 벤치 구성용 케이스이다. **제어함**과 **센서 헤드** 두 부분으로 나뉘고 보조배터리는 바깥에 둔다.
설계 원본은 `hardware/case/ess01_case.scad` (OpenSCAD, 파라메트릭)이다.

| 파일 | 부품 | 크기 (mm) |
|---|---|---|
| `stl/ess01_fit_test.stl` | **먼저 출력할 맞춤 시험 조각 5 개** | 208 x 104 x 31 |
| `stl/ess01_box_base.stl` | 제어함 본체 (Pi 5, 브레드보드 MB-102) | 211 x 124 x 44 |
| `stl/ess01_box_lid.stl` | 제어함 뚜껑 (LED 창, 부저, 버튼 구멍, 배기구) | 187 x 124 x 15 |
| `stl/ess01_head_body.stl` | 센서 헤드 (AMG8833 창, SHT31 통풍 상자, 삼각대 너트 자리) | 81 x 50 x 36 |
| `stl/ess01_head_lid.stl` | 헤드 뚜껑 (MQ-2 구멍과 보호 캡) | 49 x 47 x 14 |

- **출력 설정**: PETG 권장 (MQ-2 금속망이 50 ℃ 이상으로 가열됨), 층 높이 0.2 mm, 벽 3 줄 이상, 채움 20~30 %, 서포트 없음
- **2D 도면**: `hardware/case/drawings/out/` 에 DXF 4 장과 A3 PDF (`ESS01-CASE_도면_A3.pdf`)
- **준비물**: M3 x 8 나사 8, M2.5 x 6 나사 4, PG9 케이블 그랜드 2, 8 심 랜선 1 m 이하, 케이블타이 3
- **설치 위치**: 센서 헤드를 감시 대상 앞쪽 위 약 0.5 m 에 두고 비스듬히 내려다보게 한다.
- **주의**: AMG8833 창 앞을 테이프·필름·투명 판으로 막지 않는다 (적외선이 투과하지 못함). 뚜껑을 닫은 뒤 Pi 온도(`vcgencmd measure_temp`)가 80 ℃ 에 가까우면 냉각을 보강한다.

---

## 11. 문제 해결

| 증상 | 확인할 곳 |
|---|---|
| `i2cdetect` 표가 전부 `--` | **SDA·SCL 뒤바뀜** (두 선을 바꿔 꽂아 봄), 그다음 핀 3·5, 끊어진 점퍼선 |
| `i2cdetect` 에 48 없음 | ADS1115 VDD 3.3 V, GND, ADDR 이 GND 인지 (VDD 에 이으면 0x49) |
| ADS1115 A0 가 3.3 V 근처에 고정 | 분압 저항 누락. 즉시 전원을 빼고 결선 확인 |
| MQ-2 전압이 거의 0 V | MQ-2 VCC 가 5 V 레일인지, AO 선, 10 kΩ |
| 가스를 대도 연기 전압이 오르지 않음 | 예열 부족 (3 분 이상), 또는 AO 대신 DO 를 연결함 |
| 점검에서 MLX90614, DS18B20 이 "실패" | `--config config.battery.yaml` 을 빠뜨림 |
| 프로브 번호가 바뀜 | 설정 `ds18b20_ids` 에 위치별 ID 를 고정 |
| 릴레이가 꺼지지 않음 | 5 V 릴레이 모듈이 3.3 V 신호에 반응하지 않음. JD-VCC 분리 또는 트랜지스터 구동 |
| Ubuntu 에서 GPIO 가 열리지 않음 | `gpiodetect` 로 `pinctrl-rp1` 칩 번호 확인 후 udev 규칙 추가 (`docs/BATTERY_BENCH.md` 2-2 다) |

---

## 12. 남은 일

1. 보드에서 `tools/bench_test.py` 전체 기능 시험을 돌리고 결과(`report.md`)를 남긴다.
2. 서버 송신을 보드에서 확인한다 (토큰 설치 후 journal 에 "서버 송신 정상").
3. 정상 충전 기록을 며칠 모아 임시 기준값(8 ℃, 60 ℃, 0.3 V)을 다시 정한다 (8장).
4. 맞춤 시험 조각으로 케이스 치수를 확인한 뒤 본 부품을 출력한다.
5. 220 V 구성(SSR, DC 릴레이, 래치 해제 버튼)으로 전환 시 `README.md` 와 `CLAUDE.md` 의 세팅 순서 전체(출력 시험, 서비스, 비상 끄기 확인)를 따른다.
