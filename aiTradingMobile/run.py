#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
YTC Bot - XAUUSD Signal Generator (Mobile Native Edition)
========================================================
- Lấy dữ liệu 3 khung: HTF, TTF, LTF trực tiếp từ API Twelve Data thay thế MT5 Terminal.
- Gửi request phân tích lên Gemini API mỗi khi nến signal đóng cửa.
- Chạy độc lập, gọn nhẹ trên mọi nền tảng di động Android (qua Termux) hoặc Linux VPS.
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

# ==================== HẰNG SỐ ====================
# Đổi ánh xạ phù hợp với định dạng của Twelve Data API
TIMEFRAME_MAP = {
    "M1": "1min",
    "M5": "5min",
    "M15": "15min",
    "M30": "30min",
    "H1": "1h",
    "H4": "4h",
    "D1": "1day",
}

TIMEFRAME_MINUTES = {
    "M1": 1, "M5": 5, "M15": 15, "M30": 30,
    "H1": 60, "H4": 240, "D1": 1440,
}

CLOSE_BUFFER_SECONDS = 8
RETRY_ATTEMPTS = 5      # Tăng số lần thử lại đề phòng nghẽn mạng cục bộ
RETRY_DELAY = 5         # Tăng thời gian giãn cách giữa các lần thử

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
def load_config(path: str = "configGG.yaml") -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    required = [
        ("api", "key"), ("api", "base_url"), ("api", "model"),
        ("data_provider", "api_key"),
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

    signal_tf = cfg["trading"].get("signal_timeframe")
    if signal_tf and signal_tf not in TIMEFRAME_MAP:
        raise ValueError(f"signal_timeframe không hợp lệ: {signal_tf}")

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

# ==================== CLOUD DATA PROVIDER (THAY THẾ MT5) ====================
def fetch_candles_api(symbol: str, timeframe: str, count: int, api_key: str) -> pd.DataFrame:
    """Lấy dữ liệu nến trực tiếp từ Twelve Data Cloud API"""
    # Twelve Data nhận dạng Vàng là XAU/USD thay vì viết liền
    api_symbol = "XAU/USD" if symbol == "XAUUSD" else symbol
    interval = TIMEFRAME_MAP[timeframe]
    
    url = "https://api.twelvedata.com/time_series"
    params = {
        "symbol": api_symbol,
        "interval": interval,
        "outputsize": count,
        "apikey": api_key
    }
    
    resp = requests.get(url, params=params, timeout=15)
    if resp.status_code != 200:
        raise RuntimeError(f"Data API Error: HTTP {resp.status_code}")
        
    res_data = resp.json()
    if "values" not in res_data:
        raise RuntimeError(f"Data API Error: {res_data.get('message', 'Unknown error')}")
        
    df = pd.DataFrame(res_data["values"])
    
    # Định dạng lại dữ liệu chuẩn hóa giống hệt cấu trúc cũ của bạn
    df["datetime"] = pd.to_datetime(df["datetime"])
    df["open"] = df["open"].astype(float)
    df["high"] = df["high"].astype(float)
    df["low"] = df["low"].astype(float)
    df["close"] = df["close"].astype(float)
    df["volume"] = df["volume"].astype(float)
    
    # Đảo lại nến theo thứ tự từ cũ đến mới và đổi tên cột trùng khớp logic cũ
    df = df.sort_values("datetime").reset_index(drop=True)
    df = df.rename(columns={"datetime": "time"})
    
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

# ==================== GỌI API GEMINI ====================
def call_api(cfg: Dict[str, Any], prompt: str, logger: logging.Logger) -> Dict[str, Any]:
    api_key = cfg["api"]["key"]
    base_url = cfg["api"]["base_url"]
    model = cfg["api"]["model"]
    max_tokens = cfg["api"].get("max_tokens", 8192)

    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    body = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": cfg["api"].get("temperature", 0.0),
    }

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
            if resp.status_code == 503:
                logger.warning("Google API đang quá tải (503). Đang đợi để tự động thử lại...")
                time.sleep(RETRY_DELAY * attempt)
                continue
            if resp.status_code != 200:
                logger.error(f"Response: {resp.text[:500]}")
                raise RuntimeError(f"HTTP {resp.status_code}")

            data = resp.json()
            raw = data["choices"][0]["message"]["content"]

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

            # Khớp định dạng dữ liệu đầu ra mong đợi
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

# ==================== THỜI GIAN NGƯỠNG NẾN ====================
def next_close_utc(tf_minutes: int) -> datetime:
    now = datetime.now(timezone.utc)
    minutes = now.hour * 60 + now.minute
    boundary = ((minutes // tf_minutes) + 1) * tf_minutes
    day, minute = divmod(boundary, 1440)
    return now.replace(hour=0, minute=0, second=0, microsecond=0) \
              + timedelta(days=day, minutes=minute, seconds=CLOSE_BUFFER_SECONDS)

# ==================== MAIN RUNNER ====================
def run():
    cfg = load_config("config.yaml")
    offset = cfg.get("timezone_offset", 7)
    global LOCAL_TZ
    LOCAL_TZ = get_local_tz(offset)
    logger = setup_logging(cfg["paths"]["log_file"], offset)

    symbol = cfg["trading"]["symbol"]
    signal_tf = cfg["trading"].get("signal_timeframe", "M5")
    signal_minutes = TIMEFRAME_MINUTES[signal_tf]

    # Khai báo khung thời gian
    htf_tf = cfg["data"]["htf_timeframe"]
    ttf_tf = cfg["data"]["ttf_timeframe"]
    ltf_tf = cfg["data"]["ltf_timeframe"]
    htf_count = cfg["data"]["htf_count"]
    ttf_count = cfg["data"]["ttf_count"]
    ltf_count = cfg["data"]["ltf_count"]

    data_api_key = cfg["data_provider"]["api_key"]
    account_risk_pct = cfg["trading"].get("account_risk_pct", 0.5)
    min_rr = cfg["trading"].get("min_rr", 1.5)

    template = Path(cfg["prompt"]["template_path"]).read_text(encoding="utf-8")

    # Telegram
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
        "api_connected": True,
    }

    send_telegram(tg_token, chat_log, f"🚀 Bot YTC Cloud đã khởi động thành công cho {symbol}", logger)

    next_analysis = next_close_utc(signal_minutes)
    next_status = now_local() + status_interval
    stop = {"stop": False}

    def handle_stop(signum, frame):
        logger.info("🔴 Đang tắt bot an toàn...")
        stop["stop"] = True

    signal.signal(signal.SIGINT, handle_stop)

    logger.info(f"📊 Đã khởi động! Quét nến định kỳ mỗi {signal_minutes} phút.")
    logger.info(f"⏳ Lượt phân tích đầu tiên vào lúc: {next_analysis.astimezone(LOCAL_TZ).strftime('%Y-%m-%d %H:%M:%S')} UTC+7")

    try:
        while not stop["stop"]:
            now_utc = datetime.now(timezone.utc)

            if now_utc >= next_analysis:
                try:
                    logger.info("📡 Đang lấy dữ liệu nến từ Cloud API...")
                    htf_df = fetch_candles_api(symbol, htf_tf, htf_count, data_api_key)
                    ttf_df = fetch_candles_api(symbol, ttf_tf, ttf_count, data_api_key)
                    ltf_df = fetch_candles_api(symbol, ltf_tf, ltf_count, data_api_key)

                    current_price = ttf_df.iloc[-1]["close"]
                    spread_pips = 0.1  # Do API lấy giá thô, ta gán spread trung bình của Vàng là 0.1 USD

                    session = get_session(now_utc.hour)

                    prompt = build_prompt(
                        template, htf_df, ttf_df, ltf_df,
                        symbol, current_price, spread_pips, session,
                        account_risk_pct, min_rr
                    )
                    logger.info(f"📝 Độ dài Prompt gửi đi: {len(prompt)} ký tự")

                    result = call_api(cfg, prompt, logger)
                    state["n_analysis"] += 1

                    append_history(cfg["paths"]["signal_history_file"], result)

                    log_msg = f"🪵 [{now_local().strftime('%H:%M:%S')}] {symbol} → {'TÍN HIỆU' if result.get('has_setup') else 'HOLD'}"
                    send_telegram(tg_token, chat_log, log_msg, logger)

                    if result.get("has_setup", False) or send_hold:
                        send_telegram(tg_token, chat_signal, format_signal(result), logger)
                        if result.get("has_setup", False):
                            state["n_signals"] += 1

                    state["last_signal"] = result
                    state["last_signal_time"] = now_local()
                    logger.info(f"✅ Lượt phân tích #{state['n_analysis']} thành công!")

                except Exception as e:
                    state["n_errors"] += 1
                    err = f"❌ Lỗi: {e}\n{traceback.format_exc()}"
                    logger.error(err)
                    send_telegram(tg_token, chat_log, err[:500], logger)

                next_analysis = next_close_utc(signal_minutes)
                logger.info(f"⏳ Lượt kế tiếp: {next_analysis.astimezone(LOCAL_TZ).strftime('%Y-%m-%d %H:%M:%S')} UTC+7")

            if now_local() >= next_status:
                status = (
                    f"🤖 Trạng thái hoạt động:\n"
                    f"⏱ Uptime: {str(now_local() - state['start_time']).split('.')[0]}\n"
                    f"📊 Tổng phân tích: {state['n_analysis']}\n"
                    f"📈 Số tín hiệu phát: {state['n_signals']}\n"
                    f"⚠️ Số lỗi phát sinh: {state['n_errors']}"
                )
                send_telegram(tg_token, chat_log, status, logger)
                next_status = now_local() + status_interval

            sleep_sec = max(1, min(10, (next_analysis - now_utc).total_seconds()))
            time.sleep(sleep_sec)

    except KeyboardInterrupt:
        logger.info("⌨️ Đã bấm ngắt bàn phím, dừng bot...")
    finally:
        logger.info("🧹 Đang dọn dẹp bộ nhớ...")
        import gc
        gc.collect()
        send_telegram(tg_token, chat_log, "🛑 Bot đã dừng hoạt động an toàn.", logger)
        logger.info("🛑 Bot stopped completely.")

if __name__ == "__main__":
    run()