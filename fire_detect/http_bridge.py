"""
http_bridge.py - (선택) 규격 v0.2 기록을 서버 /api/ingest 로 HTTP POST. 설정 ingest.url 이 있을 때만 쓴다.

    fire_status     판정 주기마다 (1 초)
    device_health   10 초마다

감지와 차단은 이 통로 없이도 동작한다. publish() 는 큐에 넣기만 하고 바로 돌아오고 보내기는 별도 스레드가 한다.
네트워크가 느리거나 끊겨도 판정 루프와 watchdog 은 멈추지 않는다.
  - 못 보낸 기록은 max_queue 건(기본 600, 약 10 분)까지 두고 다시 보낸다. 넘치면 오래된 것부터 버린다
  - 401, 5xx, 연결 실패: 묶음을 큐 앞에 되돌리고 retry_s 뒤 다시 보낸다 (서버가 같은 stamp 를 중복으로 거른다)
  - 413, 422 (서버가 크기, 형식으로 거절): 다시 보내도 같으므로 그 묶음을 버린다. 원본은 서버 ingest_raw 에 남는다
표준 라이브러리만 쓴다. 토큰은 파일(ingest.token_file)에서 읽고 로그에 남기지 않는다.
"""
from __future__ import annotations

import collections
import json
import threading
import time
import urllib.error
import urllib.request


class HttpBridge:
    def __init__(self, url: str, token: str, log=print, batch: int = 300, max_queue: int = 600,
                 retry_s: float = 10.0, timeout_s: float = 5.0):
        self.url = url
        self.token = token
        self.log = log
        self.batch = batch                  # 한 요청 기록 수 (서버 상한 600)
        self.retry_s = retry_s
        self.timeout_s = timeout_s
        self.queue: collections.deque = collections.deque(maxlen=max_queue)
        self.cv = threading.Condition()
        self.stopping = False
        self.last_error: str | None = None
        self.thread = threading.Thread(target=self._run, name="http_bridge", daemon=True)
        self.thread.start()

    def publish(self, rec: dict) -> None:
        with self.cv:
            self.queue.append(rec)
            self.cv.notify()

    def close(self, wait_s: float = 3.0) -> None:
        """남은 기록을 wait_s 안에서 보내 보고 끝낸다"""
        with self.cv:
            self.stopping = True
            self.cv.notify()
        self.thread.join(wait_s)

    def _run(self) -> None:
        while True:
            with self.cv:
                while not self.queue and not self.stopping:
                    self.cv.wait()
                if not self.queue:
                    return
                recs = [self.queue.popleft() for _ in range(min(self.batch, len(self.queue)))]
            if self._post(recs):
                continue
            with self.cv:
                room = self.queue.maxlen - len(self.queue)
                self.queue.extendleft(reversed(recs[len(recs) - room:] if room < len(recs) else recs))
                deadline = time.monotonic() + self.retry_s       # publish() 의 notify 로 일찍 깨도 retry_s 를 채운다
                while not self.stopping and (left := deadline - time.monotonic()) > 0:
                    self.cv.wait(left)
                if self.stopping:
                    return

    def _post(self, recs: list) -> bool:
        """True = 끝남 (보냄 또는 버림), False = 다시 보내야 함"""
        body = json.dumps({"records": recs}, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(self.url, data=body, method="POST", headers={
            "Content-Type": "application/json", "Authorization": f"Bearer {self.token}"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_s) as r:
                r.read()
            self._report(None)
            return True
        except urllib.error.HTTPError as e:
            detail = e.read(300).decode("utf-8", "replace")
            if e.code in (413, 422):
                self._report(f"서버가 {len(recs)} 건을 거절해 버림 ({e.code}): {detail}")
                return True
            self._report(f"HTTP {e.code}: {detail}")
            return False
        except (OSError, ValueError) as e:                     # URLError, 시간 초과, 연결 끊김
            self._report(f"연결 실패: {e}")
            return False

    def _report(self, msg: str | None) -> None:
        """처음 한 번과 내용이 바뀔 때만 알린다 (1 초마다 같은 오류를 찍지 않게)"""
        if msg != self.last_error:
            self.last_error = msg
            self.log(f"서버 송신 오류: {msg} (판정과 차단은 계속함)" if msg else "서버 송신 정상")


class Tee:
    """ROS 와 HTTP 를 함께 쓸 때 publish, close 를 모두에 넘긴다"""

    def __init__(self, *bridges):
        self.bridges = bridges

    def publish(self, rec: dict) -> None:
        for b in self.bridges:
            b.publish(rec)

    def close(self) -> None:
        for b in self.bridges:
            b.close()
