# fire_detect: 소형 ESS(파워뱅크) 충전 과열 감시 (ess_01, RPi5)

파워뱅크를 충전하는 동안 표면 온도(8x8 열화상, 접촉 프로브 3 개, 적외선 온도계), 주변 온도, 연기를 1 초마다 보고
위험하면 충전 AC 라인(SSR)과 DC 릴레이를 끊고 부저, 신호등 LED 로 알립니다.
판정 결과는 규격 v0.2 의 FireStatus, DeviceHealth 기록으로 남기고 (선택) ROS 2 로 보냅니다.
데이터 형식: [moving-ver/docs/DATA_SPEC.md 4.5](../moving-ver/docs/DATA_SPEC.md).

**감지와 차단은 ROS, 네트워크 없이 이 Pi 하나에서 완결됩니다.** ROS 는 대시보드로 보내는 통로일 뿐입니다.

## 1. 판정

| 단계 | 조건 | LED | 부저 | 충전 |
|---|---|---|---|---|
| 0 정상 | 뜨거운 화소도, 뜨거운 점 센서도 없음 | 녹 | | 허용 |
| 1 주의 | 뜨거운 화소 1~2 개 (국부 발열), 또는 접촉 프로브나 적외선이 주변 + 8 ℃ 초과 | 황 | | 허용 |
| 2 경고 | 뜨거운 화소 3 개 이상 (번지는 중) | 적 점멸 | 간헐 | 허용 (`cut_level: 2` 면 차단) |
| 3 위험 | 연기, 또는 어느 화소든 60 ℃ 이상, 또는 접촉 프로브나 적외선이 60 ℃ 이상 | 적 | 연속 | **차단, 래치** |
| 감시 불가 | 열화상을 10 초 넘게 못 읽음 | 황 점멸 | 짧게 | **차단** |
| 켠 직후 | 시작하고 10 초 (센서가 모두 첫 값을 낼 때까지, `start_hold_s`) | 단계대로 | | **차단** |

- 뜨거운 화소 = 화소 온도 > 주변 온도(SHT31) + 8 ℃. 주변 온도를 못 읽으면 화소 최저값으로 대신합니다.
- 올라갈 때는 조건이 2 초 계속되어야, 내려갈 때는 1.5 ℃ 더 식은 상태가 10 초 계속되어야 합니다 (깜빡임 방지).
- 위험은 래치됩니다. 조건이 사라진 뒤 버튼을 2 초 누르거나 `fire-detect --reset` 으로 풉니다. 아직 뜨거우면 해제 요청을 무시합니다.
  래치는 `/var/lib/fire-detect/latched` 에 남아 **서비스가 다시 시작되거나 Pi 를 재부팅해도 이어집니다** (파일을 직접 지우지 말 것).
- 연기는 MQ-2 전압이 기준선보다 0.3 V 오르면 감지. 기준선은 정상 단계에서만 천천히(10 분 시정수) 학습하고 켠 뒤 3 분은 예열로 판정하지 않습니다.
- 점 센서(접촉 프로브 DS18B20, 적외선 MLX90614)는 열화상이 못 보는 곳(뒷면, 아랫면)과 열화상의 넓은 화소가
  묽게 보는 작은 발열점을 보완합니다. 점 센서만으로는 경고(2)까지 가지 않고, 주의(1)나 위험(3)만 만듭니다.
  기준은 `probe_delta_c`, `probe_abs_limit_c`, `ir_delta_c`, `ir_abs_limit_c` 로 따로 정할 수 있고 비워 두면 열화상과 같습니다.
- 점 센서는 보조라서 끊겨도 충전을 끊지 않습니다. flags(bit4 프로브, bit5 적외선)와 DeviceHealth 의 DEGRADED 로 알립니다.
  다만 **끊기기 직전 값이 뜨거웠으면** 그 단계에서 내려가지 않고 위험 래치도 풀리지 않습니다 (열에 타서 끊긴 것일 수 있음).
  이때는 먼저 그 자리가 왜 뜨거웠는지 확인하고 프로브를 고칩니다. 프로브를 아예 빼려면 원인을 확인한 뒤
  설정의 개수(또는 `ds18b20_ids`)를 고치고 서비스를 다시 시작합니다.
- 규격 v0.2 의 FireStatus 에는 프로브, 적외선 온도 필드가 없습니다. 값은 CSV 기록(`probe1_c`, `ir_c` 열)과
  판정 이유(DeviceHealth.message)로 나가고, 규격에 필드를 넣는 것은 다음 판에서 합니다.
- **기준값(8 ℃, 60 ℃, 0.3 V)은 임시값입니다.** 5장 순서로 정상 충전 기록을 보고 다시 정하십시오.

## 2. 결선 (Raspberry Pi 5, 40핀 헤더)

결선 도면(2026-10-05)의 ESS-01 에서 VOC 센서(AGS02MA)와 가속도계(MPU6050)는 빠졌습니다 (2026-10 결정).
그래서 I2C 버스는 하나(i2c-1)만 쓰고, 접촉 프로브는 1-Wire 하나(BCM 4)에 셋을 나란히 답니다.
센서는 모두 3.3 V 쪽이고, 5 V 는 MQ-2 히터, 릴레이 모듈, 부저와 SSR 구동에만 씁니다.

| 센서 | 연결 | 주소 | 비고 |
|---|---|---|---|
| AMG8833 8x8 열화상 | I2C (40핀 3 SDA, 5 SCL), 3.3 V | 0x69 | 파워뱅크 전체가 화각(60°)에 들어오게 |
| SHT31 온습도 | I2C, 3.3 V | 0x44 | ADR 를 High 로 묶은 모듈은 0x45 |
| MLX90614 적외선 (GY-906) | I2C, 3.3 V | 0x5A | 감시할 면에서 3~5 cm. 무광 테이프 붙인 자리를 보게 |
| ADS1115 ADC | I2C, **3.3 V 로 켤 것**, ADDR -> GND | 0x48 | |
| MQ-2 연기 (5 V 히터) | VCC 5 V, AO -> 10 kΩ -> ADS1115 A0 -> 20 kΩ -> GND | | 분압 2/3, `smoke_divider: 1.5`. **DO 핀은 연결하지 않음 (5 V 출력)** |
| DS18B20 접촉 프로브 x3 (방수형 3선) | 빨강 3.3 V, 검정 GND, 노랑 DQ -> BCM 4 (핀 7). **DQ 와 3.3 V 사이 4.7 kΩ 하나** (키트의 어댑터 기판을 쓰면 기판에 이미 있음) | `28-...` | 상판, 측면, 뒷면에 알루미늄 테이프로 붙임 |
| SSD1306 OLED (선택) | I2C, 3.3 V | 0x3C | |

| 출력 | BCM GPIO (40핀) | 비고 |
|---|---|---|
| AC 충전 SSR (XSSR-DA2440 + 방열판 XW-60) | 17 (11) | 통전 = 충전 허용 |
| DC 차단 릴레이 (4채널 모듈 CH1) | 27 (13) | NO 접점에 결선. 모듈이 Low 에서 붙으면 `relay_active_low: true` |
| 능동 부저 TMB12A05 | 22 (15) | 5 V 부저는 트랜지스터나 릴레이 채널을 거칠 것 |
| 신호등 LED 적, 황, 녹 | 5 (29), 6 (31), 13 (33) | GPIO -> 330 Ω -> LED -> GND |
| 래치 해제 버튼 | 26 (37) | GND 로 누름, 내부 풀업 |

**안전 쪽 설계.** SSR 과 릴레이는 "통전해야 충전" 입니다. 켠 뒤 10 초는 끊어 두고, 프로그램이 끝나면 출력을 끕니다.
프로그램이 멈추거나(systemd watchdog 10 초) 죽어도 systemd 가 `fire-detect --safe-off` 로 출력을 끄고 다시 시작합니다.
Pi 5 커널은 프로세스가 죽어도 GPIO 출력을 그대로 두는 설정(`pinctrl_rp1` 의 `persist_gpio_outputs`)이 기본으로 켜져 있어,
서비스가 시작할 때 이것을 끕니다 (`systemd/fire-detect.service` 의 ExecStartPre, ExecStopPost). Pi 전원이 나가면 출력이 풀려 끊깁니다.
SSR 이 끊는 것은 감지기 자신의 전원이 아니라 감시 대상 파워뱅크의 충전 라인입니다.

전원과 GND 핀 (예): 핀 1 (3.3 V) I2C 센서 5 개, 핀 17 (3.3 V) DS18B20 과 4.7 kΩ, 핀 2 (5 V) MQ-2,
핀 4 (5 V) 릴레이 모듈, 부저와 SSR 트랜지스터. GND 는 6, 9, 14, 20, 25, 30, 34, 39 어느 것이든 같습니다.

**하드웨어 주의**
- Pi 의 GPIO 는 3.3 V 전용입니다. 풀업은 모두 3.3 V 로 (DS18B20 4.7 kΩ, I2C 모듈). 프로브 키트의 어댑터 기판도
  VCC 를 3.3 V 에 꽂습니다. MQ-2 의 DO 와 5 V 로 켠 모듈의 신호선을 GPIO 에 직접 잇지 않습니다.
- DS18B20 은 3 선(일반 전원)으로 씁니다. 기생 전원(2 선)은 85 ℃ 초기값 오류가 잦습니다.
- I2C 모듈마다 풀업 저항이 있어 다섯 개를 다 달면 풀업이 세집니다. 읽기 오류가 잦으면 선을 짧게(30 cm 안쪽) 하고
  일부 모듈의 풀업을 뗍니다. 버스 속도는 기본 100 kHz 그대로 둡니다 (MLX90614 최대 100 kHz).
- 흔한 5 V 릴레이 모듈은 3.3 V 신호로는 확실히 떨어지지 않는 제품이 있습니다. `hw_check.py outputs` 에서 꺼지지 않으면
  JD-VCC 점퍼를 빼고 VCC 를 3.3 V, JD-VCC 를 5 V 로 나누거나 트랜지스터로 구동합니다.
- SSR 입력은 3~32 V 라 3.3 V 로도 켜지지만 여유가 적습니다. 불안하면 NPN 트랜지스터(예: 2N2222, 베이스에 1 kΩ,
  베이스와 GND 사이 10 kΩ)로 SSR 에 5 V 를 겁니다. 논리는 그대로(High = 통전, `ssr_active_low: false`)이고
  Pi 가 꺼지거나 부팅 중이면 10 kΩ 때문에 꺼진 쪽(차단)에 머뭅니다. 부저(5 V 약 30 mA)도 같은 회로로 켭니다.

**1-Wire 켜기**: `/boot/firmware/config.txt` 에 `dtoverlay=w1-gpio` (기본 BCM 4) 를 넣고 재부팅합니다.
Pi 5 에서 Raspberry Pi OS 는 이것을 1-Wire 시간 보정판인 `w1-gpio-pi5` 로 알아서 바꿔 씁니다.
Ubuntu 는 `/boot/firmware/overlays/w1-gpio-pi5.dtbo` 가 있으면 `dtoverlay=w1-gpio-pi5` 를 직접 적습니다.
재부팅 뒤 `ls /sys/bus/w1/devices/` 에 `28-` 로 시작하는 것이 셋 보여야 합니다.

**프로브 위치 고정**: 설정의 `ds18b20_ids` 를 비워 두면 찾은 ID 를 정렬한 순서가 프로브 1, 2, 3 이라,
하나가 빠진 채 켜지면 번호가 밀립니다. `hw_check.py w1 --n 20` (약 50 초)을 돌리며 프로브를 하나씩 손으로 쥐어 어느 ID 가
어디인지 확인하고 `ds18b20_ids: [상판 ID, 측면 ID, 뒷면 ID]` 처럼 적어 두십시오.
배기구 바로 앞은 정상 충전 중에도 뜨거우니 처음에는 배기구에서 떨어진 케이스 면에 붙이고, 5장 순서로 기준을 정합니다.

## 3. 설치 (RPi5)

```bash
sudo apt install python3-venv python3-gpiozero python3-lgpio python3-smbus2 python3-yaml i2c-tools
# /boot/firmware/config.txt 에 dtparam=i2c_arm=on, dtoverlay=w1-gpio 후 재부팅
# i2cdetect -y 1 에 44 48 5a 69 (3c), ls /sys/bus/w1/devices/ 에 28-... 세 개가 보여야 함
cd ~/fire_detect
python3 -m venv --system-site-packages .venv
.venv/bin/pip install .            # OLED 를 쓰면 .venv/bin/pip install luma.oled
sudo mkdir -p /etc/fire-detect && sudo cp config.example.yaml /etc/fire-detect/config.yaml
sudo cp systemd/fire-detect.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now fire-detect
journalctl -u fire-detect -f
```

처음 세팅할 때는 부품을 하나씩 확인합니다. 서비스가 돌고 있으면 먼저 `sudo systemctl stop fire-detect`.

```bash
.venv/bin/python tools/hw_check.py i2c              # I2C 센서 4 종 응답 (AMG8833, SHT31, ADS1115, MLX90614)
.venv/bin/python tools/hw_check.py w1 --n 20        # 접촉 프로브 개수, 약 50 초 동안 온도 표시 (하나씩 쥐어 위치 구별)
.venv/bin/python tools/hw_check.py sensors --n 10   # 값이 말이 되는지 (MQ-2 는 3 분 예열)
.venv/bin/python tools/hw_check.py outputs          # LED, 부저, DC 릴레이, SSR 을 하나씩 (릴레이, SSR 은 꺼지는지도). SSR 의 AC 쪽을 뺀 뒤에만
.venv/bin/python tools/hw_check.py button           # 래치 해제 버튼
```

보드에서 Claude Code 로 세팅할 때는 저장소 폴더에서 `claude` 를 실행하면 `CLAUDE.md` 의 안전 규칙과 순서를 따릅니다.

## 4. 실행

```bash
fire-detect --config /etc/fire-detect/config.yaml          # 보통은 systemd 가 실행
fire-detect --reset                                          # 위험 래치 해제 요청
fire-detect --config /etc/fire-detect/config.yaml --safe-off # 출력을 모두 끄고 끝냄 (서비스가 끝날 때 systemd 가 부름)
fire-detect --config ... --ros                               # /fire/ess_01/status, /health/ess_01 (ROS 2 + odor_msgs 필요)

# 하드웨어 없이 (가짜 센서, 가짜 출력. 실제 드라이버 코드가 가짜 레지스터 위에서 돔)
fire-detect --simulate overheat --speed 0 --duration 620 --reset-at 560 --out /tmp/fire
fire-detect --simulate normal --speed 0 --duration 3600 --out /tmp/fire_normal
fire-detect --simulate sensor_loss --speed 0 --duration 200 --out /tmp/fire_loss
fire-detect --simulate hidden_heat --speed 0 --duration 620 --reset-at 560 --out /tmp/fire_hidden
```

`overheat` 시나리오: 143 초 주의 -> 167 초 경고 -> 254 초 위험(60 ℃, 충전 차단, 래치) -> 288 초 연기 확인 -> 560 초 해제 버튼 -> 정상.
`hidden_heat` 시나리오: 열화상에는 안 보이는 뒷면이 데워져 접촉 프로브 3 만 오름. 143 초 주의 -> 254 초 위험(차단, 래치) -> 560 초 해제.

남기는 파일 (`log.dir`, 날짜는 UTC): `fire_YYYYmmdd.csv` (1 초 판정, 접촉 프로브와 적외선 값 포함), `thermal_YYYYmmdd.csv` (1 초 화소 64 개, 하루 약 30 MB),
`fire_YYYYmmdd.jsonl` (fire_status 10 초마다 + 바뀔 때, device_health 10 초마다). 60 일 지난 파일은 지웁니다.

## 5. 기준값 정하기

1. 설정은 기본값 그대로 두고, 평소처럼 파워뱅크를 여러 번 충전하면서 며칠 기록합니다.
2. `python3 tools/analyze_log.py ~/fire_logs/fire_*.csv`
3. 출력되는 정상 분포와 제안값(`delta_c`, `abs_limit_c`, `smoke_dv`, 그리고 기록에 있으면 `probe_*`, `ir_*`)을 `/etc/fire-detect/config.yaml` 의 `alarm:` 에 넣고
   `sudo systemctl restart fire-detect`.
4. 다시 며칠 돌려 오경보가 없는지 봅니다 (analyze_log.py 가 기록 중의 경보를 나열합니다).

카메라는 파워뱅크 전체가 화각(60°)에 들어오게 달고, 반사가 심한 금속면은 마스킹 테이프 등으로 덮으면 온도가 정확해집니다.

## 6. 시험

```bash
pip install pytest "jsonschema>=4.18"
python3 -m pytest tests      # moving-ver 가 옆 폴더에 있으면 기록을 규격 스키마로도 검사
```

- `test_drivers.py`: AMG8833 화소, 서미스터 형식, SHT31 CRC, ADS1115 설정 워드, MLX90614 PEC(데이터시트 예),
  DS18B20 w1_slave 해석(CRC, 모두 0, 85 ℃ 초기값), 프로브 찾기와 빠진 프로브, 읽기 스레드
- `test_alarm.py`: 단계 상승, 잡음 무시, 히스테리시스, 래치와 해제, 연기 기준선, 센서 끊김 차단,
  점 센서(주의, 위험, 따로 정한 기준, 끊김은 차단 안 함, 뜨거울 때 끊기면 단계와 래치 유지)
- `test_app.py`: 시나리오 전체 (출력, 파일, 스키마, 뒷면 발열), CSV 열 바뀜, 프로브 빠짐 = DEGRADED, systemd 알림, 설정 파일
- `test_hw_check.py`: 보드 점검 도구 (가짜 하드웨어, AC 확인 없이는 출력을 켜지 않음, 끝나면 모두 끔, 프로브 개수와 ID)
