#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
YTC Bot - XAUUSD Signal Generator
- Lấy dữ liệu 3 khung: 30m, 5m, 1m từ MT5
- Xây dựng MARKET_CONTEXT (spread, session, risk, RR)
- Gửi prompt YTC tới DeepSeek API
- Parse JSON, gửi tín hiệu qua Telegram
- Chạy mỗi khi nến 5m đóng cửa
- KHÔNG lọc giờ, KHÔNG đa timeframe
"""

import sys
import time
import json
import signal
import logging
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, Any

import yaml
import requests
import pandas as pd
import MetaTrader5 as mt5

# ==================== HẰNG SỐ ====================
TIMEFRAME_MAP = {
    "M1": mt5.TIMEFRAME_M1,
    "M5": mt5.TIMEFRAME_M5,
    "M15": mt5.TIMEFRAME_M15,
    "M30": mt5.TIMEFRAME_M30,
    "H1": mt5.TIMEFRAME_H1,
    "H4": mt5.TIMEFRAME_H4,
    "D1": mt5.TIMEFRAME_D1,
}

TIMEFRAME_MINUTES = {
    "M1": 1, "M5": 5, "M15": 15, "M30": 30,
    "H1": 60, "H4": 240, "D1": 1440,
}

CLOSE_BUFFER_SECONDS = 8
RETRY_ATTEMPTS = 3
RETRY_DELAY = 2

# ==================== MÚI GIỜ ====================
def get_local_tz(offset_hours: int = 7):
    return timezone(timedelta(hours=offset_hours))

LOCAL_TZ = get_local_tz(7)

def now_local() -> datetime:
    return datetime.now(LOCAL_TZ)

# ==================== LOGGING ====================
def setup_logging(log_file: str, offset_hours: int = 7) -> logging.Logger:
    logger = logging.getLogger("ytc_bot")
    logger.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s",
                            datefmt="%Y-%m-%d %H:%M:%S")
    tz = get_local_tz(offset_hours)
    fmt.converter = lambda *args: datetime.now(tz).timetuple()
    fh = logging.FileHandler(log_file, encoding="utf-8")
    fh.setFormatter(fmt)
    logger.addHandler(fh)
    ch = logging.StreamHandler(sys.stdout)
    ch.setFormatter(fmt)
    logger.addHandler(ch)
    return logger

# ==================== CẤU HÌNH ====================
def load_config(path: str = "config.yaml") -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    required = [
        ("api", "key"), ("api", "base_url"), ("api", "model"),
        ("trading", "symbol"),
        ("data", "htf_timeframe"), ("data", "ttf_timeframe"), ("data", "ltf_timeframe"),
        ("telegram", "token"), ("telegram", "chat_id_log"), ("telegram", "chat_id_signal"),
    ]
    for section, key in required:
        if not cfg.get(section, {}).get(key):
            raise ValueError(f"Thiếu cấu hình: {section}.{key}")

    for tf in [cfg["data"]["htf_timeframe"], cfg["data"]["ttf_timeframe"], cfg["data"]["ltf_timeframe"]]:
        if tf not in TIMEFRAME_MAP:
            raise ValueError(f"Timeframe không hợp lệ: {tf}")

    return cfg

# ==================== TELEGRAM ====================
def send_telegram(token: str, chat_id: str, text: str, logger: logging.Logger):
    if not token or not chat_id:
        return
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        for i in range(0, len(text), 4000):
            chunk = text[i:i+4000]
            resp = requests.post(url, data={"chat_id": chat_id, "text": chunk}, timeout=15)
            if resp.status_code != 200:
                logger.error(f"Telegram error {chat_id}: {resp.status_code}")
    except Exception as e:
        logger.error(f"Telegram exception: {e}")

# ==================== MT5 ====================
def mt5_connect(symbol: str, logger: logging.Logger):
    if not mt5.initialize():
        raise RuntimeError(f"MT5 init failed: {mt5.last_error()}")
    info = mt5.symbol_info(symbol)
    if info is None:
        mt5.shutdown()
        raise RuntimeError(f"Symbol '{symbol}' not found")
    if not info.visible:
        mt5.symbol_select(symbol, True)
    logger.info(f"MT5 connected: {symbol}")

def fetch_candles(symbol: str, mt5_tf: int, count: int) -> pd.DataFrame:
    rates = mt5.copy_rates_from_pos(symbol, mt5_tf, 1, count)
    if rates is None or len(rates) == 0:
        raise RuntimeError(f"No data: {mt5.last_error()}")
    df = pd.DataFrame(rates)
    df["time"] = pd.to_datetime(df["time"], unit="s")
    df = df.rename(columns={"tick_volume": "volume"})
    return df[["time", "open", "high", "low", "close", "volume"]]

def format_candles(df: pd.DataFrame) -> str:
    if df.empty:
        return "No data"
    rows = df.copy()
    rows["time"] = rows["time"].dt.strftime("%Y-%m-%d %H:%M")
    lines = ["time,open,high,low,close"]
    for _, r in rows.iterrows():
        lines.append(f"{r['time']},{r['open']:.2f},{r['high']:.2f},{r['low']:.2f},{r['close']:.2f}")
    return "\n".join(lines)

# ==================== MARKET CONTEXT ====================
def get_session(utc_hour: int) -> str:
    if 0 <= utc_hour < 8:
        return "Asia"
    elif 8 <= utc_hour < 14:
        return "London"
    elif 14 <= utc_hour < 22:
        return "NewYork"
    else:
        return "Overlap"

# ==================== XÂY DỰNG PROMPT ====================
def build_prompt(template: str, htf_df: pd.DataFrame, ttf_df: pd.DataFrame, ltf_df: pd.DataFrame,
                 symbol: str, current_price: float, spread_pips: float, session: str,
                 account_risk_pct: float, min_rr: float) -> str:
    market_context = f"""
Current Price: {current_price:.2f}
Spread: {spread_pips:.2f} pips
Session: {session}
Account Risk: {account_risk_pct}%
Min R:R: {min_rr}:1
"""
    prompt = template.replace("{{HTF_DATA}}", format_candles(htf_df))
    prompt = prompt.replace("{{TTF_DATA}}", format_candles(ttf_df))
    prompt = prompt.replace("{{LTF_DATA}}", format_candles(ltf_df))
    prompt = prompt.replace("{{MARKET_CONTEXT}}", market_context)

    if "{{" in prompt:
        raise RuntimeError("Prompt còn placeholder chưa điền")
    return prompt

# ==================== GỌI API ====================
def call_api(cfg: Dict[str, Any], prompt: str, logger: logging.Logger) -> Dict[str, Any]:
    provider = cfg["api"].get("provider", "deepseek").lower()
    api_key = cfg["api"]["key"]
    base_url = cfg["api"]["base_url"]
    model = cfg["api"]["model"]
    max_tokens = cfg["api"].get("max_tokens", 8192)
    thinking_enabled = cfg["api"].get("thinking_enabled", False)
    reasoning_effort = cfg["api"].get("reasoning_effort", "medium")

    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    body = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": cfg["api"].get("temperature", 0.0),
    }
    if provider == "deepseek" and thinking_enabled:
        body["thinking"] = {"type": "enabled"}
        if reasoning_effort:
            body["reasoning_effort"] = reasoning_effort

    for attempt in range(1, RETRY_ATTEMPTS + 1):
        try:
            logger.info(f"API attempt {attempt}/{RETRY_ATTEMPTS}")
            start = time.time()
            resp = requests.post(base_url, headers=headers, json=body, timeout=180)
            logger.info(f"Status: {resp.status_code}, time: {time.time()-start:.1f}s")

            if resp.status_code == 402:
                raise RuntimeError("Hết credit. Vui lòng nạp thêm tiền.")
            if resp.status_code == 401:
                raise RuntimeError("API key không hợp lệ.")
            if resp.status_code != 200:
                logger.error(f"Response: {resp.text[:500]}")
                raise RuntimeError(f"HTTP {resp.status_code}")

            data = resp.json()
            raw = data["choices"][0]["message"]["content"]

            # Làm sạch JSON
            cleaned = raw.strip()
            if cleaned.startswith("```json"):
                cleaned = cleaned[7:]
            elif cleaned.startswith("```"):
                cleaned = cleaned[3:]
            if cleaned.endswith("```"):
                cleaned = cleaned[:-3]
            cleaned = cleaned.strip()

            try:
                result = json.loads(cleaned)
            except json.JSONDecodeError:
                import re
                match = re.search(r'\{.*\}', cleaned, re.DOTALL)
                if match:
                    result = json.loads(match.group())
                else:
                    raise RuntimeError(f"Không tìm thấy JSON: {cleaned[:200]}")

            # Validate & fill defaults
            expected = {
                "has_setup", "setup_name", "applied_principle", "reason_cause",
                "entry_zone", "trigger_signal", "stop_loss", "target_1", "target_2",
                "risk_reward_ratio", "invalidation_condition", "confidence_score",
                "full_analysis"
            }
            missing = expected - set(result.keys())
            if missing:
                logger.warning(f"Thiếu key: {missing}")
                for k in missing:
                    if k == "confidence_score":
                        result[k] = 0
                    elif k == "risk_reward_ratio":
                        result[k] = 0.0
                    else:
                        result[k] = ""

            if isinstance(result.get("has_setup"), str):
                result["has_setup"] = result["has_setup"].lower() in ("true", "1", "yes")

            return result

        except Exception as e:
            logger.error(f"Attempt {attempt} failed: {e}")
            if attempt < RETRY_ATTEMPTS:
                time.sleep(RETRY_DELAY * attempt)
            else:
                raise

    raise RuntimeError("All API attempts failed")

# ==================== TIN NHẮN ====================
def format_signal(result: Dict[str, Any]) -> str:
    t = now_local().strftime("%Y-%m-%d %H:%M:%S")
    setup = result.get("setup_name", "NONE").upper()
    has = result.get("has_setup", False)

    setup_icons = {"BOF": "🚨", "TST": "🔄", "BPB": "🚀", "PB": "📈", "CPB": "🔁", "NONE": "⏳"}
    icon = setup_icons.get(setup, "📊")

    if not has:
        return f"{icon} {t} UTC+7\n🔴 NO SETUP\n{result.get('full_analysis', '')}"

    cause = result.get("reason_cause", "")
    direction = "⚖️"
    if "buy" in cause.lower() or "mua" in cause.lower():
        direction = "🟢 BUY"
    elif "sell" in cause.lower() or "bán" in cause.lower():
        direction = "🔴 SELL"

    return (
        f"{icon} TÍN HIỆU YTC {direction}\n"
        f"⏰ {t} UTC+7\n"
        f"📌 Setup: {setup}\n"
        f"📖 Nguyên nhân: {cause}\n"
        f"📍 Vùng Entry: {result.get('entry_zone')}\n"
        f"⚡ Trigger: {result.get('trigger_signal')}\n"
        f"🛑 SL: {result.get('stop_loss')}\n"
        f"🎯 T1: {result.get('target_1')}\n"
        f"🎯 T2: {result.get('target_2')}\n"
        f"📊 R:R: {result.get('risk_reward_ratio')}\n"
        f"🔐 Invalidation: {result.get('invalidation_condition')}\n"
        f"📈 Confidence: {result.get('confidence_score')}\n"
        f"📝 Phân tích: {result.get('full_analysis')}"
    )

def append_history(path: str, result: Dict[str, Any]):
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps({"time": now_local().isoformat(), **result}, ensure_ascii=False) + "\n")

# ==================== THỜI GIAN ====================
def next_close_utc(tf_minutes: int) -> datetime:
    now = datetime.now(timezone.utc)
    minutes = now.hour * 60 + now.minute
    boundary = ((minutes // tf_minutes) + 1) * tf_minutes
    day, minute = divmod(boundary, 1440)
    return now.replace(hour=0, minute=0, second=0, microsecond=0) \
              + timedelta(days=day, minutes=minute, seconds=CLOSE_BUFFER_SECONDS)

# ==================== MAIN ====================
def run():
    cfg = load_config("config.yaml")
    offset = cfg.get("timezone_offset", 7)
    global LOCAL_TZ
    LOCAL_TZ = get_local_tz(offset)
    logger = setup_logging(cfg["paths"]["log_file"], offset)

    symbol = cfg["trading"]["symbol"]
    htf_tf = cfg["data"]["htf_timeframe"]
    ttf_tf = cfg["data"]["ttf_timeframe"]
    ltf_tf = cfg["data"]["ltf_timeframe"]
    htf_count = cfg["data"]["htf_count"]
    ttf_count = cfg["data"]["ttf_count"]
    ltf_count = cfg["data"]["ltf_count"]

    htf_mt5 = TIMEFRAME_MAP[htf_tf]
    ttf_mt5 = TIMEFRAME_MAP[ttf_tf]
    ltf_mt5 = TIMEFRAME_MAP[ltf_tf]
    tf_minutes = TIMEFRAME_MINUTES[ttf_tf]

    account_risk_pct = cfg["trading"].get("account_risk_pct", 0.5)
    min_rr = cfg["trading"].get("min_rr", 1.5)

    mt5_connect(symbol, logger)
    template = Path(cfg["prompt"]["template_path"]).read_text(encoding="utf-8")

    tg_token = cfg["telegram"]["token"]
    chat_log = cfg["telegram"]["chat_id_log"]
    chat_signal = cfg["telegram"]["chat_id_signal"]
    status_interval = timedelta(minutes=cfg["telegram"].get("status_interval_minutes", 60))
    send_hold = cfg["telegram"].get("send_hold_to_signal", False)

    state = {
        "start_time": now_local(),
        "n_analysis": 0,
        "n_signals": 0,
        "n_errors": 0,
        "last_signal": None,
        "last_signal_time": None,
        "mt5_connected": True,
    }

    send_telegram(tg_token, chat_log, f"🚀 YTC Bot started for {symbol}", logger)

    next_analysis = next_close_utc(tf_minutes)
    next_status = now_local() + status_interval
    stop = {"stop": False}

    def handle_stop(signum, frame):
        logger.info("🔴 Received Ctrl+C, stopping bot gracefully...")
        stop["stop"] = True

    signal.signal(signal.SIGINT, handle_stop)

    logger.info(f"First analysis at {next_analysis.astimezone(LOCAL_TZ).strftime('%Y-%m-%d %H:%M:%S')} UTC+7")

    try:
        while not stop["stop"]:
            now_utc = datetime.now(timezone.utc)

            if now_utc >= next_analysis:
                try:
                    logger.info("📡 Fetching data...")
                    htf_df = fetch_candles(symbol, htf_mt5, htf_count)
                    ttf_df = fetch_candles(symbol, ttf_mt5, ttf_count)
                    ltf_df = fetch_candles(symbol, ltf_mt5, ltf_count)

                    if len(htf_df) < 30:
                        logger.warning(f"HTF candles low: {len(htf_df)}")

                    tick = mt5.symbol_info_tick(symbol)
                    if tick is None:
                        raise RuntimeError("Cannot get tick")
                    current_price = tick.bid
                    spread_usd = tick.ask - tick.bid
                    spread_pips = spread_usd * 10  # 1 pip = 0.1 USD

                    utc_hour = now_utc.hour
                    session = get_session(utc_hour)

                    prompt = build_prompt(
                        template, htf_df, ttf_df, ltf_df,
                        symbol, current_price, spread_pips, session,
                        account_risk_pct, min_rr
                    )
                    logger.info(f"📝 Prompt length: {len(prompt)} chars")

                    result = call_api(cfg, prompt, logger)
                    state["n_analysis"] += 1

                    append_history(cfg["paths"]["signal_history_file"], result)

                    log_msg = f"🪵 [{now_local().strftime('%H:%M:%S')}] {symbol} → {'SIGNAL' if result.get('has_setup') else 'HOLD'}"
                    send_telegram(tg_token, chat_log, log_msg, logger)

                    if result.get("has_setup", False) or send_hold:
                        send_telegram(tg_token, chat_signal, format_signal(result), logger)
                        if result.get("has_setup", False):
                            state["n_signals"] += 1

                    state["last_signal"] = result
                    state["last_signal_time"] = now_local()
                    logger.info(f"✅ Analysis #{state['n_analysis']}: {'SIGNAL' if result.get('has_setup') else 'HOLD'}")

                except Exception as e:
                    state["n_errors"] += 1
                    err = f"❌ Error: {e}\n{traceback.format_exc()}"
                    logger.error(err)
                    send_telegram(tg_token, chat_log, err[:500], logger)

                next_analysis = next_close_utc(tf_minutes)
                logger.info(f"⏳ Next analysis at {next_analysis.astimezone(LOCAL_TZ).strftime('%Y-%m-%d %H:%M:%S')} UTC+7")

            if now_local() >= next_status:
                status = (
                    f"🤖 Bot Status\n"
                    f"⏱ Uptime: {str(now_local() - state['start_time']).split('.')[0]}\n"
                    f"📊 Analyses: {state['n_analysis']}\n"
                    f"📈 Signals: {state['n_signals']}\n"
                    f"⚠️ Errors: {state['n_errors']}"
                )
                send_telegram(tg_token, chat_log, status, logger)
                next_status = now_local() + status_interval

            sleep_sec = max(1, min(10, (next_analysis - now_utc).total_seconds()))
            time.sleep(sleep_sec)

    except KeyboardInterrupt:
        logger.info("⌨️ KeyboardInterrupt caught, stopping...")
    finally:
        logger.info("🧹 Cleaning up resources...")
        try:
            mt5.shutdown()
            logger.info("✅ MT5 connection closed.")
        except Exception as e:
            logger.warning(f"⚠️ Error closing MT5: {e}")
        for var in ['htf_df', 'ttf_df', 'ltf_df', 'prompt']:
            if var in locals():
                try:
                    del locals()[var]
                except Exception:
                    pass
        import gc
        gc.collect()
        logger.info("🗑️ Cache and memory cleared.")
        send_telegram(tg_token, chat_log, "🛑 Bot đã dừng sạch sẽ.", logger)
        logger.info("🛑 Bot stopped completely.")

if __name__ == "__main__":
    run()