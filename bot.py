import os
import json
import logging
from datetime import datetime, timedelta, time
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, MessageHandler,
    ContextTypes, ConversationHandler, filters
)

from db import DB

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_IDS = {int(x.strip()) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip().isdigit()}
TARGET_CHAT_ID = int(os.getenv("TARGET_CHAT_ID", "0"))
TZ = ZoneInfo(os.getenv("TZ", "Asia/Seoul"))
DB_PATH = os.getenv("DB_PATH", "veltro_bot.db")

db = DB(DB_PATH)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("veltro-bot")

(TITLE, BODY, MEDIA_CHOICE, MEDIA_WAIT, BTN_DECIDE, BTN_LABEL, BTN_URL,
 BTN_LAYOUT, SCHED_TYPE, SCHED_TIME, SCHED_DAYS) = range(11)

MAIN = ReplyKeyboardMarkup([
    ["➕ 게시물 등록", "📋 예약 게시물"],
    ["📣 테스트 발송", "🔄 새로고침"]
], resize_keyboard=True)


def admin_ok(update: Update) -> bool:
    return bool(update.effective_user and update.effective_user.id in ADMIN_IDS)


async def deny(update: Update):
    if update.message:
        await update.message.reply_text("관리자만 사용할 수 있습니다.")
    elif update.callback_query:
        await update.callback_query.answer("관리자만 사용할 수 있습니다.", show_alert=True)


def keyboard(buttons, columns=2):
    if not buttons:
        return None
    rows, row = [], []
    for b in buttons:
        row.append(InlineKeyboardButton(b["text"], url=b["url"]))
        if len(row) >= columns:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    return InlineKeyboardMarkup(rows)


async def send_post(context: ContextTypes.DEFAULT_TYPE, post):
    markup = keyboard(json.loads(post["buttons_json"] or "[]"), post["button_columns"])
    if post["photo_file_id"]:
        await context.bot.send_photo(
            chat_id=TARGET_CHAT_ID,
            photo=post["photo_file_id"],
            caption=post["body"],
            reply_markup=markup,
        )
    else:
        await context.bot.send_message(
            chat_id=TARGET_CHAT_ID,
            text=post["body"],
            reply_markup=markup,
            disable_web_page_preview=True,
        )


async def scheduled_send(context: ContextTypes.DEFAULT_TYPE):
    post = db.get_post(context.job.data["post_id"])
    if not post or not post["enabled"]:
        return
    try:
        await send_post(context, post)
        if post["schedule_type"] == "once":
            db.toggle_post(post["id"])
    except Exception:
        log.exception("scheduled send failed: %s", context.job.data["post_id"])


def clear_jobs(app: Application, post_id: int):
    for job in app.job_queue.get_jobs_by_name(f"post:{post_id}"):
        job.schedule_removal()


def schedule(app: Application, post):
    clear_jobs(app, post["id"])
    if not post["enabled"]:
        return

    hh, mm = map(int, post["schedule_time"].split(":"))
    run_time = time(hh, mm, tzinfo=TZ)
    data = {"post_id": post["id"]}
    name = f"post:{post['id']}"
    kind = post["schedule_type"]

    if kind == "daily":
        app.job_queue.run_daily(scheduled_send, run_time, data=data, name=name)
    elif kind == "weekdays":
        app.job_queue.run_daily(scheduled_send, run_time, days=(1, 2, 3, 4, 5), data=data, name=name)
    elif kind == "custom":
        mapping = {"sun": 0, "mon": 1, "tue": 2, "wed": 3, "thu": 4, "fri": 5, "sat": 6}
        days = tuple(mapping[x] for x in (post["weekdays"] or "").split(",") if x in mapping)
        if days:
            app.job_queue.run_daily(scheduled_send, run_time, days=days, data=data, name=name)
    else:
        now = datetime.now(TZ)
        when = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
        if when <= now:
            when += timedelta(days=1)
        app.job_queue.run_once(scheduled_send, when, data=data, name=name)


def reschedule(app: Application):
    for post in db.list_posts():
        schedule(app, post)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not admin_ok(update):
        return await deny(update)
    await update.message.reply_text("📊 VELTRO 게시관리 봇\n\n원하는 메뉴를 선택해주세요.", reply_markup=MAIN)


async def new_post(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not admin_ok(update):
        await deny(update)
        return ConversationHandler.END
    context.user_data["draft"] = {"buttons": []}
    await update.message.reply_text("게시물 관리용 제목을 입력해주세요.\n예: 아침 브리핑", reply_markup=ReplyKeyboardRemove())
    return TITLE


async def set_title(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["draft"]["title"] = update.message.text.strip()
    await update.message.reply_text("그룹에 실제로 올라갈 메시지 본문을 입력해주세요.")
    return BODY


async def set_body(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["draft"]["body"] = update.message.text
    await update.message.reply_text("이미지를 함께 올릴까요?", reply_markup=ReplyKeyboardMarkup([["이미지 사용", "텍스트만"]], resize_keyboard=True, one_time_keyboard=True))
    return MEDIA_CHOICE


async def media_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "이미지 사용":
        await update.message.reply_text("사용할 이미지를 사진으로 보내주세요.", reply_markup=ReplyKeyboardRemove())
        return MEDIA_WAIT
    context.user_data["draft"]["photo_file_id"] = None
    return await ask_button(update, context)


async def media_wait(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["draft"]["photo_file_id"] = update.message.photo[-1].file_id
    return await ask_button(update, context)


async def ask_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("URL 버튼을 추가하시겠습니까?", reply_markup=ReplyKeyboardMarkup([["➕ 버튼 추가", "버튼 완료"]], resize_keyboard=True))
    return BTN_DECIDE


async def button_decide(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "➕ 버튼 추가":
        await update.message.reply_text("버튼 이름을 입력해주세요.", reply_markup=ReplyKeyboardRemove())
        return BTN_LABEL
    if update.message.text == "버튼 완료":
        await update.message.reply_text("버튼 배치를 선택해주세요.", reply_markup=ReplyKeyboardMarkup([["한 줄 1개", "한 줄 2개"]], resize_keyboard=True, one_time_keyboard=True))
        return BTN_LAYOUT
    await update.message.reply_text("아래 버튼 중 하나를 선택해주세요.")
    return BTN_DECIDE


async def button_label(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["button_label"] = update.message.text.strip()
    await update.message.reply_text("버튼 URL을 입력해주세요.\n예: https://t.me/veltro_support")
    return BTN_URL


async def button_url(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = update.message.text.strip()
    if not url.startswith(("https://", "http://", "tg://")):
        await update.message.reply_text("http://, https:// 또는 tg:// 로 시작하는 주소를 입력해주세요.")
        return BTN_URL
    context.user_data["draft"]["buttons"].append({"text": context.user_data.pop("button_label"), "url": url})
    return await ask_button(update, context)


async def button_layout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["draft"]["button_columns"] = 1 if "1개" in update.message.text else 2
    await update.message.reply_text("반복 방식을 선택해주세요.", reply_markup=ReplyKeyboardMarkup([["1회", "매일"], ["평일", "특정 요일"]], resize_keyboard=True, one_time_keyboard=True))
    return SCHED_TYPE


async def sched_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kinds = {"1회": "once", "매일": "daily", "평일": "weekdays", "특정 요일": "custom"}
    kind = kinds.get(update.message.text)
    if not kind:
        await update.message.reply_text("목록에서 선택해주세요.")
        return SCHED_TYPE
    context.user_data["draft"]["schedule_type"] = kind
    await update.message.reply_text("발송 시간을 HH:MM 형식으로 입력해주세요.\n예: 09:00 / 18:30", reply_markup=ReplyKeyboardRemove())
    return SCHED_TIME


async def sched_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        hh, mm = map(int, update.message.text.strip().split(":"))
        assert 0 <= hh <= 23 and 0 <= mm <= 59
    except Exception:
        await update.message.reply_text("시간 형식이 잘못됐습니다. 예: 09:00")
        return SCHED_TIME
    context.user_data["draft"]["schedule_time"] = f"{hh:02d}:{mm:02d}"
    if context.user_data["draft"]["schedule_type"] == "custom":
        await update.message.reply_text("요일을 입력해주세요.\n예: mon,wed,fri\n\nmon tue wed thu fri sat sun")
        return SCHED_DAYS
    context.user_data["draft"]["weekdays"] = None
    return await save(update, context)


async def sched_days(update: Update, context: ContextTypes.DEFAULT_TYPE):
    allowed = {"mon", "tue", "wed", "thu", "fri", "sat", "sun"}
    days = [x.strip().lower() for x in update.message.text.split(",") if x.strip()]
    if not days or any(x not in allowed for x in days):
        await update.message.reply_text("예: mon,wed,fri 형식으로 입력해주세요.")
        return SCHED_DAYS
    context.user_data["draft"]["weekdays"] = ",".join(days)
    return await save(update, context)


async def save(update: Update, context: ContextTypes.DEFAULT_TYPE):
    d = context.user_data["draft"]
    post_id = db.create_post(
        title=d["title"], body=d["body"], photo_file_id=d.get("photo_file_id"),
        buttons_json=json.dumps(d["buttons"], ensure_ascii=False), button_columns=d["button_columns"],
        schedule_type=d["schedule_type"], schedule_time=d["schedule_time"], weekdays=d.get("weekdays"), enabled=1,
    )
    post = db.get_post(post_id)
    schedule(context.application, post)
    context.user_data.pop("draft", None)
    await update.message.reply_text(f"✅ 게시물 #{post_id} 저장 완료\n제목: {post['title']}\n시간: {post['schedule_time']}", reply_markup=MAIN)
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.pop("draft", None)
    await update.message.reply_text("등록을 취소했습니다.", reply_markup=MAIN)
    return ConversationHandler.END


async def list_posts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not admin_ok(update):
        return await deny(update)
    posts = db.list_posts()
    if not posts:
        return await update.message.reply_text("등록된 게시물이 없습니다.", reply_markup=MAIN)
    for p in posts[:30]:
        state = "🟢" if p["enabled"] else "⏸"
        repeat = p["schedule_type"] + (f" ({p['weekdays']})" if p["weekdays"] else "")
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("📣 테스트", callback_data=f"test:{p['id']}"),
            InlineKeyboardButton("⏯ ON/OFF", callback_data=f"toggle:{p['id']}"),
            InlineKeyboardButton("🗑 삭제", callback_data=f"delete:{p['id']}")
        ]])
        await update.message.reply_text(f"{state} #{p['id']} {p['title']}\n⏰ {p['schedule_time']} · {repeat}", reply_markup=kb)


async def test_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not admin_ok(update):
        return await deny(update)
    posts = db.list_posts()
    if not posts:
        return await update.message.reply_text("테스트할 게시물이 없습니다.")
    kb = InlineKeyboardMarkup([[InlineKeyboardButton(f"#{p['id']} {p['title']}", callback_data=f"test:{p['id']}")] for p in posts[:20]])
    await update.message.reply_text("즉시 테스트 발송할 게시물을 선택해주세요.", reply_markup=kb)


async def callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not admin_ok(update):
        return await deny(update)
    q = update.callback_query
    await q.answer()
    action, raw = q.data.split(":", 1)
    post_id = int(raw)
    post = db.get_post(post_id)
    if not post:
        return await q.edit_message_text("이미 삭제된 게시물입니다.")
    if action == "test":
        try:
            await send_post(context, post)
            await q.answer("그룹에 발송했습니다.", show_alert=True)
        except Exception:
            log.exception("test send failed")
            await q.answer("발송 실패. 봇의 그룹 권한을 확인해주세요.", show_alert=True)
    elif action == "toggle":
        enabled = db.toggle_post(post_id)
        post = db.get_post(post_id)
        schedule(context.application, post)
        await q.edit_message_text(f"{'🟢 활성' if enabled else '⏸ 중지'} #{post_id} {post['title']}\n⏰ {post['schedule_time']} · {post['schedule_type']}")
    elif action == "delete":
        clear_jobs(context.application, post_id)
        db.delete_post(post_id)
        await q.edit_message_text(f"🗑 게시물 #{post_id} 삭제 완료")


async def refresh(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not admin_ok(update):
        return await deny(update)
    reschedule(context.application)
    await update.message.reply_text("예약 스케줄을 다시 불러왔습니다.", reply_markup=MAIN)


async def post_init(app: Application):
    reschedule(app)


def main():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN이 설정되지 않았습니다.")
    if not ADMIN_IDS:
        raise RuntimeError("ADMIN_IDS가 설정되지 않았습니다.")
    if not TARGET_CHAT_ID:
        raise RuntimeError("TARGET_CHAT_ID가 설정되지 않았습니다.")

    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()
    conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex(r"^➕ 게시물 등록$"), new_post)],
        states={
            TITLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, set_title)],
            BODY: [MessageHandler(filters.TEXT & ~filters.COMMAND, set_body)],
            MEDIA_CHOICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, media_choice)],
            MEDIA_WAIT: [MessageHandler(filters.PHOTO, media_wait)],
            BTN_DECIDE: [MessageHandler(filters.TEXT & ~filters.COMMAND, button_decide)],
            BTN_LABEL: [MessageHandler(filters.TEXT & ~filters.COMMAND, button_label)],
            BTN_URL: [MessageHandler(filters.TEXT & ~filters.COMMAND, button_url)],
            BTN_LAYOUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, button_layout)],
            SCHED_TYPE: [MessageHandler(filters.TEXT & ~filters.COMMAND, sched_type)],
            SCHED_TIME: [MessageHandler(filters.TEXT & ~filters.COMMAND, sched_time)],
            SCHED_DAYS: [MessageHandler(filters.TEXT & ~filters.COMMAND, sched_days)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    app.add_handler(CommandHandler("start", start))
    app.add_handler(conv)
    app.add_handler(MessageHandler(filters.Regex(r"^📋 예약 게시물$"), list_posts))
    app.add_handler(MessageHandler(filters.Regex(r"^📣 테스트 발송$"), test_menu))
    app.add_handler(MessageHandler(filters.Regex(r"^🔄 새로고침$"), refresh))
    app.add_handler(CallbackQueryHandler(callback, pattern=r"^(test|toggle|delete):\d+$"))
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
