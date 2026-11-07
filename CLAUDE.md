# CLAUDE.md: fire_detect (화재 감지기 ess_01, Raspberry Pi 5)

이 저장소는 파워뱅크(EcoFlow DELTA 2 Max)를 충전하는 동안 표면 온도(열화상, 접촉 프로브, 적외선), 주변 온도, 연기를 감시하고
위험하면 충전 AC 라인(SSR)과 DC 릴레이를 끊는 장치의 소프트웨어다. 자세한 동작과 결선은 README.md.
이 파일은 **보드 위에서 도는 Claude Code** 가 보드를 세팅하고 점검할 때 따를 규칙과 순서다.
대화와 기록은 한국어로 하고, 목록 구분에는 가운뎃점 대신 쉼표를 쓴다.

## 안전 규칙 (반드시)

1. SSR 은 220 V 충전 라인을 켜고 끈다. 출력 시험 전에는 사람에게 "SSR 의 AC 쪽을 뺐는지" 묻고,
   그렇다는 답을 받은 뒤에만 `tools/hw_check.py outputs` 를 돌린다. 220 V 결선은 사람이 직접 한다.
2. 출력 핀을 직접 켜는 명령(gpioset, pinctrl, python 한 줄 등)은 쓰지 않는다. 출력 시험은 hw_check.py 로만 한다.
3. `/boot/firmware/config.txt`, systemd 유닛, udev 규칙, `/etc/fire-detect/config.yaml` 을 바꾸기 전에
   바꿀 내용을 보여 주고 확인받는다. 바꾸는 파일은 먼저 `<파일>.bak` 으로 복사해 둔다.
4. 판정 기준(`alarm:` 의 값 전부, 특히 `cut_level`, `latch_danger`, `sensor_loss_cut_s`, `start_hold_s`)과
   서비스의 `WatchdogSec`, `WatchdogSignal`, `Restart`, `ExecStartPre`, `ExecStopPost`, `StateDirectory`,
   `WorkingDirectory`, `Environment` 는 바꾸지 않는다.
   위험 래치 파일 `/var/lib/fire-detect/latched` 를 지우지 않는다 (해제는 사람이 버튼이나 `fire-detect --reset` 으로).
   바꿔야 할 것 같으면 이유를 적어 사람에게 넘긴다.
5. hw_check 는 fire-detect 서비스와 같은 GPIO 를 쓴다. 서비스가 돌고 있으면 사람에게 알리고
   `sudo systemctl stop fire-detect` 후 시험하고, 끝나면 `sudo systemctl start fire-detect`.
   멈출 때 서비스가 출력을 모두 끄므로(ExecStopPost) 멈춘 동안은 충전이 끊긴 상태다 (안전 쪽).
6. git 은 PR 까지만 한다. 저장소 파일을 고쳤으면 아래 'git 과 PR' 순서대로 새 브랜치에 커밋, push 하고 PR 을 연다.
   PR 승인과 병합, main 에 직접 push, force push, 브랜치 삭제, 저장소 설정 변경은 사람이 한다.
   GitHub 인증은 사람이 보드에 넣어 둔 개인 토큰(`gh auth login`)만 쓰고, 토큰 값은 보지도 남기지도 않는다.
   SSH 설정, 사용자 계정, 디스크 포맷, `rm -rf` 는 하지 않는다.
7. 재부팅, 배선 연결과 분리, 버튼 누르기, 손이나 따뜻한 물컵을 열화상 앞에 대기 같은 물리 작업은
   사람에게 부탁하고 끝났다는 답을 기다린다. 보드는 눈으로 볼 수 없으므로 추측하지 않는다.

## 보드

| 장치 | 연결 | 주소, 핀 |
|---|---|---|
| AMG8833 8x8 열화상 | I2C 버스 1 (40핀 3 SDA, 5 SCL), 3.3 V | 0x69 |
| SHT31 온습도 | I2C | 0x44 |
| MLX90614 적외선 (GY-906) | I2C, 3.3 V | 0x5A |
| ADS1115 ADC | I2C, **3.3 V 로 켬** | 0x48 |
| MQ-2 연기 (히터 5 V) | AO -> 10 kΩ -> ADS1115 A0 -> 20 kΩ -> GND, DO 는 안 이음 | 분압 1.5 |
| DS18B20 접촉 프로브 x3 | 1-Wire: DQ -> BCM 4 (핀 7), VDD 3.3 V, DQ-3.3 V 4.7 kΩ 하나 | `/sys/bus/w1/devices/28-*` |
| SSD1306 OLED (선택) | I2C | 0x3C |
| AC 충전 SSR | BCM 17 (핀 11) | 통전 = 충전 허용 |
| DC 차단 릴레이 | BCM 27 (핀 13) | 모듈이 Low 에서 붙으면 `relay_active_low: true` |
| 부저 | BCM 22 (핀 15) | |
| LED 적, 황, 녹 | BCM 5, 6, 13 (핀 29, 31, 33) | |
| 래치 해제 버튼 | BCM 26 (핀 37) | GND 로 누름, 내부 풀업 |

- 사용자 `pi`, 저장소 `~/fire_detect` 를 기준으로 서비스 파일이 쓰여 있다. 다르면 서비스 파일의 User, Group, ExecStart 를 맞춘다.
- OS 는 Ubuntu Server 24.04 (64-bit, 권장, 드론 Pi 와 같음) 또는 Raspberry Pi OS (64-bit). `cat /etc/os-release` 로 먼저 확인한다.
- Pi 5 에서는 RPi.GPIO 가 동작하지 않는다. gpiozero 2.x + lgpio 만 쓴다.

## 세팅 순서

단계마다 실행한 명령과 결과를 짧게 보여 주고, 실패하면 다음 단계로 넘어가지 않는다.
각 단계 결과는 `~/fire_setup_log.md` 에 날짜와 함께 한 줄씩 남긴다 (저장소 밖).

1. **상태 보기**: `cat /etc/os-release`, `uname -m` (aarch64 여야 함), `free -h`, `df -h /`, `timedatectl`,
   `id`, `ls -l /dev/i2c-1 /dev/gpiochip*`, `git -C ~/fire_detect status`.
2. **패키지**: `sudo apt update && sudo apt install -y python3-venv python3-gpiozero python3-lgpio python3-smbus2 python3-yaml i2c-tools git`
3. **I2C, 1-Wire 켜기**: `/boot/firmware/config.txt` 에 `dtparam=i2c_arm=on` 과 `dtoverlay=w1-gpio` 가 없으면 추가 (안전 규칙 3).
   Ubuntu 에서 `/boot/firmware/overlays/w1-gpio-pi5.dtbo` 가 있으면 `dtoverlay=w1-gpio-pi5` 로 적는다
   (Raspberry Pi OS 는 w1-gpio 를 Pi 5 용으로 알아서 바꾼다). `i2c_arm_baudrate` 는 넣지 않는다 (MLX90614 최대 100 kHz).
   바꿨으면 재부팅을 부탁한다.
4. **권한**: `sudo usermod -aG i2c,gpio pi`. Ubuntu 처럼 `gpio` 그룹이 없으면 `sudo groupadd -f gpio` 와 udev 규칙
   `/etc/udev/rules.d/60-gpiochip.rules` 에 `SUBSYSTEM=="gpio", KERNEL=="gpiochip*", GROUP="gpio", MODE="0660"`
   (안전 규칙 3), 그 뒤 `sudo udevadm control --reload && sudo udevadm trigger`. 다시 로그인한 뒤 `id`, `ls -l` 로 확인.
5. **설치**: `cd ~/fire_detect && python3 -m venv --system-site-packages .venv && .venv/bin/pip install -e . && .venv/bin/pip install pytest "jsonschema>=4.18"`
6. **소프트웨어 시험**: `.venv/bin/python -m pytest -q tests` 가 전부 통과해야 한다.
   `.venv/bin/fire-detect --simulate overheat --speed 0 --duration 620 --reset-at 560 --out /tmp/fire` 의 출력에
   254 초 위험(충전 차단, 래치), 560 초 해제가 보여야 한다.
7. **I2C, 1-Wire**: `sudo i2cdetect -y 1` 에 44, 48, 5a, 69 (OLED 를 달았으면 3c), `ls /sys/bus/w1/devices/` 에 `28-` 셋.
   그다음 `.venv/bin/python tools/hw_check.py i2c` 와 `.venv/bin/python tools/hw_check.py w1`.
8. **센서**: `.venv/bin/python tools/hw_check.py sensors --n 10`. MQ-2 는 켠 뒤 3 분 예열이라 처음 값이 높다.
   프로브 위치 구별: 사람에게 "프로브를 하나씩 10 초씩 손으로 쥐어 달라"고 부탁하고 `.venv/bin/python tools/hw_check.py w1 --n 20`
   (약 50 초)을 돌린다. 괄호 안 상승폭이 커지는 ID 와 사람이 말한 위치(상판, 측면, 뒷면)를 짝지어 `~/fire_setup_log.md` 에 적는다.
9. **출력**: 안전 규칙 1 을 지킨 뒤 `.venv/bin/python tools/hw_check.py outputs`. 사람이 보고 답한다.
   시작 직후 이미 붙어 있는 릴레이가 있으면 active_low 설정이 반대다. 릴레이나 SSR 이 끈 뒤에도 떨어지지 않으면
   README 2장 하드웨어 주의를 사람에게 보여 주고 배선 변경을 부탁한다 (3.3 V 신호로 안 떨어지는 모듈). 버튼은 `.venv/bin/python tools/hw_check.py button`.
10. **설정 파일**: `sudo mkdir -p /etc/fire-detect && sudo cp config.example.yaml /etc/fire-detect/config.yaml`.
    9 단계 결과에 따라 `relay_active_low`, `ssr_active_low`, `buzzer_active_low` 를 맞추고, 8 단계에서 짝지은 프로브 ID 를
    `sensors.ds18b20_ids` 에 [상판, 측면, 뒷면] 순서로 적는다. 달지 않은 센서는 `mlx90614_address: -1`, `ds18b20_count: 0`.
    이 밖의 값, 특히 `alarm:` 은 건드리지 않는다 (안전 규칙 3, 4).
11. **서비스**: `sudo cp systemd/fire-detect.service /etc/systemd/system/ && sudo systemctl daemon-reload && sudo systemctl enable --now fire-detect`,
    `systemctl status fire-detect` 가 active (running), `journalctl -u fire-detect -n 50` 에 시작 문구가 있고 오류가 없어야 한다.
    `cat /sys/module/pinctrl_rp1/parameters/persist_gpio_outputs` 가 N 이어야 한다 (파일이 없으면 그 커널에는 이 설정이 없다는 뜻이니 보고만 한다).
    journal 에 "GPIO 출력 없이 동작" 이 있으면 실패다 (충전을 켤 수 없음). 서비스 파일이 저장소 것과 같은지,
    `id pi` 에 gpio 그룹이 있는지 확인하고 사람에게 보고한다.
12. **동작 확인 (사람과 같이, 안전 규칙 1 상태)**: 손이나 따뜻한 물컵을 열화상 앞에 두면 단계가 1, 2 로 오르고
    LED 와 부저가 바뀌는지, `journalctl -u fire-detect -f` 로 본다. 접촉 프로브 하나를 손으로 쥐거나 적외선 앞에 손을 대면
    주의(1)로 오르고 이유에 그 프로브나 적외선이 나와야 한다. 위험 래치가 걸렸으면 버튼 2 초나 `.venv/bin/fire-detect --reset` 으로 푼다.
    **비상 끄기 확인**: 사람에게 SSR 입력 표시 LED 와 DC 릴레이를 보고 있어 달라고 한 뒤 `sudo systemctl kill -s KILL fire-detect`.
    3 초 안에 SSR LED 가 꺼지고 릴레이가 떨어져야 하고, 서비스가 다시 시작해 10 초 뒤 다시 켜져야 한다. 안 꺼지면 바로 사람에게 알린다.
13. **기록**: `~/fire_logs` 에 `fire_*.csv`, `thermal_*.csv`, `fire_*.jsonl` 이 생기는지 확인한다.
14. **마무리 보고**: 단계별 결과, 바꾼 시스템 파일 목록(.bak 경로 포함), 저장소를 고쳤으면 PR 주소, 남은 문제를 정리해 보여 준다.

## 자주 걸리는 것

- `GPIO busy` 나 핀을 열 수 없음: fire-detect 서비스가 잡고 있다 (안전 규칙 5).
- gpiozero 가 gpiochip 을 못 연다: `gpioinfo` (gpiod 패키지)로 `pinctrl-rp1` 칩 번호를 확인해 사람에게 보고한다. 코드 수정이 필요할 수 있다.
- `i2cdetect` 에 아무것도 안 보임: 3.3 V, GND, SDA 3번, SCL 5번 핀 확인. ADS1115 를 5 V 로 켜면 안 된다.
- `/sys/bus/w1/devices` 가 없음: 1-Wire 가 안 켜졌다 (3 단계, 재부팅). `lsmod | grep w1` 에 w1_gpio, w1_therm 이 있어야 한다.
  Ubuntu 에서 `modinfo w1_therm` 이 없다고 하면 `apt-cache search linux-modules-extra` 로 raspi 커널용 추가 모듈 패키지를 찾아 사람에게 보고한다.
- `28-` 가 셋보다 적음: DQ 는 핀 7, DQ 와 3.3 V 사이 4.7 kΩ, 3 선 결선(기생 전원 아님)인지 사람에게 확인을 부탁한다.
  프로브 키트의 어댑터 기판을 5 V 에 꽂으면 안 된다.
- 기록이나 journal 에 DS18B20 "빈 값", "85 ℃ 초기값" 이 잦음: 전원, 접촉 불량, 선 길이. 선이 길면 풀업을 2.2 kΩ 로 낮추는 것을 사람에게 제안한다.
  (요즘 커널은 응답이 없거나 CRC 가 계속 틀리면 w1_slave 를 비워서 준다)
- MLX90614 "PEC 불일치": 배선, 버스 속도(100 kHz 이하), 풀업. 0x5A 가 안 보이면 GY-906 전원(3.3 V)과 SDA, SCL 을 확인한다.
- AMG8833 보드 온도가 주변보다 몇 도 높은 것은 정상이다.
- 시각: 기록은 UTC. `timedatectl` 의 NTP 동기화가 no 이면 기록에 TIME_UNSYNCED 가 붙는다.
  Pi 5 RTC 백업 전지가 공식 충전식이면 `dtparam=rtc_bbat_vchg=3000000` 으로 충전을 켠다 (충전식이 아니면 켜지 않음, 안전 규칙 3).
- 기준값(8 ℃, 60 ℃, 0.3 V)은 임시값이다. 며칠 정상 충전 기록을 모은 뒤 `tools/analyze_log.py` 로 사람이 정한다 (README 5장).

## git 과 PR

저장소 파일(코드, 문서, `config.example.yaml` 등)을 고쳤을 때만 한다. `/etc`, `/boot` 같은 보드의 시스템 파일은
저장소 밖이라 PR 대상이 아니다. 거기서 알게 된 것을 저장소에 남겨야 하면 README 나 예시 설정을 고치는 PR 로 한다.

1. 시작 전: `git -C ~/fire_detect fetch origin` 후 `git switch -c board/<YYYYMMDD>-<짧은 설명> origin/main`.
   이미 그 작업용 브랜치에 있으면 그대로 쓴다. main 에서 직접 커밋하지 않는다.
2. 고친 뒤: `.venv/bin/python -m pytest -q tests` 가 통과해야 커밋한다. 커밋 메시지는 한국어로, 무엇을 왜 바꿨는지 쓴다.
3. 올리기: `git push -u origin <브랜치>` 후
   `gh pr create --base main --title "<한 줄 요약>" --body "<바꾼 것, 보드에서 확인한 것(hw_check, pytest 결과), 남은 문제>"`.
   보드에서 확인을 다 못 했으면 `--draft` 로 연다.
4. 끝나면 PR 주소를 사람에게 보여 준다. `gh pr merge`, `gh pr review --approve`, `git push origin main`, `git push --force`,
   `git push --delete`, `gh repo edit` 는 쓰지 않는다.
5. 인증이 안 돼 있으면(`gh auth status` 실패) 직접 고치려 하지 말고 사람에게 아래 'GitHub 인증'을 부탁한다.
   `gh auth token`, `~/.config/gh/hosts.yml`, `~/.git-credentials` 처럼 토큰을 보여 주는 명령이나 파일은 열지 않는다.

## GitHub 인증 (사람이 보드에서 한 번)

1. GitHub 웹 → Settings → Developer settings → Personal access tokens → Fine-grained tokens → Generate new token.
   Resource owner 는 `selim-drone-proj`, Repository access 는 `fire_detect` 만 (필요하면 다른 저장소 추가),
   Permissions 는 Contents: Read and write, Pull requests: Read and write. 만료는 90 일 정도.
   조직 설정에 따라 조직 관리자의 토큰 승인이 필요할 수 있다.
2. 보드에서: `sudo apt install -y gh` 후 `gh auth login` → GitHub.com → HTTPS → Paste an authentication token 에 붙여 넣기,
   그다음 `gh auth setup-git` (git push 도 같은 토큰을 씀), `gh auth status` 로 확인.
   토큰은 보드 터미널에만 입력하고 채팅, 파일, 커밋에는 넣지 않는다.
3. 권장: 저장소 Settings → Branches (또는 Rules) 에서 main 에 "PR 필수, 승인 1 명, force push 금지"를 걸고 관리자도 예외 없이 둔다.
   그러면 토큰이 있어도 승인 없이는 main 이 바뀌지 않는다.

## 나중에 (지금 세팅 범위 밖)

- ROS 2 연동(`--ros`)은 Ubuntu 24.04 에서 ROS 2 Jazzy 와 moving-ver 의 odor_msgs 가 있어야 한다. 기본 세팅과 며칠 운용이 끝난 뒤 따로 한다.
- 파워뱅크 BMS 값(ess_bridge_node)은 배터리, 전원 규격 v0.3 초안에 설계만 있다.
