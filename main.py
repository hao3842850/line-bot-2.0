# 天堂M 吃王小幫手
from config.boss_data import (
    alias_map,
    cd_map,
    BOSS_MAP,
    fixed_bosses
)
from fastapi import FastAPI, Request, Header
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import (
    MemberJoinedEvent,
    MessageEvent,
    TextMessage,
    TextSendMessage,
    FlexSendMessage
)
from datetime import datetime, timedelta, timezone
from linebot.models import TextSendMessage, FlexSendMessage, BubbleContainer
import psycopg2
from urllib.parse import urlparse
import os
import json
from datetime import datetime, timedelta
import pytz
import asyncio
from threading import Lock
# 基本設定
db_lock = Lock()
app = FastAPI()
CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET")
CHANNEL_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
line_bot_api = LineBotApi(CHANNEL_TOKEN)
handler = WebhookHandler(CHANNEL_SECRET)
TZ = pytz.timezone("Asia/Taipei")
DB_FILE = "database.json"
DATABASE_URL = os.getenv("DATABASE_URL")
# 工具函式
def is_peak_time():
    h = now_tw().hour
    return 19 <= h <= 23
def safe_reply(event, text_msg, flex_msg=None):
    try:
        if is_peak_time() or flex_msg is None:
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text_msg)
            )
        else:
            line_bot_api.reply_message(
                event.reply_token,
                flex_msg
            )
    except Exception as e:
        print("Reply failed:", e)
def get_source_id(event):
    if event.source.type == "group":
        return event.source.group_id
    elif event.source.type == "room":
        return event.source.room_id
    else:
        return event.source.user_id
def now_tw():
    return datetime.now(TZ)
def get_username(user_id):
    try:
        profile = get_roster_profile(user_id)
        return profile["name"] if profile else "未登記玩家"
    except Exception:
        return "未知玩家"
def init_db():
    if not os.path.exists(DB_FILE):
        with open(DB_FILE, "w", encoding="utf-8") as f:
            json.dump({"boss": {}}, f, ensure_ascii=False, indent=2)
def load_db():
    with db_lock:
        with open(DB_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
def save_db(db):
    with db_lock:
        with open(DB_FILE, "w", encoding="utf-8") as f:
            json.dump(db, f, ensure_ascii=False, indent=2)
init_db()
def build_register_boss_flex(boss, kill_time, respawn_time, registrar, note=None):
    map_list = BOSS_MAP.get(boss, [])
    map_text = "、".join(map_list) if map_list else "未知"

    contents = [
            # ===== 標題 (僅 BOSS 名稱變色) =====
            {
                "type": "text",
                "text": "🔥 已登記 ", # 這行現在當作外殼
                "weight": "bold",
                "size": "lg",
                "contents": [
                    {
                        "type": "span",
                        "text": "🔥 已登記 "
                    },
                    {
                        "type": "span",
                        "text": boss,
                        "color": "#FF6D18", # 只有 BOSS 名稱會變紅色
                        "weight": "bold"
                    }
                ]
            },
            {
                "type": "separator",
                "margin": "md"
            },

        # ===== 資訊列 =====
        {
            "type": "box",
            "layout": "baseline",
            "contents": [
                {
                    "type": "text",
                    "text": "🗺️ 地圖：",
                    "size": "sm",
                    "color": "#888888",
                    "flex": 2
                },
                {
                    "type": "text",
                    "text": map_text,
                    "wrap": True,
                    "flex": 6
                }
            ]
        },
        {
            "type": "box",
            "layout": "baseline",
            "contents": [
                {
                    "type": "text",
                    "text": "🕒 死亡：",
                    "size": "sm",
                    "color": "#888888",
                    "flex": 2
                },
                {
                    "type": "text",
                    "text": kill_time,
                    "wrap": True,
                    "flex": 6
                }
            ]
        },
        {
            "type": "box",
            "layout": "baseline",
            "contents": [
                {
                    "type": "text",
                    "text": "✨ 重生：",
                    "size": "sm",
                    "color": "#888888",
                    "flex": 2
                },
                {
                    "type": "text",
                    "text": respawn_time,
                    "wrap": True,
                    "flex": 6
                }
            ]
        },
    ]

    # ===== 備註（同層級，不凸顯）=====
    if note:
        contents.append({
            "type": "box",
            "layout": "baseline",
            "contents": [
                {
                    "type": "text",
                    "text": "📌 備註：",
                    "size": "sm",
                    "color": "#888888",
                    "flex": 2
                },
                {
                    "type": "text",
                    "text": note,
                    "wrap": True,
                    "flex": 6
                }
            ]
        })

    # ===== 登記者 =====
    contents.extend([
        {
            "type": "separator",
            "margin": "lg"
        },
        {
            "type": "text",
            "text": f"👤 登記者：{registrar}",
            "size": "xs",
            "color": "#999999",
            "wrap": True
        }
    ])

    return FlexSendMessage(
        alt_text=f"已登記 {boss}",
        contents={
            "type": "bubble",
            "body": {
                "type": "box",
                "layout": "vertical",
                "spacing": "sm",
                "contents": contents
            }
        }
    )

def build_register_boss_text(boss, kill_time, respawn_time, registrar, note):
    map_list = BOSS_MAP.get(boss, [])
    map_text = "、".join(map_list) if map_list else "未知"

    msg = (
        f"已登記 {boss}\n"
        f"地圖：{map_text}\n"
        f"死亡時間：{kill_time}\n"
    )
    if note:
        msg += f"備註：{note}"
    return msg
def build_help_flex():
    bubbles = []
    # 1️⃣ 登記王
    bubbles.append({
        "type": "bubble",
        "body": {
            "type": "box",
            "layout": "vertical",
            "spacing": "sm",
            "contents": [
                {
                    "type": "text",
                    "text": "📌 登記BOSS",
                    "weight": "bold",
                    "size": "lg"
                },
                {
                    "type": "text",
                    "text": "指令格式：",
                    "weight": "bold"
                },
                {
                    "type": "text",
                    "text": "6666 四色\nK 四色\n0930 四色\n093045 四色 備註",
                    "wrap": True
                },
                {
                    "type": "text",
                    "text": "※ 6666 = 現在時間 and K = 現在時間",
                    "size": "sm",
                    "color": "#888888"
                }
            ]
        }
    })
    # 2️⃣ 查詢王
    bubbles.append({
        "type": "bubble",
        "body": {
            "type": "box",
            "layout": "vertical",
            "spacing": "sm",
            "contents": [
                {
                    "type": "text",
                    "text": "🔍 查詢歷史登記",
                    "weight": "bold",
                    "size": "lg"
                },
                {
                    "type": "text",
                    "text": "查 王名",
                    "wrap": True
                },
                {
                    "type": "text",
                    "text": "範例：\n查 四色",
                    "wrap": True
                }
            ]
        }
    })
    # 3️⃣ 出王清單
    bubbles.append({
        "type": "bubble",
        "body": {
            "type": "box",
            "layout": "vertical",
            "spacing": "sm",
            "contents": [
                {
                    "type": "text",
                    "text": "⏰ 出王清單",
                    "weight": "bold",
                    "size": "lg"
                },
                {
                    "type": "text",
                    "text": "出",
                    "wrap": True
                },
                {
                    "type": "text",
                    "text": "顯示即將重生的BOSS",
                    "size": "sm",
                    "color": "#888888"
                }
            ]
        }
    })
    # 4️⃣ clear 說明
    bubbles.append({
        "type": "bubble",
        "body": {
            "type": "box",
            "layout": "vertical",
            "spacing": "sm",
            "contents": [
                {
                    "type": "text",
                    "text": "⚠️ 清除紀錄",
                    "weight": "bold",
                    "size": "lg",
                    "color": "#D32F2F"
                },
                {
                    "type": "text",
                    "text": "clear",
                    "wrap": True
                },
                {
                    "type": "text",
                    "text": "※ 確定清除所有時間\n需按下『確定清除』",
                    "size": "sm",
                    "color": "#888888",
                    "wrap": True
                }
            ]
        }
    })
    # 5️⃣ 小技巧
    bubbles.append({
        "type": "bubble",
        "body": {
            "type": "box",
            "layout": "vertical",
            "spacing": "sm",
            "contents": [
                {
                    "type": "text",
                    "text": "📃 BOSS資料",
                    "weight": "bold",
                    "size": "lg"
                },
                {
                    "type": "text",
                    "text": "王列表➡️所有王的簡稱\n王重生➡️所有王的CD時間",
                    "wrap": True
                }
            ]
        }
    })
    # 六 
    bubbles.append({
        "type": "bubble",
        "body": {
            "type": "box",
            "layout": "vertical",
            "spacing": "sm",
            "contents": [
                {
                    "type": "text",
                    "text": "🔌開機時間",
                    "weight": "bold",
                    "size": "lg"
                },
                {
                    "type": "text",
                    "text": "開機 時間",
                    "wrap": True
                },
                {
                    "type": "text",
                    "text": "範例：\n開機 2100",
                    "wrap": True
                }
            ]
        }
    })
    return FlexSendMessage(
        alt_text="伊娃小幫手 使用說明",
        contents={
            "type": "carousel",
            "contents": bubbles
        }
    )
def build_join_roster_guide_flex():
    return FlexSendMessage(
        alt_text="歡迎加入群組，請加入名冊",
        contents={
            "type": "bubble",
            "size": "mega",
            "body": {
                "type": "box",
                "layout": "vertical",
                "spacing": "md",
                "contents": [
                    # ===== 標題 =====
                    {
                        "type": "text",
                        "text": "👋 歡迎加入群組",
                        "weight": "bold",
                        "size": "xl",
                        "wrap": True
                    },
                    {
                        "type": "text",
                        "text": "為了正確統計王表與 KPI\n請先完成名冊登記",
                        "wrap": True,
                        "size": "sm",
                        "color": "#666666"
                    },

                    {
                        "type": "separator",
                        "margin": "lg"
                    },

                    # ===== 指令區 =====
                    {
                        "type": "text",
                        "text": "✍️ 加入名冊方式",
                        "weight": "bold",
                        "size": "md"
                    },

                    {
                        "type": "box",
                        "layout": "vertical",
                        "spacing": "xs",
                        "backgroundColor": "#F7F7F7",
                        "paddingAll": "md",
                        "cornerRadius": "md",
                        "contents": [
                            {
                                "type": "text",
                                "text": "加入名冊 血盟名 遊戲角色名",
                                "size": "sm",
                                "weight": "bold",
                                "wrap": True
                            },
                            {
                                "type": "text",
                                "text": "📘 範例：加入名冊 酒窖 威士忌乄",
                                "size": "sm",
                                "color": "#777777",
                                "wrap": True
                            }
                        ]
                    },

                    {
                        "type": "separator",
                        "margin": "lg"
                    },

                    # ===== 補充說明 =====
                    {
                        "type": "text",
                        "text": "📌 完成後即可使用王表、吃王登記等功能",
                        "size": "xs",
                        "color": "#999999",
                        "wrap": True
                    }
                ]
            }
        }
    )
def build_query_record_bubble(boss, rec):
    respawn = datetime.fromisoformat(rec["respawn"]).astimezone(TZ)
    registrar = get_username(rec.get("user"))
    
    # 標題與基礎樣式
    contents = [
        {
            "type": "text",
            "text": f"📋 歷史紀錄｜{boss}",
            "weight": "bold",
            "size": "lg",
            "color": "#111111"
        },
        {
            "type": "separator",
            "margin": "md",
            "color": "#EEEEEE"
        }
    ]

    # 定義內部資料行模板
    def create_info_row(label, value, value_color="#333333", is_bold=False):
        return {
            "type": "box",
            "layout": "horizontal",
            "contents": [
                {"type": "text", "text": label, "size": "sm", "color": "#888888", "flex": 3},
                {"type": "text", "text": value, "size": "sm", "color": value_color, "flex": 7, "weight": "bold" if is_bold else "regular", "align": "end"}
            ]
        }

    # 資料區塊
    info_box = {
        "type": "box",
        "layout": "vertical",
        "margin": "lg",
        "spacing": "sm",
        "contents": [
            create_info_row("📅 登記日期", rec['date']),
            create_info_row("🕒 死亡時間", rec['kill']),
            # 重生時間用藍色加粗，方便一眼識別
            create_info_row("✨ 重生時間", respawn.strftime('%H:%M:%S'), value_color="#1756B7", is_bold=True),
            create_info_row("👤 登記者", registrar)
        ]
    }
    
    contents.append(info_box)

    # 備註區塊
    if rec.get("note"):
        contents.append({
            "type": "box",
            "layout": "vertical",
            "margin": "md",
            "paddingAll": "sm",
            "backgroundColor": "#FDFDFD",
            "contents": [
                {
                    "type": "text",
                    "text": f"📌 {rec['note']}",
                    "size": "xs",
                    "color": "#999999",
                    "wrap": True,
                }
            ]
        })

    return {
        "type": "bubble",
        "body": {
            "type": "box",
            "layout": "vertical",
            "contents": contents,
            "paddingAll": "lg"
        }
    }
def clear_confirm_flex():
    return {
      "type": "bubble",
      "size": "mega",
      "header": {
        "type": "box",
        "layout": "vertical",
        "backgroundColor": "#D32F2F",
        "contents": [
          {
            "type": "text",
            "text": "⚠️ 危險操作確認",
            "color": "#FFFFFF",
            "weight": "bold",
            "size": "md",
            "align": "center"
          }
        ]
      },
      "body": {
        "type": "box",
        "layout": "vertical",
        "spacing": "md",
        "contents": [
          {
            "type": "text",
            "text": "清除所有王表紀錄？",
            "weight": "bold",
            "size": "md",
            "wrap": True,
            "align": "center"
          },
          {
            "type": "text",
            "text": "此動作將會抹除資料庫中所有現存紀錄，且「無法復原」。請再次確認您的操作。",
            "wrap": True,
            "size": "xs",
            "color": "#888888",
            "align": "center"
          }
        ]
      },
      "footer": {
        "type": "box",
        "layout": "vertical",
        "spacing": "sm",
        "contents": [
          {
            "type": "button",
            "style": "primary",
            "color": "#D32F2F",
            "height": "sm",
            "action": {
              "type": "message",
              "label": "確定清除",
              "text": "確定清除"
            }
          },
          {
            "type": "button",
            "style": "link",
            "color": "#444444",
            "height": "sm",
            "action": {
              "type": "message",
              "label": "取消",
              "text": "取消清除"
            }
          }
        ]
      },
      "styles": {
        "footer": {
          "separator": True
        }
      }
    }
def build_boot_init_flex(base_time_str):
    return {
        "type": "bubble",
        "size": "mega",
        "body": {
            "type": "box",
            "layout": "vertical",
            "paddingAll": "lg",
            "contents": [
                {
                    "type": "text",
                    "text": "🔌 開機時間已紀錄",
                    "weight": "bold",
                    "size": "lg",
                    "color": "#2E7D32"
                },
                {
                    "type": "separator",
                    "margin": "md",
                    "color": "#EEEEEE"
                },
                {
                    "type": "box",
                    "layout": "vertical",
                    "margin": "lg",
                    "backgroundColor": "#F1F8E9",
                    "paddingAll": "md",
                    "cornerRadius": "md",
                    "contents": [
                        {
                            "type": "text",
                            "text": "🕒 開機時間",
                            "size": "xs",
                            "color": "#689F38",
                            "weight": "bold"
                        },
                        {
                            "type": "text",
                            "text": base_time_str,
                            "size": "md",
                            "weight": "bold",
                            "color": "#333333",
                            "margin": "xs"
                        }
                    ]
                },
                {
                    "type": "box",
                    "layout": "horizontal",
                    "margin": "md",
                    "contents": [
                        {
                            "type": "text",
                            "text": "ℹ️ 系統已自動補齊尚未登記的 CD 王",
                            "size": "xs",
                            "color": "#999999",
                            "wrap": True,
                            "flex": 1
                        }
                    ]
                }
            ]
        }
    }
def build_kpi_flex(title, period_text, ranking):
    rows = []
    # 定義前三名的特殊顏色與圖標
    top_styles = {
        0: {"color": "#FFD700", "weight": "bold", "icon": "🥇"},  # 金
        1: {"color": "#C0C0C0", "weight": "bold", "icon": "🥈"},  # 銀
        2: {"color": "#CD7F32", "weight": "bold", "icon": "🥉"}   # 銅
    }

    for idx, (name, count) in enumerate(ranking):
        style = top_styles.get(idx, {"color": "#666666", "weight": "regular", "icon": f"{idx+1}"})
        
        # 每一行的內容
        row_content = {
            "type": "box",
            "layout": "horizontal",
            "paddingAll": "sm",
            "contents": [
                {
                    "type": "text",
                    "text": style["icon"],
                    "size": "sm",
                    "flex": 1,
                    "align": "center",
                    "weight": style.get("weight")
                },
                {
                    "type": "text",
                    "text": name,
                    "size": "sm",
                    "flex": 4,
                    "weight": style.get("weight"),
                    "color": "#333333" if idx < 3 else "#666666"
                },
                {
                    "type": "text",
                    "text": f"{count} 次",
                    "size": "sm",
                    "align": "end",
                    "flex": 2,
                    "weight": "bold",
                    "color": style["color"] if idx < 3 else "#333333"
                }
            ]
        }
        
        # 前三名加入淡色背景強調
        if idx < 3:
            row_content["backgroundColor"] = "#F8F9FA"
            row_content["cornerRadius"] = "md"
            row_content["margin"] = "xs"

        rows.append(row_content)

    return {
        "type": "bubble",
        "size": "kilo",
        "header": {
            "type": "box",
            "layout": "vertical",
            "backgroundColor": "#1A237E",
            "contents": [
                {
                    "type": "text",
                    "text": f"🏆 {title}",
                    "color": "#FFFFFF",
                    "weight": "bold",
                    "size": "md"
                }
            ]
        },
        "body": {
            "type": "box",
            "layout": "vertical",
            "spacing": "md",
            "contents": [
                {
                    "type": "text",
                    "text": f"📅 統計區間：{period_text}",
                    "size": "xs",
                    "color": "#888888",
                },
                {
                    "type": "box",
                    "layout": "vertical",
                    "spacing": "xs",
                    "contents": rows
                }
            ]
        }
    }
def build_roster_added_flex(clan, game_name):
    return {
        "type": "bubble",
        "size": "mega",  # 成功訊息不需要太大，輕量化更精緻
        "body": {
            "type": "box",
            "layout": "vertical",
            "backgroundColor": "#FFFFFF",
            "paddingAll": "lg",
            "contents": [
                # 頂部成功圖示與文字
                {
                    "type": "box",
                    "layout": "horizontal",
                    "contents": [
                        {
                            "type": "text",
                            "text": "✅",
                            "size": "lg",
                            "flex": 0
                        },
                        {
                            "type": "text",
                            "text": "登記成功",
                            "weight": "bold",
                            "size": "md",
                            "color": "#2E7D32",
                            "margin": "md",
                            "flex": 1
                        }
                    ]
                },
                # 分割線
                {
                    "type": "separator",
                    "margin": "lg",
                    "color": "#EEEEEE"
                },
                # 資料卡片區塊
                {
                    "type": "box",
                    "layout": "vertical",
                    "margin": "lg",
                    "spacing": "sm",
                    "contents": [
                        {
                            "type": "box",
                            "layout": "horizontal",
                            "contents": [
                                {"type": "text", "text": "遊戲角色", "size": "xs", "color": "#888888", "flex": 3},
                                {"type": "text", "text": game_name, "size": "sm", "color": "#333333", "weight": "bold", "flex": 7, "align": "end"}
                            ]
                        },
                        {
                            "type": "box",
                            "layout": "horizontal",
                            "contents": [
                                {"type": "text", "text": "所屬血盟", "size": "xs", "color": "#888888", "flex": 3},
                                {"type": "text", "text": clan, "size": "sm", "color": "#333333", "weight": "bold", "flex": 7, "align": "end"}
                            ]
                        }
                    ]
                },
                # 底部小字提醒
                {
                    "type": "text",
                    "text": "您現在可以正常使用王表功能了",
                    "size": "xxs",
                    "color": "#AAAAAA",
                    "margin": "xl",
                    "align": "center"
                }
            ]
        },
        "styles": {
            "body": {
                "cornerRadius": "md"
            }
        }
    }
def build_roster_confirm_update_flex(old_name, old_clan, new_name, new_clan):
    return {
        "type": "bubble",
        "body": {
            "type": "box",
            "layout": "vertical",
            "contents": [
                {"type": "text", "text": "⚠️ 名冊已存在", "weight": "bold"},
                {"type": "text", "text": f"目前：{old_name} / {old_clan}"},
                {"type": "text", "text": f"修改為：{new_name} / {new_clan}"},
                {
                    "type": "button",
                    "action": {"type": "message", "label": "確認修改", "text": "確認修改"}
                },
                {
                    "type": "button",
                    "action": {"type": "message", "label": "取消", "text": "取消"}
                }
            ]
        }
    }
def build_roster_self_flex(game_name, clan):
    return {
        "type": "bubble",
        "body": {
            "type": "box",
            "layout": "vertical",
            "contents": [
                {"type": "text", "text": "👤 我的名冊", "weight": "bold"},
                {"type": "text", "text": f"🎮 {game_name}"},
                {"type": "text", "text": f"🏰 {clan}"}
            ]
        }
    }
def build_roster_delete_confirm_flex(game_name):
    return {
        "type": "bubble",
        "body": {
            "type": "box",
            "layout": "vertical",
            "contents": [
                {"type": "text", "text": "⚠️ 確認刪除名冊", "weight": "bold"},
                {"type": "text", "text": f"角色：{game_name}"},
                {
                    "type": "button",
                    "action": {"type": "message", "label": "確認刪除", "text": "確認刪除"}
                },
                {
                    "type": "button",
                    "action": {"type": "message", "label": "取消", "text": "取消"}
                }
            ]
        }
    }
def build_roster_deleted_flex():
    return {
        "type": "bubble",
        "body": {
            "type": "box",
            "layout": "vertical",
            "contents": [
                {"type": "text", "text": "🗑 名冊已刪除", "weight": "bold"}
            ]
        }
    }
def build_roster_search_flex(keyword, rows):
    contents = []
    if not rows:
        contents.append({
            "type": "text",
            "text": "查無符合的名冊資料",
            "size": "sm",
            "color": "#888888"
        })
    else:
        for game_name, clan_name, line_name in rows:
            contents.append({
                "type": "box",
                "layout": "vertical",
                "spacing": "xs",
                "margin": "md",
                "contents": [
                    {
                        "type": "text",
                        "text": f"🎮 角色：{game_name}",
                        "size": "sm",
                        "weight": "bold"
                    },
                    {
                        "type": "text",
                        "text": f"🏰 血盟：{clan_name}",
                        "size": "sm",
                        "weight": "bold"
                    },
                    {
                        "type": "text",
                        "text": f"📱 LINE名稱：{line_name}",
                        "size": "sm",
                        "weight": "bold"
                    },
                ]
            })
    bubble = {
        "type": "bubble",
        "size": "mega",
        "header": {
            "type": "box",
            "layout": "vertical",
            "contents": [{
                "type": "text",
                "text": f"🔍 名冊查詢：{keyword}",
                "weight": "bold",
                "size": "lg"
            }]
        },
        "body": {
            "type": "box",
            "layout": "vertical",
            "contents": contents
        }
    }
    return FlexSendMessage(
        alt_text=f"名冊查詢：{keyword}",
        contents=bubble
    )
def ensure_roster_table():
    with get_pg_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
            CREATE TABLE IF NOT EXISTS roster (
                id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,

                line_user_id TEXT NOT NULL,
                game_name TEXT NOT NULL,
                clan_name TEXT NOT NULL,
                line_name TEXT,

                created_at TIMESTAMPTZ DEFAULT NOW(),
                updated_at TIMESTAMPTZ DEFAULT NOW(),

                UNIQUE (line_user_id, game_name)
            );
            """)
        conn.commit()
def get_line_display_name(user_id):
    try:
        profile = line_bot_api.get_profile(user_id)
        return profile.display_name
    except Exception:
        return None
def query_roster(clan_name=None):
    with get_pg_conn() as conn:
        with conn.cursor() as cur:
            if clan_name:
                cur.execute("""
                    SELECT game_name, clan_name, COALESCE(line_name, '') as line_name
                    FROM roster
                    WHERE clan_name = %s
                    ORDER BY created_at
                """, (clan_name,))
            else:
                cur.execute("""
                    SELECT game_name, clan_name, COALESCE(line_name, '') as line_name
                    FROM roster
                    ORDER BY clan_name, created_at
                """)
            return cur.fetchall()
def search_roster(keyword):
    with get_pg_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT game_name, clan_name, COALESCE(line_name, '') as line_name
                FROM roster
                WHERE game_name ILIKE %s
                   OR clan_name ILIKE %s
                   OR line_name ILIKE %s
                ORDER BY clan_name, game_name;
            """, (f"%{keyword}%", f"%{keyword}%", f"%{keyword}%"))
            return cur.fetchall()
def build_boss_list_text():
    lines = ["📜【王列表（含所有簡稱）】", ""]
    for boss, aliases in alias_map.items():
        alias_text = "、".join(aliases)
        lines.append(f"🔹 {boss}")
        lines.append(f"   ➜ {alias_text}")
        lines.append("")
    return "\n".join(lines)
def build_boss_cd_list_text():
    lines = ["⏳【王重生時間一覽】", ""]
    for boss, cd in sorted(cd_map.items(), key=lambda x: x[1]):  # 小數轉成 小時 + 分鐘
        hours = int(cd)
        minutes = int((cd - hours) * 60)
        if minutes > 0:
            cd_text = f"{hours} 小時 {minutes} 分"
        else:
            cd_text = f"{hours} 小時"
        lines.append(f"🔹 {boss}：{cd_text}")
    return "\n".join(lines)
def build_roster_flex(rows):
    body_contents = []

    # === 標題欄位列 ===
    body_contents.append({
        "type": "box",
        "layout": "horizontal",
        "paddingAll": "8px",
        "backgroundColor": "#333333",  # 深色背景讓標題更醒目
        "contents": [
            {"type": "text", "text": "角色", "flex": 3, "size": "xs", "color": "#FFFFFF", "weight": "bold"},
            {"type": "text", "text": "血盟", "flex": 2, "size": "xs", "color": "#FFFFFF", "weight": "bold", "align": "center"},
            {"type": "text", "text": "LINE", "flex": 2, "size": "xs", "color": "#FFFFFF", "weight": "bold", "align": "end"}
        ]
    })

    # === 資料列 (帶斑馬紋邏輯) ===
    for i, (game_name, line_name, clan_name) in enumerate(rows):
        # 奇數行使用淺灰色背景
        bg_color = "#F9F9F9" if i % 2 == 1 else "#FFFFFF"
        
        body_contents.append({
            "type": "box",
            "layout": "horizontal",
            "paddingAll": "10px",
            "backgroundColor": bg_color,
            "contents": [
                {
                    "type": "text",
                    "text": game_name,
                    "flex": 3,
                    "size": "sm",
                    "weight": "bold",
                    "wrap": True,
                    "color": "#111111"
                },
                {
                    "type": "text",
                    "text": clan_name if clan_name else "-",
                    "flex": 2,
                    "size": "xs",
                    "align": "center",
                    "color": "#666666",
                    "margin": "sm"
                },
                {
                    "type": "text",
                    "text": line_name if line_name else "-",
                    "flex": 2,
                    "size": "xs",
                    "align": "end",
                    "color": "#1E90FF"  # 維持你原本的藍色區分
                }
            ]
        })

    # === 底部提醒 ===
    body_contents.append({
        "type": "box",
        "layout": "vertical",
        "margin": "md",
        "contents": [
            {"type": "separator", "color": "#EEEEEE"},
            {
                "type": "text",
                "text": "💡 資料有誤請連繫 @H. 進行修正",
                "size": "xxs",
                "color": "#AAAAAA",
                "align": "center",
                "margin": "md"
            }
        ]
    })

    return {
        "type": "bubble",
        "size": "mega",
        "header": {
            "type": "box",
            "layout": "vertical",
            "backgroundColor": "#F4F4F4",
            "paddingAll": "12px",
            "contents": [
                {
                    "type": "text",
                    "text": "📖 名冊資料",
                    "weight": "bold",
                    "size": "md",
                    "color": "#444444"
                }
            ]
        },
        "body": {
            "type": "box",
            "layout": "vertical",
            "spacing": "none",
            "paddingAll": "0px",  # 滿版表格感
            "contents": body_contents
        }
    }
# 邏輯函式
def get_roster_profile(user_id):
    row = roster_get_by_user(user_id)
    if not row:
        return None
    game_name, clan_name, line_name = row
    return {
        "name": game_name,
        "clan": clan_name,
        "line_name": line_name
    }
def get_boss(name):
    for boss, aliases in alias_map.items():
        if name in aliases:
            return boss
    return None
def parse_time(token):
    now = now_tw()
    try:
        if token in ("6", "6666", "K", "k"):
            return now
        if token.isdigit() and len(token) == 4:
            h = int(token[:2])
            m = int(token[2:])
            if h > 23 or m > 59:
                return None
            t = now.replace(hour=h, minute=m, second=0)
            if t > now:
                t -= timedelta(days=1)
            return t
        if token.isdigit() and len(token) == 6:
            h = int(token[:2])
            m = int(token[2:4])
            s = int(token[4:])
            if h > 23 or m > 59 or s > 59:
                return None
            t = now.replace(hour=h, minute=m, second=s)
            if t > now:
                t -= timedelta(days=1)
            return t
    except Exception:
        return None
    return None
def get_next_fixed_time(time_list):
    now = now_tw()
    today = now.strftime("%Y-%m-%d")
    times = []
    for t in time_list:
        dt = TZ.localize(datetime.strptime(f"{today} {t}", "%Y-%m-%d %H:%M"))
        if dt >= now:
            times.append(dt)
    if times:
        return min(times)
    tomorrow = (now + timedelta(days=1)).strftime("%Y-%m-%d")
    return TZ.localize(datetime.strptime(f"{tomorrow} {time_list[0]}", "%Y-%m-%d %H:%M"))
def get_next_fixed_time_fixed(boss_conf):
    now = now_tw()
    today = now.date()
    for day_offset in range(0, 8):  # 最多找一週
        current_date = today + timedelta(days=day_offset)
        weekday = current_date.weekday()# 有設定 weekdays，但今天不在 → 跳過
        if "weekdays" in boss_conf and weekday not in boss_conf["weekdays"]:
            continue
        for t in boss_conf["times"]:
            dt = TZ.localize(
                datetime.strptime(
                    f"{current_date} {t}",
                    "%Y-%m-%d %H:%M"
                )
            )
            if dt >= now:
                return dt
    return None
def init_cd_boss_with_given_time(db, group_id, base_time):
    db.setdefault("boss", {})
    db["boss"].setdefault(group_id, {})
    boss_db = db["boss"][group_id]
    for boss, cd in cd_map.items(): # 已有紀錄就跳過
        if boss in boss_db and boss_db[boss]:
            continue
        respawn = base_time + timedelta(hours=cd)
        boss_db.setdefault(boss, []).append({
            "date": base_time.strftime("%Y-%m-%d"),
            "kill": base_time.strftime("%H:%M:%S"),
            "respawn": respawn.isoformat(),
            "note": "開機",
            "user": "__SYSTEM__"
        })
def get_kpi_range(now):
    """
    KPI 統計區間：
    星期三 05:00 ～ 下星期三 05:00
    """
    days_since_wed = (now.weekday() - 2) % 7
    start = now - timedelta(days=days_since_wed)
    start = start.replace(hour=5, minute=0, second=0, microsecond=0)
    if now < start:
        start -= timedelta(days=7)
    end = start + timedelta(days=7)
    return start, end
def calculate_kpi(boss_db, start, end):
    """
    boss_db = db["boss"][group_id]
    回傳 dict: {user_id: count}
    排除：
    - 開機補登記 (__SYSTEM__)
    - 備份 / 多行貼上登記 (source=backup)
    """
    result = {}
    seen = set()  # KPI 去重

    for boss, records in boss_db.items():
        for rec in records:
            # 1️⃣ 排除開機補登
            if rec.get("user") == "__SYSTEM__":
                continue

            # 2️⃣ 排除備份 / 多行貼上登記
            if rec.get("source") == "backup":
                continue

            kill_dt = TZ.localize(
                datetime.strptime(
                    f"{rec['date']} {rec['kill']}",
                    "%Y-%m-%d %H:%M:%S"
                )
            )

            if not (start <= kill_dt < end):
                continue

            uid = rec["user"]
            key = (uid, boss, kill_dt)
            if key in seen:
                continue
            seen.add(key)
            result[uid] = result.get(uid, 0) + 1
    return result
def build_query_boss_flex(boss, records):
    if not records:
        return TextSendMessage("尚無紀錄")
    bubbles = []
    for rec in reversed(records):   # ⭐ 新 → 舊（保險再 reversed 一次）
        bubbles.append(build_query_record_bubble(boss, rec))
    return FlexSendMessage(
         alt_text=f"{boss} 最近紀錄",
        contents={
            "type": "carousel",
            "contents": bubbles
        }
    )
def get_pg_conn():
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL not set")
    result = urlparse(url)
    return psycopg2.connect(
        host=result.hostname,
        port=result.port,
        user=result.username,
        password=result.password,
        dbname=result.path[1:],
        sslmode="require"
    )
def roster_get_by_user(user_id):
    with get_pg_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT game_name, clan_name, line_name
                FROM roster
                WHERE line_user_id = %s
                ORDER BY updated_at DESC
                LIMIT 1

                """,
                (user_id,)
            )
            return cur.fetchone()
def roster_insert(user_id, game_name, clan_name, line_name):
    with get_pg_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO roster (line_user_id, line_name, game_name, clan_name)
                VALUES (%s, %s, %s, %s)
                """,
                (user_id, line_name, game_name, clan_name)
            )
        conn.commit()
def roster_update(user_id, game_name, clan_name):
    line_name = get_line_display_name(user_id)
    with get_pg_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE roster
                SET game_name = %s,
                    clan_name = %s,
                    line_name = %s,
                    updated_at = NOW()
                WHERE line_user_id = %s
                """,
                (game_name, clan_name, line_name, user_id)
            )
        conn.commit()
def roster_delete(user_id):
    with get_pg_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM roster WHERE line_user_id = %s",
                (user_id,)
            )
        conn.commit()
# FastAPI Webhook
@app.on_event("startup")
async def startup():
    ensure_roster_table()# asyncio.create_task(boss_reminder_loop())
@app.post("/callback")
async def callback(request: Request, x_line_signature: str = Header(None)):
    body = await request.body()
    await process_line_event(body, x_line_signature)
    return "OK"
async def process_line_event(body: bytes, signature: str):
    try:
        handler.handle(body.decode("utf-8"), signature)
    except Exception as e:
        print("LINE 背景處理錯誤:", e)
@handler.add(MemberJoinedEvent)
def handle_member_joined(event):
    # 只處理群組 / room
    if event.source.type not in ["group", "room"]:
        return
    line_bot_api.reply_message(
        event.reply_token,
        build_join_roster_guide_flex()
    )
import re
def sanitize_register_line(line: str) -> str:
    """
    清理備份 / 多行貼上的單行內容
    回傳可解析的登記行，或空字串（代表跳過）
    """
    if not line:
        return ""
    line = line.strip()
    if not line:
        return ""
    # 王表備份標題可忽略
    if line.startswith("📦") or "王表備份" in line:
        return ""
    # 分隔線或裝飾
    if line.startswith("—"):
        return ""
    # 🔥 移除「#過N」或「#過 N」
    line = re.sub(r"\s*#\s*過\s*\d+", "", line)
    # 壓縮多餘空白
    line = re.sub(r"\s{2,}", " ", line).strip()
    # 忽略多行輸入
    if "\n" in line:
        return ""
    return line
def build_kpi_backup_text(kpi_db):
    lines = ["__KPI_START__"]
    for user_id, count in kpi_db.items():
        name = get_username(user_id)
        lines.append(f"{name} {user_id} {count}")
    lines.append("__KPI_END__")
    return "\n".join(lines)
@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user = event.source.user_id
    text = event.message.text.strip()
    msg = text
    raw_text = event.message.text.strip()
    lines = raw_text.splitlines()
    success_count = 0
    failed_lines = []
    # 在進入迴圈前，先定義好模式判斷
    is_multi_register = len(lines) > 1
    # 只有包含「📦」或「備份」字眼的多行訊息，才判定為靜音備份模式
    is_backup_mode = is_multi_register and ("📦" in raw_text or "備份" in raw_text)
    db = load_db()
    group_id = get_source_id(event)
    db.setdefault("boss", {})
    db["boss"].setdefault(group_id, {})
    boss_db = db["boss"][group_id]
    clean_msg = msg.strip()
    if clean_msg == "備份" and "\n" not in msg:
        now = now_tw()
        output = []

        output.append("📦【王表備份】")
        output.append("")

        for boss, records in boss_db.items():
            if not records:
                continue
            if boss not in cd_map:
                continue

            last = records[-1]
            kill_time = last.get("kill")
            respawn_str = last.get("respawn")
            note = last.get("note", "").strip()
            if not kill_time or not respawn_str:
                continue

            # ===== 計算過幾 =====
            cd_hours = cd_map[boss]
            base_respawn = datetime.fromisoformat(respawn_str).astimezone(TZ)
            step = timedelta(hours=cd_hours)

            if now < base_respawn:
                missed = 0
            else:
                diff = now - base_respawn
                rounds_passed = int(diff.total_seconds() // step.total_seconds())
                current_respawn = base_respawn + rounds_passed * step
                passed_minutes = int((now - current_respawn).total_seconds() // 60)

                if passed_minutes <= 30:
                    missed = rounds_passed
                else:
                    missed = rounds_passed + 1

            # ===== 時間格式 hhmmss =====
            parts = kill_time.split(":")
            if len(parts) == 3:
                hhmmss = parts[0] + parts[1] + parts[2]
            elif len(parts) == 2:
                hhmmss = parts[0] + parts[1] + "00"
            else:
                continue

            # ===== 組輸出 =====
            line = f"{hhmmss} {boss}"
            if note:
                line += f" {note}"
            line += f" #過{missed}"

            output.append(line)

        reply = "\n".join(output)

        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=reply)
        )
        return
    # 名冊功能
    db.setdefault("__ROSTER_WAIT__", {})
    # === 加入名冊 ===
    if msg.startswith("加入名冊"):
        parts = msg.split(" ", 2)
        if len(parts) < 3:
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage("❌ 用法：加入名冊 血盟名 遊戲名")
            )
            return
        _, clan, game_name = parts
        # === 已存在 → 詢問是否更新 ===
        exists = roster_get_by_user(user)  # 先拿到資料
        if exists:
            old_game, old_clan, _ = exists
            db["__ROSTER_WAIT__"][user] = {
                "action": "update",
                "clan": clan,
                "name": game_name
            }
            save_db(db)
            line_bot_api.reply_message(
                event.reply_token,
                FlexSendMessage(
                    alt_text="名冊已存在",
                    contents=build_roster_confirm_update_flex(
                        old_game, old_clan, game_name, clan
                    )
                )
            )
            return
        # === 不存在 → 新增 ===
        line_name = get_line_display_name(user)
        roster_insert(user, game_name, clan, line_name)
        line_bot_api.reply_message(
            event.reply_token,
            FlexSendMessage(
                alt_text="已加入名冊",
                contents=build_roster_added_flex(clan, game_name)
            )
        )
        return

    # === 確認修改名冊 ===
    if msg == "確認修改":
        wait = db.get("__ROSTER_WAIT__", {}).get(user)
        if not wait or wait["action"] != "update":
            return
        roster_update(user, wait["name"], wait["clan"])
        db["__ROSTER_WAIT__"].pop(user)
        save_db(db)
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage("✅ 名冊已更新")
        )
        return
    # === 查自己 ===
    if msg == "查自己":
        profile = get_roster_profile(user)
        if not profile:
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage("❌ 尚未加入名冊")
            )
            return
        line_bot_api.reply_message(
            event.reply_token,
            FlexSendMessage(
                alt_text="我的名冊資料",
                contents=build_roster_self_flex(
                    profile["name"], profile["clan"]
                )
            )
        )
        return
    if msg == "刪除名冊":
        profile = get_roster_profile(user)
        if not profile:
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage("❌ 尚未加入名冊")
            )
            return
        line_bot_api.reply_message(
            event.reply_token,
            FlexSendMessage(
                alt_text="確認刪除名冊",
                contents=build_roster_delete_confirm_flex(profile["name"])
            )
        )
        return
    # === 刪除名冊 ===
    if msg == "確認刪除":
        roster_delete(user)
        line_bot_api.reply_message(
            event.reply_token,
            FlexSendMessage(
                alt_text="名冊已刪除",
                contents=build_roster_deleted_flex()
            )
        )
        return
    # === 取消（名冊）===
    if msg == "取消":
        if user in db.get("__ROSTER_WAIT__", {}):
            db["__ROSTER_WAIT__"].pop(user)
            save_db(db)
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage("❎ 已取消操作")
            )
            return
    #-----查名冊
    if text.startswith("查名冊"):
        parts = text.split(maxsplit=1)

        # 只有輸入「查名冊」
        if len(parts) == 1:
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(
                    text="用法：查名冊 關鍵字\n例如：查名冊 威士忌"
                )
            )
            return

        keyword = parts[1].strip()

        with db_lock:
            conn = psycopg2.connect(DATABASE_URL)
            cur = conn.cursor()
            cur.execute("""
                SELECT game_name, line_name, clan_name
                FROM roster
                WHERE game_name ILIKE %s
                ORDER BY game_name
                LIMIT 10
            """, (f"%{keyword}%",))
            rows = cur.fetchall()
            conn.close()

        if not rows:
            reply = TextSendMessage(text="❌ 查無符合的名冊資料")
        else:
            reply = FlexSendMessage(
                alt_text="名冊查詢結果",
                contents=build_roster_flex(rows)
            )

        line_bot_api.reply_message(event.reply_token, reply)
        return
    # 王列表
    if msg == "王列表":
        text = build_boss_list_text()
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text)
        )
        return
    # 王重生（CD 一覽）
    if msg == "王重生":
        text = build_boss_cd_list_text()
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text)
        )
        return
    # === 名冊（Flex）===
    if msg.startswith("名冊"):
        parts = msg.split(maxsplit=1)
        if len(parts) == 2:
            clan = parts[1]
            rows = query_roster(clan)
            keyword = clan
        else:
            rows = query_roster()
            keyword = "全部"
        result = []
        for game_name, clan_name in rows:
            result.append((game_name, clan_name, ""))
        reply = build_roster_search_flex(keyword, result)
        line_bot_api.reply_message(event.reply_token, reply)
        return
    # 開機 初始化 CD 王
    if msg.startswith("開機 "):
        parts = msg.split(" ", 1)
        time_token = parts[1].strip()
        base_time = parse_time(time_token)
        
        if not base_time:
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage("❌ 時間格式錯誤，請使用 HHMM 或 HHMMSS")
            )
            return
            
        init_cd_boss_with_given_time(db, group_id, base_time)
        save_db(db)
        
        # 1. 取得 Flex 字典內容
        flex_contents = build_boot_init_flex(base_time.strftime('%H:%M'))
        
        # 2. 修改此處：將字典轉換為物件並包裝送出
        line_bot_api.reply_message(
            event.reply_token,
            FlexSendMessage(
                alt_text=f"🔌 開機時間已紀錄：{base_time.strftime('%H:%M')}",
                contents=BubbleContainer.new_from_json_dict(flex_contents) # 這裡最重要！
            )
        )
        return
    # clear
    if msg == "clear":
        db.setdefault("__WAIT__", {})
        db["__WAIT__"][group_id] = {
            "user": user
        }
        save_db(db)
        flex = FlexSendMessage(
            alt_text="清除確認",
            contents=clear_confirm_flex()
        )
        line_bot_api.reply_message(event.reply_token, flex)
        return
    if msg == "確定清除":
        wait = db.get("__WAIT__", {}).get(group_id)
        if not wait or wait["user"] != user:
            return
        # ===== ① 先送出 KPI =====
        now = now_tw()
        start, end = get_kpi_range(now)
        kpi_data = calculate_kpi(boss_db, start, end)
        if kpi_data:
            ranking = sorted(
                kpi_data.items(),
                key=lambda x: x[1],
                reverse=True
            )
            display = [(get_username(uid), count) for uid, count in ranking]
            kpi_bubble = build_kpi_flex(
                "📊 本週 KPI 排行榜（清除前）",
                f"{start.strftime('%m/%d %H:%M')} ～ {end.strftime('%m/%d %H:%M')}",
                display
            )
            line_bot_api.reply_message(
                event.reply_token,
                [
                    FlexSendMessage(
                        alt_text="本週 KPI 排行榜",
                        contents=kpi_bubble
                    ),
                    TextSendMessage("🗑 清除所有紀錄")
                ]
            )
        else:
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage("📊 本週尚無 KPI 紀錄，將直接清除資料")
            )
        # ===== ② 再清除資料 =====
        db["boss"].pop(group_id, None)
        db["__WAIT__"].pop(group_id, None)
        save_db(db)
        return
    if msg == "取消清除":
        db.get("__WAIT__", {}).pop(group_id, None)
        save_db(db)
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage("❎ 已取消清除")
        )
        return
    # 查 王名
    if msg.startswith("查 "):
        name = msg.split(" ", 1)[1]
        boss = get_boss(name)
        if not boss:
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage("找不到此王")
            )
            return
        if boss not in boss_db or not boss_db[boss]:
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage("尚無紀錄")
            )
            return
        records = boss_db[boss][-5:]  # 最近 5 筆（舊 → 新）
        flex_msg = build_query_boss_flex(boss, records)
        line_bot_api.reply_message(
            event.reply_token,
            flex_msg
        )
        return
    # KPI
    if msg.upper() == "KPI":
        now = now_tw()
        start, end = get_kpi_range(now)
        kpi_data = calculate_kpi(boss_db, start, end)
        if not kpi_data:
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage("📊 本週尚無 KPI 紀錄")
            )
            return
        ranking = sorted(
            kpi_data.items(),
            key=lambda x: x[1],
            reverse=True
        )
        display = [(get_username(uid), count) for uid, count in ranking]
        bubble = build_kpi_flex(
            "📊 本週 KPI 排行榜",
            f"{start.strftime('%m/%d %H:%M')} ～ {end.strftime('%m/%d %H:%M')}",
            display
        )
        line_bot_api.reply_message(
            event.reply_token,
            FlexSendMessage(
                alt_text="本週 KPI 排行榜",
                contents=bubble
            )
        )
        return
    # 出
    is_force_full = (msg == "出出")
    if msg in ("出", "出出"):
        now = now_tw()
        time_items = []
        unregistered = []
        # ===== CD 王 =====
        for boss, cd in cd_map.items():
            if boss not in boss_db or not boss_db[boss]:
                unregistered.append(boss)
                continue
            rec = boss_db[boss][-1]
            base_respawn = datetime.fromisoformat(rec["respawn"]).astimezone(TZ)
            step = timedelta(hours=cd)
            if now < base_respawn:
                # 尚未第一次重生
                display_time = base_respawn
                passed_minutes = None
                missed = 0
            else:
                diff = now - base_respawn
                rounds_passed = int(diff.total_seconds() // step.total_seconds())
                current_respawn = base_respawn + rounds_passed * step
                passed_minutes = int((now - current_respawn).total_seconds() // 60)
                if passed_minutes <= 30:
                    # 還在這一輪 30 分鐘內 → 未打
                    display_time = current_respawn
                    missed = rounds_passed          
                else:
                    # 已超過 30 分鐘 → 真的錯過一輪
                    display_time = current_respawn + step
                    missed = rounds_passed + 1
                    passed_minutes = None
            # ===== 組顯示字串 =====
            note = rec.get("note", "").strip()
            line = f"{display_time.strftime('%H:%M:%S')} {boss}"
            if note:
                line += f"（{note}）"
            if passed_minutes is not None and passed_minutes <= 30:
                line += f" <{passed_minutes}分未打>"
            if missed > 0:
                line += f" #過{missed}"
            time_items.append((display_time, line))
        # ===== 排序（一定先完整排序）=====
        time_items.sort(key=lambda x: x[0])
        # ===== 根據時段 / 指令 決定顯示數 =====
        if is_force_full:
            display_items = time_items  # 出出 → 強制全部
        elif is_peak_time():
            display_items = time_items[:14]  # 熱門 → 限制
        else:
            display_items = time_items  # 非熱門 → 全部
        # ===== 輸出 =====
        if is_force_full:
            output = ["📢【即將重生列表｜完整】", ""]
        elif is_peak_time():
            output = ["📢【即將重生列表｜熱門】", ""]
        else:
            output = ["📢【即將重生列表】", ""]

        for _, line in display_items:
            output.append(line)

        # 熱門時段但被限制時，給提示
        if is_peak_time() and not is_force_full:
            output.append("")
            output.append("👉 輸入「出出」可查看完整列表")

        if unregistered:
            output.append("")
            output.append("— 未登記 —")
            for b in unregistered:
                output.append(b)

        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage("\n".join(output))
        )
        return
    # ===== 固定王(關閉) =====
    #    for boss, conf in fixed_bosses.items():
    #        t = get_next_fixed_time_fixed(conf)
    #        if not t:
    #           continue
    #   
    #       time_items.append(
    #            (2, t, f"{t.strftime('%H:%M:%S')} {boss}")
    #        )
    # ===== 登記王（支援多行 / 備份貼上 + KPI）=====
    restored_kpi = {}  # 放在迴圈前面
    skip_kpi = False
    for line in lines:
        raw_line = line.strip()
        if not raw_line: continue

        # 1. KPI 備份處理 (保持原樣)
        if raw_line == "__KPI_START__":
            skip_kpi = True
            continue
        if raw_line == "__KPI_END__":
            skip_kpi = False
            if restored_kpi:
                db.setdefault("kpi_backup", {})[now_tw().strftime("%Y-%m-%d")] = restored_kpi
                save_db(db)
            continue
        if skip_kpi:
            # ... (此處保留你原本解析 restored_kpi 的邏輯) ...
            continue

        # 2. 普通登記行處理
        clean_line = sanitize_register_line(raw_line)
        if not clean_line: continue

        parts = clean_line.split()
        if len(parts) < 2:
            failed_lines.append(raw_line)
            continue

        time_token = parts[0]
        boss_name = parts[1]
        note = " ".join(parts[2:]) if len(parts) > 2 else ""

        # === 解析時間 (修正 6 失敗的問題) ===
        if time_token in ["6", "6666"] or time_token.upper() == "K":
            t = now_tw()
        else:
            t = parse_time(time_token)
            
        if not t:
            failed_lines.append(raw_line)
            continue

        boss = get_boss(boss_name)
        if not boss:
            failed_lines.append(raw_line)
            continue

        cd = cd_map.get(boss)
        if cd is None: continue

        # 3. 寫入資料庫
        respawn = t + timedelta(hours=cd)
        rec = {
            "date": now_tw().strftime("%Y-%m-%d"),
            "kill": t.strftime("%H:%M:%S"),
            "respawn": respawn.isoformat(),
            "note": note,
            "user": user,
            "source": "backup" if is_backup_mode else "manual"
        }
        boss_db.setdefault(boss, []).append(rec)
        boss_db[boss] = boss_db[boss][-20:]
        success_count += 1

        # 4. 回應邏輯 (確保單行輸入 6 時會觸發)
        if not is_backup_mode:
            save_db(db) # 單次登記立即存檔
            registrar = get_username(user)
            text_msg = build_register_boss_text(boss, rec['kill'], respawn.strftime('%H:%M:%S'), registrar, note)
            flex_msg = build_register_boss_flex(boss, rec['kill'], respawn.strftime('%H:%M:%S'), registrar, note)
            safe_reply(event, text_msg, flex_msg)

    # 5. 迴圈結束後的整批存檔與備份模式回覆
    if success_count > 0:
        save_db(db)

    if is_backup_mode:
        summary_msg = f"📦 備份登記完成：成功 {success_count} 隻"
        if failed_lines:
            summary_msg += f"\n⚠️ 失敗 {len(failed_lines)} 行"
        line_bot_api.reply_message(event.reply_token, TextSendMessage(summary_msg))
@app.get("/")
def root():
    return {"status": "OK"}
import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 8000))
    )
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL 未設定")
