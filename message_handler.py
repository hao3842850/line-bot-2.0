from linebot.models import (
    TextSendMessage,
    FlexSendMessage
)

from services.roster_service import *
from services.boss_service import *
from services.kpi_service import *

from utils.time_utils import now_tw
from utils.user_utils import get_username

#王列表
def match_boss_list(ctx):
    return ctx["text"] == "王列表"

def handle_boss_list(ctx):
    line_bot_api.reply_message(
        ctx["event"].reply_token,
        TextSendMessage(build_boss_list_text())
    )
  
#王重生
def match_boss_cd(ctx):
    return ctx["text"] == "王重生"

def handle_boss_cd(ctx):
    line_bot_api.reply_message(
        ctx["event"].reply_token,
        TextSendMessage(build_boss_cd_list_text())
    )

#KPI
def match_kpi(ctx):
    return ctx["text"].upper() == "KPI"

def handle_kpi(ctx):
    now = now_tw()
    start, end = get_kpi_range(now)
    boss_db = ctx["db"]["boss"].get(ctx["group_id"], {})
    kpi_data = calculate_kpi(boss_db, start, end)

    if not kpi_data:
        reply = TextSendMessage("📊 本週尚無 KPI 紀錄")
    else:
        ranking = sorted(kpi_data.items(), key=lambda x: x[1], reverse=True)
        display = [(get_username(uid), count) for uid, count in ranking]
        reply = FlexSendMessage(
            alt_text="本週 KPI 排行榜",
            contents=build_kpi_flex(
                "📊 本週 KPI 排行榜",
                f"{start:%m/%d %H:%M} ～ {end:%m/%d %H:%M}",
                display
            )
        )

    line_bot_api.reply_message(ctx["event"].reply_token, reply)

MESSAGE_HANDLERS = [
    {"match": match_boss_list, "handle": handle_boss_list},
    {"match": match_boss_cd,   "handle": handle_boss_cd},
    {"match": match_kpi,       "handle": handle_kpi},
    # 你之後只要一直加
]


