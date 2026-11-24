"""Gate.io USDT 무기한 선물 전 종목의 시간봉을 받아 site/data.json 을 만듭니다.

GitHub Actions가 주기적으로 이 스크립트를 돌려 GitHub Pages에 올립니다.
현재가·24h 값·펀딩비는 화면(site/index.html)이 Gate API에서 직접 받아 옵니다.

    python3 build_data.py            # site/data.json 한 번 생성
    python3 build_data.py --serve    # 로컬: 5분마다 갱신 + http://localhost:8765

공개 시세만 쓰므로 API 키가 필요 없고, 표준 라이브러리만 사용합니다.
"""

from __future__ import annotations

import argparse
import functools
import json
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

API = "https://api.gateio.ws/api/v4/futures/usdt"
SITE = Path(__file__).with_name("site")
MAX_DAYS = 7
HOURS = 24 * 14          # 최대 조회 기간 7일 + 거래량 비교 7일
SPARK_STEP = 4           # 추이 그래프: 4시간 간격 종가
KST = 9 * 3600
REQ_PER_SEC = 15         # Gate 공개 API 한도(10초 200회)보다 여유 있게
WORKERS = 8


# ---------------------------------------------------------------- 수집

class RateLimiter:
    def __init__(self, per_sec: float):
        self.interval = 1.0 / per_sec
        self.lock = threading.Lock()
        self.next_at = 0.0

    def wait(self):
        with self.lock:
            now = time.monotonic()
            at = max(now, self.next_at)
            self.next_at = at + self.interval
        if at > now:
            time.sleep(at - now)


limiter = RateLimiter(REQ_PER_SEC)


def get_json(path: str, params: dict | None = None, retries: int = 4):
    url = f"{API}{path}" + ("?" + urllib.parse.urlencode(params) if params else "")
    for attempt in range(retries):
        limiter.wait()
        try:
            req = urllib.request.Request(url, headers={"Accept": "application/json",
                                                       "User-Agent": "gate-screener"})
            with urllib.request.urlopen(req, timeout=20) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if attempt == retries - 1:
                raise
            time.sleep((3 if e.code == 429 else 1) * (attempt + 1))
        except (urllib.error.URLError, TimeoutError):
            if attempt == retries - 1:
                raise
            time.sleep(1 + attempt)
    raise RuntimeError(f"요청 실패: {url}")


def fetch_candles(contract: str):
    rows = get_json("/candlesticks", {"contract": contract, "interval": "1h", "limit": HOURS})
    out = []
    for r in rows:
        try:
            out.append((int(r["t"]), float(r["h"]), float(r["l"]), float(r["c"]),
                        float(r.get("sum") or 0)))
        except (KeyError, TypeError, ValueError):
            continue
    out.sort()
    return out


# ---------------------------------------------------------------- 계산

def r6(x: float | None):
    """JSON 크기를 줄이려고 유효숫자 6자리로."""
    return None if x is None else float(f"{x:.6g}")


def summarize(cs: list, now: int) -> dict | None:
    """한 종목의 시간봉 → 화면에서 필요한 요약값.

    화면은 여기에 현재가(실시간)를 더해 상승률을 계산합니다.
    """
    if not cs:
        return None
    hour_now = now // 3600 * 3600
    base, low, high, runup = [], [], [], []
    for n in range(1, MAX_DAYS + 1):
        start = hour_now - n * 24 * 3600          # 정확히 N×24시간 전
        before = [c for c in cs if c[0] < start]
        window = [c for c in cs if c[0] >= start] or cs[-1:]
        # N일 전 종가. 상장 N일 미만이면 첫 봉 종가(≈상장가)로 대신함
        base.append(r6(before[-1][3] if before else window[0][3]))
        lows = [c[2] for c in window]
        li = min(range(len(lows)), key=lows.__getitem__)
        low.append(r6(lows[li]))
        high.append(r6(max(c[1] for c in window)))
        runup.append(r6(max(c[1] for c in window[li:])))     # 저점 이후 고점

    # 한국시간 자정 기준 일별 종가 (최근 MAX_DAYS+1일)
    closes: dict[int, float] = {}
    for c in cs:
        closes[(c[0] + KST) // 86400] = c[3]
    today = (now + KST) // 86400
    daily = [r6(closes.get(d)) for d in range(today - MAX_DAYS, today + 1)]

    prev = [c for c in cs if c[0] < hour_now - 23 * 3600][-24 * 7:]   # 최근 24시간 이전 7일
    vol_avg = sum(c[4] for c in prev) / (len(prev) / 24) if len(prev) >= 24 else None

    spark_from = hour_now - MAX_DAYS * 24 * 3600
    spark = [r6(c[3]) for c in cs if c[0] >= spark_from][::-1][::SPARK_STEP][::-1]

    return {
        "base": base, "low": low, "high": high, "runup": runup,
        "daily": daily, "vol_avg": r6(vol_avg), "spark": spark,
        "listed_h": len(cs),
    }


def build(out_dir: Path = SITE) -> Path:
    t0 = time.time()
    contracts = get_json("/contracts")
    names = sorted(c["name"] for c in contracts
                   if c.get("status") == "trading" and not c.get("in_delisting"))
    now = int(time.time())
    result, failed = {}, []

    def job(name):
        try:
            return name, summarize(fetch_candles(name), now)
        except Exception as e:  # 개별 종목 실패는 건너뜀
            return name, e

    with ThreadPoolExecutor(WORKERS) as ex:
        for i, (name, s) in enumerate(ex.map(job, names), 1):
            if isinstance(s, Exception):
                failed.append(name)
            elif s:
                result[name] = s
            if i % 200 == 0:
                print(f"  {i}/{len(names)}", flush=True)

    if len(result) < len(names) * 0.8:
        raise RuntimeError(f"수집 실패가 너무 많음: {len(failed)}/{len(names)}")

    today = (now + KST) // 86400
    data = {
        "generated_at": now,
        "max_days": MAX_DAYS,
        "spark_step_h": SPARK_STEP,
        "day_ids": list(range(today - MAX_DAYS, today + 1)),  # daily 배열의 KST 날짜(일 번호)
        "contracts": result,
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "data.json"
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")
    tmp.replace(path)
    print(f"[ok] {len(result)}개 종목 (실패 {len(failed)}) · {path.stat().st_size/1e6:.2f}MB "
          f"· {time.time()-t0:.0f}초", flush=True)
    return path


# ---------------------------------------------------------------- 로컬 실행

def serve(port: int, host: str, every: int):
    def loop():
        while True:
            try:
                build()
            except Exception as e:
                print(f"[error] {e}", flush=True)
            time.sleep(every)

    threading.Thread(target=loop, daemon=True).start()

    class Quiet(SimpleHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def end_headers(self):
            self.send_header("Cache-Control", "no-store")
            super().end_headers()

    srv = ThreadingHTTPServer((host, port), functools.partial(Quiet, directory=str(SITE)))
    print(f"스크리너: http://localhost:{port}  (첫 수집에 1~2분 걸립니다)", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--serve", action="store_true", help="로컬 웹서버 + 주기적 갱신")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--host", default="127.0.0.1", help="0.0.0.0 이면 같은 와이파이의 다른 기기에서도 접속")
    ap.add_argument("--every", type=int, default=300, help="--serve 갱신 주기(초)")
    args = ap.parse_args()
    if args.serve:
        serve(args.port, args.host, args.every)
    else:
        try:
            build()
        except Exception as e:
            print(f"[error] {e}", file=sys.stderr)
            sys.exit(1)


if __name__ == "__main__":
    main()
