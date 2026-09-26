# 매생이 효능 1분 브이로그 (인포그래픽 모션그래픽)

`maesaengi-vlog.mp4` — 60초, 1080×1920 (9:16 쇼츠/릴스), 30fps, H.264 + AAC.

| 구간 | 장면 |
|------|------|
| 0–5s | 인트로: 겨울 바다의 초록 보약, 매생이 |
| 5–11s | 매생이란? 남해안 산지 지도 + 제철(12~2월) 캘린더 |
| 11–18.5s | 효능 01 철분·칼슘: 빈혈 예방, 뼈 건강 |
| 18.5–26s | 효능 02 식이섬유: 장 건강 |
| 26–33s | 효능 03 저칼로리: 다이어트 |
| 33–40s | 효능 04 숙취 해소: 아스파라긴산 |
| 40–47s | 효능 05 면역·피부: 비타민·무기질·엽록소 |
| 47–54.5s | 꿀팁: 추천 메뉴 + "앗, 뜨거워!" 주의 |
| 54.5–60s | 요약 + 좋아요·구독 |

## 다시 렌더링하기

```bash
# 필요: node + playwright(Chromium), ffmpeg(libx264), python3
node render.mjs                    # → out/maesaengi-vlog.mp4
node render.mjs --stills 3,15,58   # 특정 시점 PNG 미리보기
```

## 남자 아나운서 나레이션 버전

원고는 `script.js`에 있어요(자막과 TTS가 같은 원고를 씀. `say`는 숫자를 한글로 풀어 읽는 발음용).
[Supertonic 3](https://github.com/supertone-inc/supertonic) 한국어 남성 음성(M1~M5)으로 오프라인 합성하고, 말할 때 BGM이 자동으로 줄어들게(덕킹) 믹싱해요.

```bash
pip install supertonic                       # 첫 실행 때 huggingface.co에서 모델(~400MB) 다운로드
python3 narration.py out/narration.wav --samples   # out/voice-M1..M5.wav 로 목소리 비교
node render.mjs --voice M1 --mix-only        # 기존 영상에 나레이션만 입혀서 → out/maesaengi-vlog-narration.mp4
```

- `index.html` — 모든 애니메이션을 `renderAt(t)` 하나로 그리는 결정적(deterministic) 타임라인. 브라우저로 열면 실시간 재생, `?t=12`를 붙이면 해당 시점에서 멈춤.
- `narration.py` — `script.js` 원고를 자막 시작 시점에 맞춰 합성하고, 자막 구간보다 길면 속도를 올려서 다시 합성.
- `bgm.py` — 표준 라이브러리만으로 만든 로파이 BGM + 장면 전환 효과음.
- `fonts/` — Noto Sans KR, Black Han Sans (SIL OFL 1.1).

※ 영상 속 효능 정보는 일반적으로 알려진 내용이며, 질병의 치료나 의학적 조언을 대신하지 않습니다.
