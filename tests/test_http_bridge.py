"""http_bridge: 서버로 보내기 (가짜 HTTP 서버를 127.0.0.1 에 띄워 시험)"""
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

from fire_detect.http_bridge import HttpBridge


class FakeServer:
    """받은 본문을 모으고, codes 에 적은 응답 코드를 차례로 돌려준다 (다 쓰면 200)"""

    def __init__(self, codes=()):
        self.codes = list(codes)
        self.got = []            # (Authorization, 기록 목록, 응답 코드)
        srv = self

        class H(BaseHTTPRequestHandler):
            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                code = srv.codes.pop(0) if srv.codes else 200
                srv.got.append((self.headers["Authorization"], body["records"], code))
                self.send_response(code)
                self.end_headers()
                self.wfile.write(b"{}")

            def log_message(self, *a):
                pass

        self.httpd = HTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.httpd.server_port}/api/ingest"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def ok_records(self):
        return [r for _, recs, code in self.got if code == 200 for r in recs]

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


def wait_for(cond, timeout=5.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.01)
    return False


def rec(i, type_name="fire_status"):
    return {"type": type_name, "version": "0.2", "stamp": f"2026-11-07T00:00:{i:02d}.000Z", "device_id": "ess_01",
            "level": 0}


def test_sends_records_with_token():
    srv = FakeServer()
    b = HttpBridge(srv.url, "tok", log=lambda m: None)
    try:
        b.publish(rec(1))
        b.publish(rec(2, "device_health"))
        assert wait_for(lambda: len(srv.ok_records()) == 2)
        assert all(auth == "Bearer tok" for auth, _, _ in srv.got)
        assert [r["type"] for r in srv.ok_records()] == ["fire_status", "device_health"]
    finally:
        b.close()
        srv.close()


def test_retries_after_server_error_without_loss():
    srv = FakeServer(codes=[503])
    logs = []
    b = HttpBridge(srv.url, "tok", log=logs.append, retry_s=0.05)
    try:
        for i in range(3):
            b.publish(rec(i))
        assert wait_for(lambda: len(srv.ok_records()) == 3)
        assert [r["stamp"] for r in srv.ok_records()] == [rec(i)["stamp"] for i in range(3)]   # 순서 유지
        assert any("503" in m for m in logs) and logs[-1] == "서버 송신 정상"
    finally:
        b.close()
        srv.close()


def test_drops_batch_rejected_as_invalid():
    srv = FakeServer(codes=[422])
    b = HttpBridge(srv.url, "tok", log=lambda m: None, retry_s=0.05)
    try:
        b.publish(rec(1))
        assert wait_for(lambda: len(srv.got) == 1)
        b.publish(rec(2))
        assert wait_for(lambda: len(srv.ok_records()) == 1)
        assert srv.ok_records()[0]["stamp"] == rec(2)["stamp"]        # 거절된 1 은 다시 보내지 않음
    finally:
        b.close()
        srv.close()


def test_publish_never_blocks_when_server_is_down():
    logs = []
    b = HttpBridge("http://127.0.0.1:9/api/ingest", "tok", log=logs.append, max_queue=5, retry_s=0.05)
    t0 = time.monotonic()
    for i in range(50):
        b.publish(rec(i % 60))
    assert time.monotonic() - t0 < 0.5                                # 판정 루프를 막지 않음
    assert wait_for(lambda: any("연결 실패" in m for m in logs))
    assert len(b.queue) <= 5                                          # 오래된 것부터 버려 상한 유지
    b.close(wait_s=1.0)
