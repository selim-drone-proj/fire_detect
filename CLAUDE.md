# CLAUDE.md: fire_detect (화재 감지기 ess_01, Raspberry Pi 5)

이 저장소는 파워뱅크(EcoFlow DELTA 2 Max)를 충전하는 동안 표면 온도, 주변 온도, 연기를 감시하고
위험하면 충전 AC 라인(SSR)과 DC 릴레이를 끊는 장치의 소프트웨어다. 자세한 동작과 결선은 README.md.
이 파일은 **보드 위에서 도는 Claude Code** 가 보드를 세팅하고 점검할 때 따를 규칙과 순서다.
대화와 기록은 한국어로 하고, 목록 구분에는 가운뎃점 대신 쉼표를 쓴다.

## 안전 규칙 (반드시)

1. SSR 은 220 V 충전 라인을 켜고 끈다. 출력 시험 전에는 사람에게 "SSR 의 AC 쪽을 뺐는지" 묻고,
   그렇다는 답을 받은 뒤에만 `tools/hw_check.py outputs` 를 돌린다. 220 V 결선은 사람이 직접 한다.
2. 출력 핀을 직접 켜는 명령(gpioset, pinctrl, python 한 줄 등)은 쓰지 않는다. 출력 시험은 hw_check.py 로만 한다.
3. `/boot/firmware/config.txt`, systemd 유닛, udev 규칙, `/etc/fire-detect/config.yaml` 을 바꾸기 전에
   바꿀 내용을 보여 주고 확인받는다. 바꾸는 파일은 먼저 `<파일>.bak` 으로 복사해 둔다.
4. 판정 기준(`alarm:` 의 값 전부, 특히 `cut_level`, `latch_danger`, `sensor_loss_cut_s`)과
   서비스의 `WatchdogSec`, `Restart` 는 바꾸지 않는다. 바꿔야 할 것 같으면 이유를 적어 사람에게 넘긴다.
5. hw_check 는 fire-detect 서비스와 같은 GPIO 를 쓴다. 서비스가 돌고 있으면 사람에게 알리고
   `sudo systemctl stop fire-detect` 후 시험하고, 끝나면 `sudo systemctl start fire-detect`.
   멈춘 동안은 출력이 풀려 충전이 끊긴 상태다 (안전 쪽).
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
| ADS1115 ADC | I2C, **3.3 V 로 켬** | 0x48 |
| MQ-2 연기 (히터 5 V) | AO -> 10 kΩ -> ADS1115 A0 -> 20 kΩ -> GND | 분압 1.5 |
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
3. **I2C 켜기**: `/boot/firmware/config.txt` 에 `dtparam=i2c_arm=on` 이 없으면 추가 (안전 규칙 3). 바꿨으면 재부팅을 부탁한다.
4. **권한**: `sudo usermod -aG i2c,gpio pi`. Ubuntu 처럼 `gpio` 그룹이 없으면 `sudo groupadd -f gpio` 와 udev 규칙
   `/etc/udev/rules.d/60-gpiochip.rules` 에 `SUBSYSTEM=="gpio", KERNEL=="gpiochip*", GROUP="gpio", MODE="0660"`
   (안전 규칙 3), 그 뒤 `sudo udevadm control --reload && sudo udevadm trigger`. 다시 로그인한 뒤 `id`, `ls -l` 로 확인.
5. **설치**: `cd ~/fire_detect && python3 -m venv --system-site-packages .venv && .venv/bin/pip install -e . && .venv/bin/pip install pytest "jsonschema>=4.18"`
6. **소프트웨어 시험**: `.venv/bin/python -m pytest -q tests` 가 전부 통과해야 한다.
   `.venv/bin/fire-detect --simulate overheat --speed 0 --duration 620 --reset-at 560 --out /tmp/fire` 의 출력에
   254 초 위험(충전 차단, 래치), 560 초 해제가 보여야 한다.
7. **I2C**: `sudo i2cdetect -y 1` 에 48, 44, 69 (OLED 를 달았으면 3c). 그다음 `.venv/bin/python tools/hw_check.py i2c`.
8. **센서**: `.venv/bin/python tools/hw_check.py sensors --n 10`. MQ-2 는 켠 뒤 3 분 예열이라 처음 값이 높다.
9. **출력**: 안전 규칙 1 을 지킨 뒤 `.venv/bin/python tools/hw_check.py outputs`. 사람이 보고 답한다.
   시작 직후 이미 붙어 있는 릴레이가 있으면 active_low 설정이 반대다. 버튼은 `.venv/bin/python tools/hw_check.py button`.
10. **설정 파일**: `sudo mkdir -p /etc/fire-detect && sudo cp config.example.yaml /etc/fire-detect/config.yaml`.
    9 단계 결과에 따라 `relay_active_low`, `ssr_active_low`, `buzzer_active_low` 만 맞춘다 (안전 규칙 3, 4).
11. **서비스**: `sudo cp systemd/fire-detect.service /etc/systemd/system/ && sudo systemctl daemon-reload && sudo systemctl enable --now fire-detect`,
    `systemctl status fire-detect` 가 active (running), `journalctl -u fire-detect -n 50` 에 시작 문구가 있고 오류가 없어야 한다.
12. **동작 확인 (사람과 같이, 안전 규칙 1 상태)**: 손이나 따뜻한 물컵을 열화상 앞에 두면 단계가 1, 2 로 오르고
    LED 와 부저가 바뀌는지, `journalctl -u fire-detect -f` 로 본다. 위험 래치가 걸렸으면 버튼 2 초나 `.venv/bin/fire-detect --reset` 으로 푼다.
13. **기록**: `~/fire_logs` 에 `fire_*.csv`, `thermal_*.csv`, `fire_*.jsonl` 이 생기는지 확인한다.
14. **마무리 보고**: 단계별 결과, 바꾼 시스템 파일 목록(.bak 경로 포함), 저장소를 고쳤으면 PR 주소, 남은 문제를 정리해 보여 준다.

## 자주 걸리는 것

- `GPIO busy` 나 핀을 열 수 없음: fire-detect 서비스가 잡고 있다 (안전 규칙 5).
- gpiozero 가 gpiochip 을 못 연다: `gpioinfo` (gpiod 패키지)로 `pinctrl-rp1` 칩 번호를 확인해 사람에게 보고한다. 코드 수정이 필요할 수 있다.
- `i2cdetect` 에 아무것도 안 보임: 3.3 V, GND, SDA 3번, SCL 5번 핀 확인. ADS1115 를 5 V 로 켜면 안 된다.
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
