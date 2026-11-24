# gate-screener — 작업 안내 (Claude용)

Gate.io USDT 무기한 선물 전 종목(약 1,000개)을 조건으로 거르는 웹 스크리너.
사용자는 한국어로 대화하며, 개발자가 아니므로 설명은 쉬운 말로 한다.

- 사이트: https://gitakchun.github.io/gate-screener/
- 저장소: https://github.com/gitakchun/gate-screener (공개)

## 구조

- `build_data.py` — Python 표준 라이브러리만 사용(설치 불필요). 전 종목 1시간봉(최근 14일)을 받아
  기간(1~7일)별 요약을 `site/data.json`으로 저장. 약 70~100초 걸림.
  `python3 build_data.py --serve` 로 로컬 실행(http://localhost:8765, 5분마다 재생성).
- `site/index.html` — 화면 전체(HTML/CSS/JS 한 파일). `data.json`(5분마다 다시 읽음)과
  Gate API `/futures/usdt/tickers`(브라우저에서 직접 호출, 20초마다)를 합쳐 지표를 계산.
  Gate API는 CORS를 허용(`access-control-allow-origin: *`)하므로 브라우저 직접 호출 가능.
- `.github/workflows/update.yml` — `build` 작업(수집 + Pages 아티팩트 업로드)과
  `deploy` 작업(배포)을 **분리**해 둠. 한 작업 안에서 업로드 직후 배포하면
  "No artifacts named github-pages" 오류가 간헐적으로 났기 때문. 다시 합치지 말 것.
- `site/data.json`은 git에 올리지 않음(.gitignore). Actions가 매번 생성.

## 지표 정의

- N일 상승률 기준 3가지: N×24시간 전 종가 대비 / N일 저점 대비 / N일 저점→이후 고점 최대 상승
- 일별 상승률: **한국시간 자정 기준** 그날 종가 ÷ 전날 종가, 오늘 칸은 현재가 기준. 표의 맨 오른쪽 열
- 거래량 배수: 최근 24h 거래대금 ÷ 그 전 7일 하루 평균
- 상장 N일 미만 종목은 첫 봉 종가를 기준가로 쓰고 "신규 n일" 표시

## 사용자가 정한 것 (바꾸지 말 것)

- 디자인: "클래식하고 AI 느낌 안 나는 트레이딩 스크리너". 각진 테두리, 촘촘한 표, Arial 12px,
  짙은 남색 상단 바, 파비콘은 남색 바탕 원숭이 얼굴, 탭 모양 빠른 조건, 줄무늬 행. 둥근 카드·알약 버튼·이모지 쓰지 않기.
  시스템 다크 모드면 어두운 테마.
- 색: 국내 관례대로 **상승 빨강, 하락 파랑**.
- 휴대폰에서 종목명 링크는 `https://gate.com/futures/USDT/{종목}`(**www 없음**)을 **같은 탭**으로 열어야
  아이폰에서 Gate 앱이 바로 열림. www.gate.com, gate.io, 새 탭, 앱 스킴(gateio:// 등)은 실제 아이폰 테스트에서 안 됐음.
  컴퓨터에서는 새 탭으로 연다(`TOUCH`/`LINK_TARGET` 상수).
- 기본 조건은 "5일 전 대비 +100% 이상"(사용자가 처음 원한 조건). 해당 종목이 0개일 때가 많다는 건 설명함.

## 미해결

- **10분마다 예약 실행(cron)이 아직 한 번도 돌지 않음** (2026-11-24 저장소 생성 후 1시간 넘게 0회,
  push 때만 실행됨). 사용자는 좀 더 기다려 보기로 함.
  계속 안 돌면 대안: cron-job.org 등 외부 서비스가 10분마다
  `POST /repos/gitakchun/gate-screener/actions/workflows/update.yml/dispatches`를 호출하게 설정
  (사용자가 GitHub 토큰을 직접 만들어 넣어야 함. 토큰은 사용자가 입력하게 할 것).
  확인: `gh run list --json event,createdAt` 에서 event가 `schedule`인 실행이 있는지.
- 공개 저장소는 60일간 커밋이 없으면 GitHub가 예약 실행을 멈춤.

## 작업 방법

- 화면을 고치면 로컬(`--serve`)에서 데스크톱·모바일(375px)·다크 모드를 확인한 뒤 push.
  push하면 Actions가 1~2분 안에 사이트에 반영. `gh run list` / `gh run watch` 로 성공 확인.
- 여러 기기에서 작업하므로 시작 전에 `git pull`.
