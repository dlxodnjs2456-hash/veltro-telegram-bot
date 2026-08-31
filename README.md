# VELTRO Telegram Scheduler Bot

VELTRO Futures Korea 커뮤니티용 예약 게시 봇입니다.

## 기능

- 지정 시간 예약 발송
- 시간별 서로 다른 게시물 등록
- 텍스트 + 여러 URL 버튼
- 버튼 1열 / 2열 배치
- 1회 / 매일 / 평일 / 특정 요일 반복
- 이미지 + 텍스트 + 버튼
- 예약 게시물 목록
- 게시물 활성/중지
- 게시물 삭제
- 즉시 테스트 발송
- 관리자 ID 제한
- SQLite 저장

## Render 설정

Build Command:

```bash
pip install -r requirements.txt
```

Start Command:

```bash
python bot.py
```

Environment Variables:

```text
BOT_TOKEN=BotFather에서 받은 토큰
ADMIN_IDS=관리자 Telegram 숫자 UID
TARGET_CHAT_ID=-100... 형태의 대상 그룹 ID
TZ=Asia/Seoul
DB_PATH=veltro_bot.db
```

> 실제 `.env` 파일이나 Bot Token은 GitHub에 올리지 마세요.

## 사용

봇 개인채팅에서 `/start`를 입력합니다.

- ➕ 게시물 등록
- 📋 예약 게시물
- 📣 테스트 발송
- 🔄 새로고침

게시물 등록 시 제목 → 본문 → 이미지 여부 → 버튼 → 버튼 배치 → 반복 방식 → 발송시간 순서로 설정합니다.
