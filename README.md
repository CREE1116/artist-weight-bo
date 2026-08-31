# Artist Weight BO

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

## 사용 (Electron 앱)

```bash
npm start            # 개발 모드 실행 (vendor/electron-dist 프리빌드 바이너리 재사용, 다운로드 없음)
npm run build         # dist/mac-arm64/Artist Weight BO.app 생성
```

앱이 파이썬 서버를 자식 프로세스로 띄우고 창 하나를 엽니다. 시스템 python3에
`torch`/`numpy`/`Pillow`가 설치되어 있어야 합니다 (`.venv`는 패키징에 포함하지 않음 — 원본
프로젝트와 동일한 제약).

Tag Wiki는 `data/danbooru-wiki.sqlite3`(122MB, style-genome-explorer와 공유 심볼릭 링크)가
있어야 동작합니다. 개발 모드에서는 자동으로 잡히지만, 빌드된 `.app`에는 기본적으로 포함되지 않아
Tag Wiki 탭이 "not available"로 비활성 처리됩니다 — 배포 시 필요하면 `electron-builder`의
`extraResources`로 DB를 따로 넣어야 합니다.
