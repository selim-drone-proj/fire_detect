# 보조배터리 벤치 구성 (2026-10-31)

220 V 쪽(SMPS, SSR, 퓨즈, 출력 콘센트)과 DC 릴레이, 부저, LED, 버튼을 모두 빼고
**Raspberry Pi 5 를 USB-C 보조배터리로 켜서 센서 값을 받고 기록, 판정, 그래프까지** 하는 구성이다.
코드는 220 V 구성과 같은 `fire-detect` 를 쓰고 설정 파일만 `config.battery.yaml` 로 바꾼다.
판정 단계(정상, 주의, 경고, 위험)는 그대로 계산해 기록하지만 끊을 출력이 없으므로 아무것도 차단하지 않는다.

| 들어가는 것 | 빠지는 것 |
|---|---|
| Pi 5, microSD, USB-C 보조배터리 | 220 V 전부 (단자대, 퓨즈, SMPS, DC-DC, SSR, 출력 콘센트) |
| AMG8833 8x8 열화상 (I2C 0x69) | DC 릴레이, 부저, LED 모듈, 래치 해제 버튼, NPN 트랜지스터 |
| SHT31 온습도 (I2C 0x44) | 함체 (벤치에서는 브레드보드 그대로) |
| ADS1115 ADC (I2C 0x48) + MQ-2 연기, 저항 10 kΩ, 20 kΩ | MLX90614, DS18B20 (나중에 더할 수 있음, 6장) |
| 브레드보드, 점퍼선 | |

## 1. 전원: 보조배터리 조건

- **USB-C 출력 5 V 3 A 이상** (PD 지원이면 좋음). 케이블도 3 A 용 (USB-C to C, 또는 A to C 3 A).
  Pi 5 는 5 V 5 A 를 원하지만 3 A 공급이면 켜지고 USB 포트 전류만 600 mA 로 줄인다.
  이 구성은 센서를 GPIO 핀에서 받으므로 영향 없다. "5 A 를 못 준다" 경고는 무시해도 된다.
- 소비 전력 어림: Pi 5 화면 없이 3~4 W, MQ-2 히터 약 0.8 W (5 V 150 mA 안팎), 나머지 센서는 몇 mA.
  합쳐 **약 4~5 W**. 변환 손실을 넣으면 10,000 mAh 는 대략 6 시간, 20,000 mAh 는 대략 12 시간 (실제는 기록으로 확인).
- 전압 확인: `vcgencmd get_throttled` 가 `throttled=0x0` 이면 정상. `0x50005` 처럼 1, 4 비트가 서 있으면 전압 부족.
  fire-detect 는 Pi 5 입력 전압을 10 초마다 `fire_*.jsonl` 의 `device_health.supply_v` 에 남기고,
  `tools/plot_log.py` 그래프 맨 아래 칸에 그린다. 4.75 V 아래로 자주 내려가면 보조배터리나 케이블을 바꾼다.
- 보조배터리를 **충전하면서 동시에 쓰면**(패스스루) 충전기를 꽂고 뺄 때 출력이 잠깐 끊겨 Pi 가 재부팅되는 제품이 많다. 기록 중에는 피한다.
- 배터리가 다 되어 꺼지면 마지막 몇 초 기록이 빠질 수 있다. 끄기 전에는 `sudo poweroff`.
- **시각**: 기록은 UTC. 인터넷이 없으면 시계가 틀어져 기록에 TIME_UNSYNCED 가 붙는다.
  휴대폰 핫스팟 등에 한 번 붙여 `timedatectl` 의 `System clock synchronized: yes` 를 확인하고 시작한다.

## 2. 결선 (처음부터, 보조배터리를 뺀 채로)

### Pi 5 40핀에서 쓰는 핀

| Pi 핀 | 신호 | 가는 곳 |
|---|---|---|
| 1 | 3.3 V | 브레드보드 3.3 V 레일 |
| 2 또는 4 | 5 V | 브레드보드 5 V 레일 (MQ-2 히터만) |
| 3 | SDA (BCM 2) | SDA 줄 |
| 5 | SCL (BCM 3) | SCL 줄 |
| 6, 9, 14, 20, 25 중 둘 | GND | 두 GND 레일 모두 |

### 브레드보드 (1 번 줄을 왼쪽에 두고, 1~30 번 줄만 씀)

레일: 한쪽 + 를 3.3 V (Pi 핀 1), 다른 쪽 + 를 5 V (Pi 핀 2), 양쪽 − 를 GND (Pi 핀 6, 25).
**3.3 V 레일과 5 V 레일을 헷갈리지 않게 5 V 쪽에 테이프 표시.** I2C 모듈과 ADS1115 는 모두 3.3 V 쪽이다.

| 줄 | 꽂는 것 |
|---|---|
| 3, 4 | SDA: Pi 핀 3, AMG8833 SDA, SHT31 SDA, ADS1115 SDA |
| 7, 8 | SCL: Pi 핀 5, AMG8833 SCL, SHT31 SCL, ADS1115 SCL |
| 18 | MQ-2 AO |
| 18-22 | 10 kΩ |
| 22 | ADS1115 A0 |
| 22-26 | 20 kΩ |
| 26 | GND 레일로 |

(한 줄의 같은 쪽 다섯 구멍은 이어져 있다. 3 과 4 번 줄은 점퍼 하나로 이어 구멍 수를 늘린 것. 7, 8 도 같음)

### 모듈별

| 모듈 | VCC | GND | 그 밖 |
|---|---|---|---|
| AMG8833 | 3.3 V (VIN) | GND | SDA, SCL. INT 는 안 씀. AD_SELECT 를 GND 에 묶은 보드는 0x68 (설정 고침) |
| SHT31 | 3.3 V | GND | SDA, SCL. ADDR 안 이음 (0x44) |
| ADS1115 | **3.3 V** (5 V 금지: SDA, SCL 이 5 V 가 되어 Pi 를 상하게 함) | GND | SDA, SCL, **ADDR 을 GND**, A0 는 22 번 줄, ALRT 안 씀 |
| MQ-2 | **5 V** (히터) | GND | AO 는 18 번 줄 (분압 거쳐 A0 로), **DO 는 이지 않음** (5 V 출력) |

처음에는 2-1 처럼 MQ-2 와 ADS1115 만 꽂아 확인하고 나머지를 더하는 것을 권한다.

- 분압: MQ-2 AO 는 최대 5 V 라 10 kΩ, 20 kΩ 로 2/3 로 낮춰 ADS1115 에 3.3 V 이하로 넣는다. 설정 `smoke_divider: 1.5` 가 되돌려 곱한다.
  20 kΩ 가 없으면 10 kΩ 둘을 이어 쓴다.
- 풀업 저항은 따로 달지 않는다 (모듈과 Pi 에 이미 있음).
- 선 길이는 I2C 는 30 cm 안쪽으로. 열화상을 멀리 두려면 나중에 랜선 결선(220 V 구성 문서의 L1)으로.

### 꽂기 전 점검 (멀티미터)

1. 3.3 V 레일과 GND 사이, 5 V 레일과 GND 사이가 0 Ω 근처가 아닐 것 (단락 아님).
2. 3.3 V 레일과 5 V 레일 사이가 이어져 있지 않을 것.
3. ADS1115 VDD 가 3.3 V 레일에 꽂혔는지 눈으로 한 번 더.

## 2-1. MQ-2 먼저 살리기 (ADS1115 와 둘만)

Pi 에는 아날로그 입력이 없어서 MQ-2 의 AO 는 ADS1115 를 거쳐야 읽힌다. 열화상, 온습도는 빼 두고 이 둘만 꽂는다.
DO 는 5 V 비교기 출력이라 Pi 핀에 바로 꽂으면 안 되고, 이 구성에서는 쓰지 않는다.

**가. 모듈만 확인 (Pi 없이, 1 분)**
1. MQ-2 의 VCC, GND 두 선만 USB 5 V(충전기, PC 포트) 나 Pi 핀 2, 6 에 잇는다. AO, DO 는 비워 둔다.
2. 모듈 전원 LED 가 켜지고 1~2 분 뒤 금속 망이 미지근해지면 히터가 도는 것이다. 망은 뜨거워지니 오래 만지지 않는다.
3. 멀티미터가 있으면 AO 와 GND 사이 전압: 켠 직후 높게 시작해 몇 분에 걸쳐 내려온다. 깨끗한 공기에서 몇백 mV ~ 1 V 대가 흔하다
   (모듈의 부하 저항에 따라 다름). 라이터 가스를 불 붙이지 않고 잠깐 대면 바로 오른다.
   가변저항(파란 나사)은 DO 기준만 바꾸고 AO 에는 영향이 없다.

**나. ADS1115 와 결선 (보조배터리 뺀 채로)**

| 선 | 처음 | 끝 |
|---|---|---|
| ADS1115 VDD | ADS1115 | 3.3 V 레일 (Pi 핀 1) |
| ADS1115 GND, ADDR | ADS1115 | GND 레일 (ADDR 도 GND 로, 주소 0x48) |
| ADS1115 SDA, SCL | ADS1115 | Pi 핀 3, 5 (브레드보드 3+4, 7+8 번 줄) |
| MQ-2 VCC | MQ-2 | 5 V 레일 (Pi 핀 2) |
| MQ-2 GND | MQ-2 | GND 레일 |
| MQ-2 AO | MQ-2 | 18 번 줄 → 10 kΩ → 22 번 줄 (ADS1115 A0) → 20 kΩ → 26 번 줄 → GND 레일 |

꽂기 전에 멀티미터로 3.3 V 와 5 V 레일이 서로, 그리고 GND 와 이어지지 않았는지 본다.
SDA, SCL 선에는 테이프로 표시해 둔다 (뒤에 SHT31, AMG8833 을 같은 줄에 더할 때 바뀌기 쉬움).

**다. 확인**

```bash
sudo i2cdetect -y 1                                   # 48 하나만 보이면 정상
.venv/bin/python tools/mq2_check.py --config config.battery.yaml --minutes 30
```

`mq2_check.py` 는 처음에 A0~A3 을 한 번씩 읽어 보여 준 뒤, 1 초마다 A0 핀 전압, MQ-2 AO 전압(x1.5), 기준선 대비, 최근 1 분 기울기, 상태를 찍고
`~/fire_logs/mq2/mq2_<UTC시각>.csv` 에 남긴다. 기대하는 흐름:

| 때 | 보이는 것 |
|---|---|
| 켠 직후 ~ 3 분 | 예열 중. AO 가 높게 시작해 내려옴 |
| 3 분 ~ 수십 분 | 내려가는 중 → 안정 (1 분 기울기 ±10 mV 안) |
| 라이터 가스를 불 없이 10 cm 앞에서 1 초 (환기, 불꽃 금지) | AO 가 확 오르고 0.3 V 넘게 오르면 "올라감", 몇십 초~몇 분에 걸쳐 돌아옴 |

| 증상 | 볼 곳 |
|---|---|
| i2cdetect 표가 전부 `--` (전원 3.3 V 는 정상) | **SDA, SCL 이 서로 바뀜** (전압으로는 구분 안 됨, 두 선을 바꿔 꽂아 봄. 2026-11-01 실제로 이것이었음). 그다음 SDA 핀 3, SCL 핀 5, 끊어진 점퍼선 |
| i2cdetect 에 48 없음 | ADS1115 VDD 3.3 V, GND, SDA 핀 3, SCL 핀 5, ADDR 이 GND 인지 (ADDR 을 VDD 에 이으면 0x49) |
| "ADS1115 응답 없음" | 위와 같음, `i2c` 그룹 권한 (`id`) |
| A0 가 3.3 V 근처에 붙음 | 분압 저항이 빠졌거나 AO 를 A0 에 바로 꽂음. 바로 보조배터리를 빼고 결선 확인 |
| 거의 0 V | MQ-2 VCC 가 5 V 레일인지, AO 선, 10 kΩ, 모듈 전원 LED |
| A0~A3 이 비슷한 값으로 마구 흔들림 | AO 가 A0 에 안 닿음 (떠 있는 입력). 22 번 줄 확인 |
| 가스를 대도 안 오름 | 예열이 덜 됨 (3 분 이상 기다림), 또는 AO 대신 DO 를 꽂음 |

여기까지 되면 SHT31, AMG8833 을 같은 SDA, SCL 줄과 3.3 V 레일에 더하고 아래 3장으로 간다.
처음 쓰는 MQ-2 는 4장 번인을 해야 기준선이 덜 흐른다.

## 3. 첫 전원과 센서 확인

OS 와 기본 세팅은 CLAUDE.md 세팅 순서 1~6 단계 그대로 (I2C 켜기, 권한, venv 설치, 시험).
1-Wire(`dtoverlay=w1-gpio`) 는 DS18B20 을 달 때만 필요하다. 9 단계(출력), 11, 12 단계(서비스, 비상 끄기)는 이 구성에서 건너뛴다.

```bash
cd ~/fire_detect
sudo i2cdetect -y 1                          # 44, 48, 69 (AMG8833 이 0x68 이면 68)
.venv/bin/python tools/hw_check.py i2c --config config.battery.yaml
.venv/bin/python tools/hw_check.py sensors --n 10 --config config.battery.yaml
```

- `--config config.battery.yaml` 을 꼭 붙인다. 안 붙이면 `/etc/fire-detect/config.yaml` 이나 기본값을 써서 MLX90614, DS18B20 이 "실패" 로 나온다.
- MQ-2 는 켠 뒤 몇 분 동안 값이 높게 시작해 내려온다. 정상이다.
- AMG8833 의 보드 온도가 주변보다 몇 도 높은 것도 정상이다.

## 4. MQ-2 번인 (처음 한 번, 24~48 시간)

새 MQ-2 는 히터를 오래 켜 두어야 값이 안정된다. 보조배터리로는 길게 못 버티므로
**MQ-2 만 따로 USB 5 V(휴대폰 충전기나 PC USB 포트)에서 VCC, GND 두 선만 이어 켜 둔다.** Pi 도, AO 도 필요 없다.
시작 시각을 재고 대장 #71 에 적는다. 번인 전에도 시험은 되지만 기준선이 계속 흘러간다.

## 5. 실행, 값 보기, 데이터 처리

터미널 두 개 (SSH 두 창, 또는 `tmux`):

```bash
# 창 1: 읽기, 판정, 기록 (1 초마다). Ctrl+C 로 끝
.venv/bin/fire-detect --config config.battery.yaml

# 창 2: 값 보기 (파일만 읽으므로 같이 돌려도 됨)
.venv/bin/python tools/live_view.py           # 1 초마다 한 줄
.venv/bin/python tools/live_view.py --grid    # + 열화상 8x8 숫자 (* 는 뜨거운 화소)
```

기록은 `~/fire_logs` (날짜는 UTC):

| 파일 | 내용 |
|---|---|
| `fire_YYYYmmdd.csv` | 1 초마다 한 줄: 단계, 주변 온습도, 열화상 최고, 평균, 최저, 뜨거운 화소 수, 연기 전압과 기준선, 이유. 엑셀로 열림 |
| `thermal_YYYYmmdd.csv` | 1 초마다 화소 64 개 (p00 ~ p63, 8 개씩 한 줄) |
| `fire_YYYYmmdd.jsonl` | 데이터 규격 v0.2 `fire_status` (10 초마다와 바뀔 때), `device_health` (센서 상태, Pi 입력 전압, CPU 온도) |

그래프와 요약 (matplotlib 필요: `sudo apt install -y python3-matplotlib`):

```bash
.venv/bin/python tools/plot_log.py                 # 오늘 전체 -> ~/fire_logs/plots/*.png
.venv/bin/python tools/plot_log.py --last 30       # 마지막 30 분
.venv/bin/python tools/plot_log.py --day 20261101
.venv/bin/python tools/analyze_log.py ~/fire_logs/fire_2026110*.csv   # 정상 기록으로 판정 기준 제안
```

- `fire_*.png`: 온도(주변, 열화상 최고, 평균, 뜨거운 화소 기준선), 습도, 연기(기준선, +0.3 V 선), 판정 단계, Pi 입력 전압
- `thermal_*.png`: 가장 뜨거웠던 순간, 기간 평균, 화소별 최고를 8x8 로
- 노트북으로 가져오기: `scp -r pi@ess01.local:fire_logs ./` (노트북에서 `pip install matplotlib` 후 `python tools/plot_log.py --dir ./fire_logs` 도 됨)

전원을 꽂으면 저절로 시작하게 하려면 CLAUDE.md 10, 11 단계처럼 `config.battery.yaml` 을 `/etc/fire-detect/config.yaml` 로 복사하고
서비스를 켠다 (`sudo systemctl enable --now fire-detect`, 보기는 `journalctl -u fire-detect -f`).

### 동작 시험 (사람이)

| 시험 | 기대 |
|---|---|
| 손바닥을 열화상 10~20 cm 앞에 | 뜨거운 화소 1~2 개면 주의, 3 개 이상이면 경고 |
| 뜨거운 물 컵 (60 ℃ 넘는 물)을 가까이 | 최고가 60 ℃ 넘으면 위험 (래치). 해제는 `fire-detect --config config.battery.yaml --reset` 후 식을 때 |
| 라이터 가스를 불 붙이지 않고 MQ-2 앞 10 cm 에서 1 초 | 켠 뒤 3 분이 지난 상태에서 연기 전압이 기준 + 0.3 V 를 넘으면 위험. 환기, 불꽃 금지 |
| 열화상 선 하나를 뽑음 | 10 초 뒤 감시 불가 표시 (기록의 fault 1). 다시 꽂으면 10 초 안에 돌아옴 |

## 6. 다른 열 센서를 더할 때

| 센서 | 결선 | 설정 (`config.battery.yaml`) |
|---|---|---|
| MLX90614 (GY-906) 적외선 | 3.3 V, GND, SDA 줄, SCL 줄 (같은 I2C) | `mlx90614_address: 0x5A` |
| DS18B20 접촉 프로브 | 빨강 3.3 V, 검정 GND, 노랑 DQ 를 Pi 핀 7 (BCM 4), DQ 와 3.3 V 사이 4.7 kΩ 하나 | `ds18b20_count: 3`, `/boot/firmware/config.txt` 에 `dtoverlay=w1-gpio` 후 재부팅, `hw_check.py w1` |

더하면 기록에 `ir_c`, `probe1_c`.. 열이 생기고 그래프에도 저절로 나온다 (그날 기존 CSV 는 `_1` 로 옮겨짐).

## 7. 220 V 구성으로 돌아갈 때

`config.example.yaml` 과 README 2장, CLAUDE.md 세팅 순서 전체 (출력 시험, 서비스, 비상 끄기 확인)를 따른다.
