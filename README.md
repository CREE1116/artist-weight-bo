# Artist Weight BO

[Releases](https://github.com/CREE1116/artist-weight-bo/releases)에서 macOS(Apple Silicon)·Windows(x64) 빌드를 받을 수 있습니다.
압축 풀고 실행하면 됩니다 (macOS는 서명 안 된 빌드라 우클릭 → 열기 필요, Windows는 첫 실행 시
Python 의존성이 없으면 자동 설치를 시도합니다 — Python 3.10+ / pip가 PATH에 있어야 함).

고정된 작가 태그 목록의 **가중치만** 베이지안 최적화로 탐색하는 최소 도구입니다.
GA로 태그 자체를 진화시키던 기존 style-genome-explorer와 달리, 태그 집합은
config에서 고정하고 각 태그의 weight(연속값)만 탐색 변수로 둡니다.

## 원리

- 탐색 변수: `x ∈ [0,1]^d` (d = 작가 태그 수), `weight_bounds`로 실제 가중치로 역변환
- 목적함수: 관측 불가능한 잠재 선호 함수 `f(x)`. 직접 값은 모르고 A/B 승패만 앎
- 모델: Chu & Ghahramani (2005) preference-learning GP, Laplace 근사로 `f`의 사후분포 추정
  (`core/gp_preference.py`)
- 후보 제안: 매 라운드 incumbent(사후평균 최댓값) vs challenger(Thompson sampling)
  듀얼 (`core/bo_loop.py`)
- 같은 seed 고정 사용 → 매 듀얼 구도/포즈 차이 없이 화풍(가중치) 차이만 비교

## 화면 (탭)

원본 style-genome-explorer의 다크 테마/컴포넌트를 그대로 가져와 6개 탭으로 구성했습니다.

- **Tournament** — A/B 듀얼. 클릭한 쪽이 승리. "지금까지 최적 가중치 NAI 프롬프트로 복사" 버튼으로
  중간중간 현재 GP posterior 기준 최적 가중치를 클립보드에 NAI weight 문법(`w.ww::tag::`)으로 복사 가능
- **Gallery** — 지금까지 생성된 모든 이미지(양쪽 다), 라운드별 승자 표시
- **Win Record** — 라운드별 승리 가중치 로그
- **Tag Wiki** — Danbooru Wiki 2024 FTS5 검색 (참고용, 여기서 검색해도 자동으로 실험에 반영되지 않음 —
  Settings의 artist tags를 직접 편집)
- **Loss Landscape** — 현재 best point 기준, 태그 하나씩만 바꿔가며 본 GP posterior mean/std 1D 단면
  (전체 d차원 표면 대신 축별 slice)
- **Settings** — 토큰, 작가 태그, weight bounds, 프롬프트, 생성 파라미터, BO 라운드 수

## 사용 (개발 모드, 브라우저)

```bash
cd artist-weight-bo
pip install -r requirements.txt
cp config.example.json config.json   # 또는 Settings 탭에서 직접 입력
python main.py
```

`use_live_novelai: false`면 실제 API 호출 없이 mock 이미지로 UI/루프만 검증합니다.
켜면 NovelAI에 매 라운드 2장씩 과금 생성됩니다.

진행 상태는 `work/state.json`에 저장되어 중단 후 재실행 시 이어집니다
(단, 서버 재시작 시 마지막 라운드 이미지는 다시 생성됨).

## 소스에서 Electron 앱 빌드

```bash
npm install
npm start              # 개발 모드 실행
npm run build:mac      # dist/mac-arm64/Artist Weight BO.app + .zip
npx electron-builder --win zip --x64   # dist/win-unpacked + .zip
```

앱이 파이썬 서버를 자식 프로세스로 띄우고 창 하나를 엽니다. 시스템 python3가 필요하며,
`torch`/`numpy`/`Pillow`가 없으면 첫 실행 시 `pip install -r requirements.txt`를 자동으로
시도합니다(로딩 화면에 진행 로그 표시). `.venv`는 패키징에 포함하지 않습니다.

Tag Wiki는 `data/danbooru-wiki.sqlite3`(122MB, [isek-ai/danbooru-wiki-2024](data/DANBOORU_WIKI_LICENSE.md)
스냅샷)가 있어야 동작합니다. 저장소에는 포함되어 있지 않으니(git 용량 제한) 직접 넣거나, 없으면
Tag Wiki 탭이 자동으로 "not available"로 비활성 처리됩니다 — 나머지 기능(BO 탐색·프롬프트 파싱의
artist:/by: 명시 인식 등)은 그대로 동작합니다.
