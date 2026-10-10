"""
app.py - 화재 감지기 본체 (ess_01). 1 초마다: 센서 읽기 -> 판정 -> 출력 -> 기록 -> (선택) ROS 2 발행

    fire-detect --config /etc/fire-detect/config.yaml          # 실제 장비 (systemd 서비스로 상시 실행)
    fire-detect --simulate overheat --speed 50 --out /tmp/fire  # 하드웨어 없이 (가짜 센서, 가짜 출력)
    fire-detect --reset                                          # 위험 래치 해제 요청 (조건이 사라졌을 때만 풀림)
    fire-detect --config ... --ros                               # /fire/ess_01/status, /health/ess_01 발행

systemd 아래에서는 READY, WATCHDOG 신호를 보낸다. 루프가 멈추면 systemd 가 재시작하고,
그동안 GPIO 가 풀려 충전이 끊긴다 (outputs.py 의 안전 쪽 설계).
"""
from __future__ import annotations

import argparse
import os
import signal
import socket
import sys
import time
from pathlib import Path

from . import __version__, system_info
from .alarm import FLAG_SIMULATED, FLAG_TIME_UNSYNCED, LEVEL_NAMES, AlarmEngine, Status
from .config import Config, load
from .drivers.ads1115 import ADS1115
from .drivers.amg8833 import AMG8833
from .drivers.ds18b20 import ProbeGroup
from .drivers.mlx90614 import MLX90614
from .drivers.sht31 import SHT31
from .logger import FireLogger
from .odor_json import record
from .outputs import FakeOutputs
from .sensors import OK_AMG8833, SensorHub

STATE_BOOT, STATE_WARMUP, STATE_OK, STATE_DEGRADED, STATE_ERROR = range(5)


def sd_notify(msg: str) -> None:
    """systemd Type=notify 에 상태 알리기 (systemd 밖에서는 아무 일도 안 함)"""
    addr = os.environ.get("NOTIFY_SOCKET")
    if not addr:
        return
    if addr.startswith("@"):
        addr = "\0" + addr[1:]
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as s:
            s.connect(addr)
            s.sendall(msg.encode())
    except OSError:
        pass


class FireApp:
    def __init__(self, cfg: Config, hub: SensorHub, outputs, logger: FireLogger | None,
                 display=None, ros=None, clock=time.monotonic, wall=time.time, simulated=False,
                 clock_synced=system_info.clock_synced, log=print):
        self.cfg = cfg
        self.hub = hub
        self.outputs = outputs
        self.logger = logger
        self.display = display
        self.ros = ros
        self.clock = clock
        self.wall = wall
        self.simulated = simulated
        self.clock_synced = clock_synced
        self.log = log
        self.engine = AlarmEngine(cfg.alarm)
        self.started = clock()
        self.last_health = -1e18
        self.last: Status | None = None

    # ------------------------------------------------------------------
    def health(self, stamp: float) -> dict:
        mask = self.hub.sensor_ok_mask
        warm = self.clock() - self.started < self.cfg.alarm.smoke_warmup_s
        if not mask & OK_AMG8833 or (self.last is not None and self.last.fault):
            state = STATE_ERROR                        # 열화상 없이는 감시 불가
        elif warm:
            state = STATE_WARMUP
        elif mask == sum(s.bit for s in self.hub.slots.values()):
            state = STATE_OK
        else:
            state = STATE_DEGRADED
        msg = self.hub.last_error
        if self.last is not None and self.last.reason:
            msg = self.last.reason if not msg else f"{self.last.reason} | {msg}"
        return record("device_health", stamp, self.cfg.device_id, state=state,
                      firmware=f"fire_detect {__version__}" + (" (simulate)" if self.simulated else ""),
                      uptime_s=system_info.uptime_s() if not self.simulated else int(self.clock() - self.started),
                      sensor_ok_mask=mask, error_count=min(self.hub.error_count, 65535),
                      supply_v=system_info.supply_v() if not self.simulated else None,
                      cpu_temp_c=system_info.cpu_temp_c() if not self.simulated else None,
                      rssi_dbm=0, message=msg[:200])

    def check_reset(self) -> bool:
        asked = self.outputs.reset_pressed()
        p = Path(self.cfg.reset_file)
        try:
            if p.exists():
                p.unlink()
                asked = True
        except OSError:
            pass
        if asked:
            self.engine.request_reset()
            self.log("래치 해제 요청")
        return asked

    def step(self) -> Status:
        t = self.clock()
        stamp = self.wall()
        self.check_reset()
        frame = self.hub.read(t)
        s = self.engine.update(frame)
        if not self.clock_synced():
            s.flags |= FLAG_TIME_UNSYNCED
        if self.simulated:
            s.flags |= FLAG_SIMULATED
        self.outputs.apply(s)
        prev = self.last
        self.last = s
        if prev is None or (prev.level, prev.latched, prev.fault) != (s.level, s.latched, s.fault):
            points = ""
            probes = [v for v in s.probe_c if v == v]
            if probes:
                points += f"프로브 최고 {max(probes):.1f}℃ "
            if s.ir_object_c == s.ir_object_c:
                points += f"적외선 {s.ir_object_c:.1f}℃ "
            self.log(f"[{LEVEL_NAMES[s.level]}{' 래치' if s.latched else ''}{' 감시불가' if s.fault else ''}] "
                     f"최고 {s.surface_max_c:.1f}℃ 주변 {s.ambient_temp_c:.1f}℃ {points}연기 {s.smoke_v:.2f}V "
                     f"충전 {'허용' if s.charge_allowed else '차단'} {s.reason}")
        rec = self.logger.write_status(stamp, s) if self.logger else None
        if self.ros:
            self.ros.publish(rec or record("fire_status", stamp, self.cfg.device_id, **s.fields()))
        if t - self.last_health >= self.cfg.health_period_s:
            self.last_health = t
            h = self.health(stamp)
            if self.logger:
                self.logger.write_record(stamp, h)
            if self.ros:
                self.ros.publish(h)
        if self.display:
            try:
                self.display.show(s)
            except OSError as e:
                self.log(f"OLED 오류, 표시 끔: {e}")
                self.display = None
        return s

    def close(self):
        self.outputs.close()
        self.hub.close()
        if self.logger:
            self.logger.close()
        if self.display:
            try:
                self.display.close()
            except OSError:
                pass
        if self.ros:
            self.ros.close()


# ------------------------------------------------------------------ 조립
def build(cfg: Config, simulate: str | None, out: str | None, ros: bool, log=print):
    sc = cfg.sensors
    scen = None
    if simulate:
        from .simulate import FakeW1, Scenario, make_bus
        scen = Scenario(simulate)
        bus = make_bus(scen, sc.amg8833_address, sc.sht31_address, sc.ads1115_address, sc.smoke_divider,
                       sc.mlx90614_address)
        w1, threaded = FakeW1(scen), False                      # 가짜 1-Wire 는 바로 답하므로 스레드 없이
        clock = lambda: scen.t                                  # noqa: E731  가상 시계 (1 단계 = 1 초)
        start_wall = time.time()
        wall = lambda: start_wall + scen.t                      # noqa: E731
        outputs = FakeOutputs()
        sleep = lambda s: None                                  # noqa: E731
    else:
        from .drivers.ds18b20 import W1Sysfs
        from .drivers.i2c_bus import SMBus2Bus
        bus = SMBus2Bus(cfg.i2c_bus)
        w1, threaded = W1Sysfs(), True                          # 프로브 하나 읽는 데 0.75 초: 별도 스레드
        clock, wall, sleep = time.monotonic, time.time, time.sleep
        try:
            from .outputs import GpioOutputs
            outputs = GpioOutputs(cfg.pins)
        except Exception as e:                                  # gpiozero 없음, GPIO 접근 불가
            log(f"GPIO 출력 없이 동작 (감시, 기록만): {e}")
            outputs = FakeOutputs()

    probes = None
    if sc.ds18b20_ids or sc.ds18b20_count > 0:
        probes = ProbeGroup(w1, sc.ds18b20_ids, sc.ds18b20_count, threaded=threaded, clock=clock, log=log)
    ir = MLX90614(bus, sc.mlx90614_address) if sc.mlx90614_address >= 0 else None
    hub = SensorHub(AMG8833(bus, sc.amg8833_address, sleep=sleep), SHT31(bus, sc.sht31_address, sleep=sleep),
                    ADS1115(bus, sc.ads1115_address, sleep=sleep), sc.smoke_channel, sc.smoke_divider,
                    sc.retry_s, clock=clock, log=log, probes=probes, ir=ir)
    display = None
    if cfg.display.enabled and not simulate:
        try:
            from .display import OledDisplay
            display = OledDisplay(cfg.i2c_bus, cfg.display.address)
        except Exception as e:
            log(f"OLED 표시 없이 동작: {e}")
    logger = FireLogger(out or cfg.log.dir, cfg.device_id, cfg.log.jsonl_every_s, cfg.log.thermal, cfg.log.keep_days,
                        probe_count=probes.count if probes else 0, ir=ir is not None)
    bridge = None
    if ros:
        from .ros_bridge import RosBridge
        bridge = RosBridge(cfg.device_id)
    app = FireApp(cfg, hub, outputs, logger, display, bridge, clock=clock, wall=wall,
                  simulated=bool(simulate), clock_synced=(lambda: True) if simulate else system_info.clock_synced,
                  log=log)
    return app, scen


def run(app: FireApp, scen, period_s: float, duration_s: float | None, speed: float, reset_at: float | None):
    stop = []
    signal.signal(signal.SIGTERM, lambda *a: stop.append(1))
    app.hub.begin()
    sd_notify("READY=1")
    next_t = time.monotonic()
    steps = 0
    try:
        while not stop:
            if scen is not None and reset_at is not None and scen.t == reset_at:
                Path(app.cfg.reset_file).touch()
            app.step()
            sd_notify("WATCHDOG=1")
            steps += 1
            if scen is not None:
                scen.t += period_s
                if duration_s is not None and scen.t >= duration_s:
                    break
                if speed > 0:
                    time.sleep(period_s / speed)
            else:
                if duration_s is not None and steps * period_s >= duration_s:
                    break
                next_t += period_s
                time.sleep(max(0.0, next_t - time.monotonic()))
    except KeyboardInterrupt:
        pass
    finally:
        sd_notify("STOPPING=1")
        app.close()
    return steps


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="fire-detect", description="소형 ESS 충전 과열 감시 (ess_01)")
    ap.add_argument("--config", help="설정 YAML (없으면 기본값)")
    ap.add_argument("--simulate", choices=["overheat", "normal", "sensor_loss", "hidden_heat"], help="가짜 센서로 실행")
    ap.add_argument("--speed", type=float, default=1.0, help="시뮬레이션 배속 (0 = 기다리지 않음)")
    ap.add_argument("--duration", type=float, help="이 초만큼만 실행 (시뮬레이션은 가상 시간)")
    ap.add_argument("--reset-at", type=float, help="시뮬레이션에서 이 시각(초)에 래치 해제 버튼을 누름")
    ap.add_argument("--out", help="기록 폴더 (설정의 log.dir 대신)")
    ap.add_argument("--ros", action="store_true", help="ROS 2 로도 발행")
    ap.add_argument("--reset", action="store_true", help="실행 중인 감지기에 래치 해제 요청을 보내고 끝냄")
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--version", action="version", version=f"fire_detect {__version__}")
    a = ap.parse_args(argv)

    cfg = load(a.config)
    if a.simulate:
        cfg.reset_file = str(Path(a.out or ".") / "reset.request")
    if a.reset:
        Path(cfg.reset_file).parent.mkdir(parents=True, exist_ok=True)
        Path(cfg.reset_file).touch()
        print(f"래치 해제 요청: {cfg.reset_file}")
        return 0
    log = (lambda m: None) if a.quiet else (lambda m: print(time.strftime("%H:%M:%S"), m, flush=True))
    app, scen = build(cfg, a.simulate, a.out, a.ros, log)
    log(f"fire_detect {__version__} 시작 ({cfg.device_id}{', 시뮬레이션 ' + a.simulate if a.simulate else ''}). "
        f"기록: {app.logger.dir}")
    run(app, scen, cfg.period_s, a.duration, a.speed, a.reset_at)
    return 0


if __name__ == "__main__":
    sys.exit(main())
