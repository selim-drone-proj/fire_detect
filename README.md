# fire_detect: 소형 ESS(파워뱅크) 충전 과열 감시 (ess_01, RPi5)

파워뱅크를 충전하는 동안 표면 온도(8x8 열화상), 주변 온도, 연기를 1 초마다 보고
위험하면 충전 AC 라인(SSR)과 DC 릴레이를 끊고 부저, 신호등 LED 로 알립니다.
판정 결과는 규격 v0.2 의 FireStatus, DeviceHealth 기록으로 남기고 (선택) ROS 2 로 보냅니다.
데이터 형식: [moving-ver/docs/DATA_SPEC.md 4.5](../moving-ver/docs/DATA_SPEC.md).

**감지와 차단은 ROS, 네트워크 없이 이 Pi 하나에서 완결됩니다.** ROS 는 대시보드로 보내는 통로일 뿐입니다.

## 1. 판정

| 단계 | 조건 | LED | 부저 | 충전 |
|---|---|---|---|---|
| 0 정상 | 뜨거운 화소 없음 | 녹 | | 허용 |
| 1 주의 | 뜨거운 화소 1~2 개 (국부 발열) | 황 | | 허용 |
| 2 경고 | 뜨거운 화소 3 개 이상 (번지는 중) | 적 점멸 | 간헐 | 허용 (`cut_level: 2` 면 차단) |
| 3 위험 | 연기, 또는 어느 화소든 60 ℃ 이상 | 적 | 연속 | **차단, 래치** |
| 감시 불가 | 열화상을 10 초 넘게 못 읽음 | 황 점멸 | 짧게 | **차단** |

- 뜨거운 화소 = 화소 온도 > 주변 온도(SHT31) + 8 ℃. 주변 온도를 못 읽으면 화소 최저값으로 대신합니다.
- 올라갈 때는 조건이 2 초 계속되어야, 내려갈 때는 1.5 ℃ 더 식은 상태가 10 초 계속되어야 합니다 (깜빡임 방지).
- 위험은 래치됩니다. 조건이 사라진 뒤 버튼을 2 초 누르거나 `fire-detect --reset` 으로 풉니다. 아직 뜨거우면 해제 요청을 무시합니다.
- 연기는 MQ-2 전압이 기준선보다 0.3 V 오르면 감지. 기준선은 정상 단계에서만 천천히(10 분 시정수) 학습하고 켠 뒤 3 분은 예열로 판정하지 않습니다.
- **기준값(8 ℃, 60 ℃, 0.3 V)은 임시값입니다.** 5장 순서로 정상 충전 기록을 보고 다시 정하십시오.

## 2. 결선

결선 도면(2026-10-05)의 ESS-01 에서 VOC 센서(AGS02MA)와 가속도계(MPU6050)는 빠졌습니다 (2026-10 결정).
그래서 I2C 버스는 하나(i2c-1)만 씁니다.

| 장치 | 연결 | 주소 |
|---|---|---|
| AMG8833 8x8 열화상 | I2C (40핀 3 SDA, 5 SCL), 3.3 V | 0x69 |
| SHT31 온습도 | I2C | 0x44 |
| ADS1115 | I2C, **3.3 V 로 켤 것** | 0x48 |
| MQ-2 연기 (5 V 히터) | AO -> 10 kΩ -> ADS1115 A0 -> 20 kΩ -> GND | 분압 2/3, 설정 `smoke_divider: 1.5` |
| SSD1306 OLED (선택) | I2C | 0x3C |

| 출력 | BCM GPIO (40핀) | 비고 |
|---|---|---|
| AC 충전 SSR (XSSR-DA2440 + 방열판 XW-60) | 17 (11) | 통전 = 충전 허용 |
| DC 차단 릴레이 (4채널 모듈 CH1) | 27 (13) | NO 접점에 결선. 모듈이 Low 에서 붙으면 `relay_active_low: true` |
| 능동 부저 TMB12A05 | 22 (15) | 5 V 부저는 트랜지스터나 릴레이 채널을 거칠 것 |
| 신호등 LED 적, 황, 녹 | 5 (29), 6 (31), 13 (33) | |
| 래치 해제 버튼 | 26 (37) | GND 로 누름, 내부 풀업 |

**안전 쪽 설계.** SSR 과 릴레이는 "통전해야 충전" 입니다. 프로그램이 죽거나, 멈추거나(systemd watchdog 10 초),
Pi 전원이 나가면 출력이 풀려 충전이 끊깁니다. 켤 때도 첫 판정 전까지는 끊긴 상태입니다.
SSR 이 끊는 것은 감지기 자신의 전원이 아니라 감시 대상 파워뱅크의 충전 라인입니다.

## 3. 설치 (RPi5)

```bash
sudo apt install python3-venv python3-gpiozero python3-lgpio python3-smbus2 python3-yaml i2c-tools
# /boot/firmware/config.txt 에 dtparam=i2c_arm=on 후 재부팅. i2cdetect -y 1 에 48 44 69 (3c) 가 보여야 함
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
.venv/bin/python tools/hw_check.py i2c              # 센서 3종 응답
.venv/bin/python tools/hw_check.py sensors --n 10   # 값이 말이 되는지 (MQ-2 는 3 분 예열)
.venv/bin/python tools/hw_check.py outputs          # LED, 부저, DC 릴레이, SSR 을 하나씩. SSR 의 AC 쪽을 뺀 뒤에만
.venv/bin/python tools/hw_check.py button           # 래치 해제 버튼
```

보드에서 Claude Code 로 세팅할 때는 저장소 폴더에서 `claude` 를 실행하면 `CLAUDE.md` 의 안전 규칙과 순서를 따릅니다.

## 4. 실행

```bash
fire-detect --config /etc/fire-detect/config.yaml          # 보통은 systemd 가 실행
fire-detect --reset                                          # 위험 래치 해제 요청
fire-detect --config ... --ros                               # /fire/ess_01/status, /health/ess_01 (ROS 2 + odor_msgs 필요)

# 하드웨어 없이 (가짜 센서, 가짜 출력. 실제 드라이버 코드가 가짜 레지스터 위에서 돔)
fire-detect --simulate overheat --speed 0 --duration 620 --reset-at 560 --out /tmp/fire
fire-detect --simulate normal --speed 0 --duration 3600 --out /tmp/fire_normal
fire-detect --simulate sensor_loss --speed 0 --duration 200 --out /tmp/fire_loss
```

`overheat` 시나리오: 143 초 주의 -> 167 초 경고 -> 254 초 위험(60 ℃, 충전 차단, 래치) -> 288 초 연기 확인 -> 560 초 해제 버튼 -> 정상.

남기는 파일 (`log.dir`, 날짜는 UTC): `fire_YYYYmmdd.csv` (1 초 판정), `thermal_YYYYmmdd.csv` (1 초 화소 64 개, 하루 약 30 MB),
`fire_YYYYmmdd.jsonl` (fire_status 10 초마다 + 바뀔 때, device_health 10 초마다). 60 일 지난 파일은 지웁니다.

## 5. 기준값 정하기

1. 설정은 기본값 그대로 두고, 평소처럼 파워뱅크를 여러 번 충전하면서 며칠 기록합니다.
2. `python3 tools/analyze_log.py ~/fire_logs/fire_*.csv`
3. 출력되는 정상 분포와 제안값(`delta_c`, `abs_limit_c`, `smoke_dv`)을 `/etc/fire-detect/config.yaml` 의 `alarm:` 에 넣고
   `sudo systemctl restart fire-detect`.
4. 다시 며칠 돌려 오경보가 없는지 봅니다 (analyze_log.py 가 기록 중의 경보를 나열합니다).

카메라는 파워뱅크 전체가 화각(60°)에 들어오게 달고, 반사가 심한 금속면은 마스킹 테이프 등으로 덮으면 온도가 정확해집니다.

## 6. 시험

```bash
pip install pytest "jsonschema>=4.18"
python3 -m pytest tests      # moving-ver 가 옆 폴더에 있으면 기록을 규격 스키마로도 검사
```

- `test_drivers.py`: AMG8833 화소, 서미스터 형식, SHT31 CRC, ADS1115 설정 워드
- `test_alarm.py`: 단계 상승, 잡음 무시, 히스테리시스, 래치와 해제, 연기 기준선, 센서 끊김 차단
- `test_app.py`: 시나리오 전체 (출력, 파일, 스키마), systemd 알림, 설정 파일
- `test_hw_check.py`: 보드 점검 도구 (가짜 하드웨어, AC 확인 없이는 출력을 켜지 않음, 끝나면 모두 끔)
