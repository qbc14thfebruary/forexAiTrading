"""
run.py
======
Bot tín hiệu giao dịch dùng API (DeepSeek/OpenAI/Anthropic) và MT5.
Tất cả tham số được lấy từ config.yaml, không hardcode.
Mỗi khi nến mới đóng, bot lấy dữ liệu, gọi AI, gửi tín hiệu qua Telegram.
pip install MetaTrader5 pandas numpy requests pyyaml
"""

import sys
import time
import json
import signal
import logging
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, Any, Optional, Tuple

import yaml
import requests
import pandas as pd
import numpy as np
import MetaTrader5 as mt5

# ==================== HẰNG SỐ KỸ THUẬT (ít thay đổi) ====================
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
CLOSE_BUFFER_SECONDS = 8   # đợi thêm sau khi nến đóng để MT5 cập nhật

# ==================== ĐỌC CẤU HÌNH ====================

def load_config(path: str = "config.yaml") -> Dict[str, Any]:
    """Đọc file config và kiểm tra các trường bắt buộc."""
    with open(path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    required = [
        ("api", "key"), ("api", "base_url"), ("api", "model"),
        ("trading", "symbol"), ("trading", "timeframe"),
        ("telegram", "token"), ("telegram", "chat_id_log"),
        ("telegram", "chat_id_signal"),
    ]
    for section, key in required:
        if section not in cfg or key not in cfg[section] or not cfg[section][key]:
            raise ValueError(f"Thiếu cấu hình: {section}.{key}")

    if cfg["trading"]["timeframe"] not in TIMEFRAME_MAP:
        raise ValueError(f"timeframe không hợp lệ: {cfg['trading']['timeframe']}")

    return cfg

def merge_symbol_overrides(cfg: Dict[str, Any], symbol: str) -> Dict[str, Any]:
    """Gộp các tham số ghi đè cho symbol cụ thể vào config chính."""
    overrides = cfg.get("symbol_overrides", {}).get(symbol, {})
    def deep_merge(base, override):
        for k, v in override.items():
            if k in base and isinstance(base[k], dict) and isinstance(v, dict):
                deep_merge(base[k], v)
            else:
                base[k] = v
    deep_merge(cfg, overrides)
    return cfg

# ==================== LOGGING ====================

def setup_logging(log_file: str) -> logging.Logger:
    logger = logging.getLogger("signal_bot")
    logger.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s",
                            datefmt="%Y-%m-%d %H:%M:%S")
    fh = logging.FileHandler(log_file, encoding="utf-8")
    fh.setFormatter(fmt)
    logger.addHandler(fh)
    ch = logging.StreamHandler(sys.stdout)
    ch.setFormatter(fmt)
    logger.addHandler(ch)
    return logger

# ==================== TELEGRAM ====================

def send_telegram(token: str, chat_id: str, text: str, logger: logging.Logger):
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        resp = requests.post(url, data={"chat_id": chat_id, "text": text}, timeout=15)
        if resp.status_code != 200:
            logger.error(f"Telegram error (chat_id={chat_id}): {resp.status_code} {resp.text}")
    except Exception as e:
        logger.error(f"Telegram exception: {e}")

# ==================== MT5 ====================

def mt5_connect(symbol: str, logger: logging.Logger):
    if not mt5.initialize():
        raise RuntimeError(f"MT5 initialize failed: {mt5.last_error()}")
    info = mt5.symbol_info(symbol)
    if info is None:
        mt5.shutdown()
        raise RuntimeError(f"Symbol '{symbol}' not found")
    if not info.visible:
        mt5.symbol_select(symbol, True)
    logger.info(f"Connected to MT5, symbol={symbol}")

def fetch_candles(symbol: str, mt5_timeframe: int, n_candles: int, extra: int = 0) -> pd.DataFrame:
    """Lấy n_candles nến đã đóng (không bao gồm nến hiện tại)."""
    count = n_candles + extra
    rates = mt5.copy_rates_from_pos(symbol, mt5_timeframe, 1, count)
    if rates is None or len(rates) == 0:
        raise RuntimeError(f"Không lấy được dữ liệu: {mt5.last_error()}")
    df = pd.DataFrame(rates)
    df["time"] = pd.to_datetime(df["time"], unit="s")
    df = df.rename(columns={"tick_volume": "volume"})
    return df[["time", "open", "high", "low", "close", "volume"]].reset_index(drop=True)

# ==================== CHỈ BÁO KỸ THUẬT ====================

def atr(df: pd.DataFrame, period: int) -> pd.Series:
    high, low, close = df["high"], df["low"], df["close"]
    tr = pd.concat([
        high - low,
        (high - close.shift()).abs(),
        (low - close.shift()).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(alpha=1/period, min_periods=period, adjust=False).mean()

def rsi(df: pd.DataFrame, period: int) -> pd.Series:
    delta = df["close"].diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    avg_gain = gain.ewm(alpha=1/period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, 1e-12)
    return 100 - 100 / (1 + rs)

def ema(df: pd.DataFrame, period: int) -> pd.Series:
    return df["close"].ewm(span=period, adjust=False).mean()

# ==================== SUPPORT / RESISTANCE ====================

def find_support_resistance(df: pd.DataFrame, current_price: float,
                            lookback: int, swing_window: int, cluster_pct: float) -> Tuple[float, float]:
    """Tìm vùng hỗ trợ và kháng cự mạnh gần nhất."""
    recent = df.tail(lookback).reset_index(drop=True)
    highs, lows = recent["high"].values, recent["low"].values
    n = len(recent)

    swing_highs, swing_lows = [], []
    for i in range(swing_window, n - swing_window):
        if highs[i] == max(highs[i-swing_window:i+swing_window+1]):
            swing_highs.append(highs[i])
        if lows[i] == min(lows[i-swing_window:i+swing_window+1]):
            swing_lows.append(lows[i])

    def cluster_levels(levels):
        if not levels:
            return []
        levels = sorted(levels)
        clusters = [[levels[0]]]
        for lv in levels[1:]:
            if abs(lv - clusters[-1][-1]) / max(clusters[-1][-1], 1) * 100 <= cluster_pct:
                clusters[-1].append(lv)
            else:
                clusters.append([lv])
        return sorted([(float(np.mean(c)), len(c)) for c in clusters], key=lambda x: -x[1])

    res_candidates = [lv for lv, _ in cluster_levels(swing_highs) if lv > current_price]
    sup_candidates = [lv for lv, _ in cluster_levels(swing_lows) if lv < current_price]

    resistance = min(res_candidates) if res_candidates else max(swing_highs, default=current_price)
    support = max(sup_candidates) if sup_candidates else min(swing_lows, default=current_price)
    return round(float(support), 2), round(float(resistance), 2)

# ==================== ĐỊNH DẠNG DỮ LIỆU CHO PROMPT ====================

def format_candles_table(df: pd.DataFrame, n: int) -> str:
    rows = df.tail(n).copy()
    rows["time"] = rows["time"].dt.strftime("%Y-%m-%d %H:%M")
    lines = ["time,open,high,low,close,volume"]
    for _, r in rows.iterrows():
        lines.append(f"{r['time']},{r['open']:.2f},{r['high']:.2f},{r['low']:.2f},{r['close']:.2f},{int(r['volume'])}")
    return "\n".join(lines)

# ==================== XÂY DỰNG PROMPT ====================

def build_prompt(template: str, symbol: str, timeframe: str,
                 df: pd.DataFrame, current_price: float,
                 indicator_cfg: dict, sr_cfg: dict, risk_cfg: dict) -> Tuple[str, dict]:
    """
    Tính toán tất cả chỉ báo, tìm S/R, thay thế placeholder.
    Trả về (prompt đã điền, dict các giá trị đã tính).
    """
    period_atr = indicator_cfg["atr_period"]
    period_rsi = indicator_cfg["rsi_period"]
    ema_fast = indicator_cfg["ema_fast"]
    ema_slow = indicator_cfg["ema_slow"]
    vol_avg_period = indicator_cfg["volume_avg_period"]

    df = df.copy()
    df["atr14"] = atr(df, period_atr)
    df["rsi14"] = rsi(df, period_rsi)
    df["ema20"] = ema(df, ema_fast)
    df["ema50"] = ema(df, ema_slow)
    df["vol_avg20"] = df["volume"].rolling(vol_avg_period).mean()

    last = df.iloc[-1]

    support, resistance = find_support_resistance(
        df, current_price,
        lookback=sr_cfg["lookback"],
        swing_window=sr_cfg["swing_window"],
        cluster_pct=sr_cfg["cluster_percent"]
    )

    # Lấy tham số risk
    sl_multiplier = risk_cfg.get("max_sl_atr_multiplier", 4.0)

    values = {
        "symbol": symbol,
        "timeframe": timeframe,
        "CANDLES_TABLE": format_candles_table(df, indicator_cfg["n_candles"]),
        "ATR_14": round(float(last["atr14"]), 2),
        "RSI_14": round(float(last["rsi14"]), 2),
        "EMA_20": round(float(last["ema20"]), 2),
        "EMA_50": round(float(last["ema50"]), 2),
        "VOLUME_CURRENT": int(last["volume"]),
        "VOLUME_AVG_20": round(float(last["vol_avg20"]), 2),
        "CURRENT_PRICE": round(float(current_price), 2),
        "SUPPORT_LEVEL": support,
        "RESISTANCE_LEVEL": resistance,
        "SL_MULTIPLIER": sl_multiplier,
    }

    prompt = template
    for key, val in values.items():
        prompt = prompt.replace("{{" + key + "}}", str(val))

    # Kiểm tra còn placeholder chưa thay thế
    if "{{" in prompt:
        raise RuntimeError(f"Prompt còn placeholder chưa điền: {prompt}")

    return prompt, values

# ==================== GỌI API ====================

def call_llm_api(cfg: Dict[str, Any], prompt_text: str, logger: logging.Logger) -> Dict[str, Any]:
    """
    Gọi API dựa trên provider trong config.
    Hỗ trợ: deepseek, openai, anthropic.
    """
    provider = cfg["api"].get("provider", "deepseek").lower()
    api_key = cfg["api"]["key"]
    base_url = cfg["api"]["base_url"]
    model = cfg["api"]["model"]
    max_tokens = cfg["api"].get("max_tokens", 2048)

    headers = {}
    body = {}

    if provider == "deepseek":
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        body = {
            "model": model,
            "messages": [{"role": "user", "content": prompt_text}],
            "max_tokens": max_tokens,
        }
        if cfg["api"].get("thinking_enabled", False):
            body["thinking"] = {"type": "enabled"}
            if cfg["api"].get("reasoning_effort"):
                body["reasoning_effort"] = cfg["api"]["reasoning_effort"]
        if not cfg["api"].get("thinking_enabled", False) and "temperature" in cfg["api"]:
            body["temperature"] = cfg["api"]["temperature"]

    elif provider == "openai":
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        body = {
            "model": model,
            "messages": [{"role": "user", "content": prompt_text}],
            "max_tokens": max_tokens,
            "temperature": cfg["api"].get("temperature", 0.0),
        }

    elif provider == "anthropic":
        headers = {
            "x-api-key": api_key,
            "anthropic-version": cfg["api"].get("anthropic_version", "2023-06-01"),
            "content-type": "application/json",
        }
        body = {
            "model": model,
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": prompt_text}],
        }
        if "temperature" in cfg["api"]:
            body["temperature"] = cfg["api"]["temperature"]

    else:
        raise ValueError(f"Provider không hỗ trợ: {provider}")

    logger.info(f"Gọi API {provider} model={model}")
    resp = requests.post(base_url, headers=headers, json=body, timeout=90)
    resp.raise_for_status()
    data = resp.json()

    raw_text = ""
    if provider == "anthropic":
        for block in data.get("content", []):
            if block.get("type") == "text":
                raw_text += block.get("text", "")
    else:
        raw_text = data["choices"][0]["message"]["content"]

    cleaned = raw_text.strip()
    if cleaned.startswith("```json") or cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:].strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as e:
        logger.error(f"JSON parse error. Raw: {raw_text[:200]}...")
        raise RuntimeError(f"Invalid JSON from API: {e}")

# ==================== TẠO TIN NHẮN ====================

def format_signal_message(symbol: str, timeframe: str, signal: dict) -> str:
    return (
        f"📊 {symbol} ({timeframe})\n"
        f"Action: {signal.get('action')}\n"
        f"Entry: {signal.get('entry')}\n"
        f"SL: {signal.get('sl')}\n"
        f"TP: {signal.get('tp')}\n"
        f"Confidence: {signal.get('confidence')}\n"
        f"Reason: {signal.get('reasoning_short')}\n"
        f"Time: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}"
    )

def format_log_message(symbol: str, timeframe: str, signal: dict) -> str:
    return (
        f"🪵 [{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}] "
        f"{symbol} {timeframe} -> {signal.get('action')} "
        f"(conf={signal.get('confidence')})\n"
        f"log_reason: {signal.get('log_reason')}"
    )

def format_status_message(state: dict, cfg: dict) -> str:
    uptime = datetime.now(timezone.utc) - state["start_time"]
    last_sig = state.get("last_signal")
    last_sig_str = (
        f"{last_sig['action']} @ {last_sig['entry']} (conf={last_sig['confidence']}) "
        f"lúc {state['last_signal_time'].strftime('%Y-%m-%d %H:%M:%S UTC')}"
        if last_sig else "chưa có"
    )
    return (
        f"🤖 Trạng thái bot\n"
        f"Symbol: {cfg['trading']['symbol']} ({cfg['trading']['timeframe']})\n"
        f"Uptime: {str(uptime).split('.')[0]}\n"
        f"Số lần phân tích: {state['n_analysis']}\n"
        f"Số tín hiệu BUY/SELL: {state['n_signals']}\n"
        f"Số lỗi: {state['n_errors']}\n"
        f"Tín hiệu gần nhất: {last_sig_str}\n"
        f"MT5: {'OK' if state['mt5_connected'] else 'MẤT KẾT NỐI'}"
    )

def append_signal_history(path: str, symbol: str, timeframe: str, signal: dict):
    record = {
        "time": datetime.now(timezone.utc).isoformat(),
        "symbol": symbol,
        "timeframe": timeframe,
        **signal,
    }
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")

# ==================== TÍNH THỜI GIAN NẾN ĐÓNG ====================

def next_candle_close_time(timeframe_minutes: int) -> datetime:
    now = datetime.now(timezone.utc)
    epoch_minutes = now.hour * 60 + now.minute
    next_boundary = ((epoch_minutes // timeframe_minutes) + 1) * timeframe_minutes
    day_offset, minute_of_day = divmod(next_boundary, 1440)
    close_time = now.replace(hour=0, minute=0, second=0, microsecond=0) \
                   + timedelta(days=day_offset, minutes=minute_of_day, seconds=CLOSE_BUFFER_SECONDS)
    return close_time

# ==================== HÀM CHÍNH ====================

def run():
    # Đọc config
    cfg = load_config("config.yaml")
    logger = setup_logging(cfg["paths"]["log_file"])

    # Lấy thông tin cơ bản
    symbol = cfg["trading"]["symbol"]
    timeframe_label = cfg["trading"]["timeframe"]
    mt5_timeframe = TIMEFRAME_MAP[timeframe_label]
    tf_minutes = TIMEFRAME_MINUTES[timeframe_label]

    # Gộp ghi đè cho symbol (nếu có)
    cfg = merge_symbol_overrides(cfg, symbol)

    # Lấy các tham số từ config
    indicator_cfg = cfg["indicators"]
    sr_cfg = cfg["support_resistance"]
    risk_cfg = cfg["risk_management"]

    # Kết nối MT5
    mt5_connect(symbol, logger)
    logger.info(f"Bot khởi động: {symbol} ({timeframe_label})")

    # Đọc prompt template
    template_path = cfg["prompt"]["template_path"]
    template_text = Path(template_path).read_text(encoding="utf-8")

    # Trạng thái bot
    state = {
        "start_time": datetime.now(timezone.utc),
        "n_analysis": 0,
        "n_signals": 0,
        "n_errors": 0,
        "last_signal": None,
        "last_signal_time": None,
        "mt5_connected": True,
    }

    # Telegram
    tg_token = cfg["telegram"]["token"]
    chat_log = cfg["telegram"]["chat_id_log"]
    chat_signal = cfg["telegram"]["chat_id_signal"]
    status_interval = timedelta(minutes=cfg["telegram"].get("status_interval_minutes", 60))
    send_hold = cfg["telegram"].get("send_hold_to_signal", False)

    # Gửi thông báo khởi động
    send_telegram(tg_token, chat_log, f"🚀 Bot khởi động: {symbol} ({timeframe_label})", logger)

    # Lên lịch phân tích lần đầu
    next_analysis_time = next_candle_close_time(tf_minutes)
    next_status_time = datetime.now(timezone.utc) + status_interval
    logger.info(f"Phân tích lần đầu lúc {next_analysis_time.isoformat()}")

    # Biến dừng
    stop_flag = {"stop": False}
    def handle_sigint(signum, frame):
        stop_flag["stop"] = True
    signal.signal(signal.SIGINT, handle_sigint)

    try:
        while not stop_flag["stop"]:
            now = datetime.now(timezone.utc)

            if now >= next_analysis_time:
                try:
                    # Lấy dữ liệu
                    df = fetch_candles(symbol, mt5_timeframe, indicator_cfg["n_candles"])
                    tick = mt5.symbol_info_tick(symbol)
                    if tick is None:
                        raise RuntimeError("Không lấy được giá tick")
                    current_price = tick.bid

                    # Xây dựng prompt
                    prompt_text, _ = build_prompt(
                        template_text, symbol, timeframe_label, df, current_price,
                        indicator_cfg, sr_cfg, risk_cfg
                    )

                    # Gọi API
                    signal = call_llm_api(cfg, prompt_text, logger)
                    state["n_analysis"] += 1

                    # Log và gửi Telegram log
                    log_msg = format_log_message(symbol, timeframe_label, signal)
                    send_telegram(tg_token, chat_log, log_msg, logger)
                    append_signal_history(cfg["paths"]["signal_history_file"], symbol, timeframe_label, signal)

                    # Gửi tín hiệu (BUY/SELL) hoặc HOLD nếu được cấu hình
                    action = signal.get("action", "HOLD").upper()
                    if action in ("BUY", "SELL") or (action == "HOLD" and send_hold):
                        send_telegram(tg_token, chat_signal,
                                      format_signal_message(symbol, timeframe_label, signal), logger)
                        if action in ("BUY", "SELL"):
                            state["n_signals"] += 1

                    state["last_signal"] = signal
                    state["last_signal_time"] = now
                    logger.info(f"Phân tích hoàn tất: action={action}, conf={signal.get('confidence')}")

                except Exception as e:
                    state["n_errors"] += 1
                    err_msg = f"❌ Lỗi phân tích: {e}"
                    logger.error(err_msg + "\n" + traceback.format_exc())
                    send_telegram(tg_token, chat_log, err_msg, logger)

                next_analysis_time = next_candle_close_time(tf_minutes)
                logger.info(f"Phân tích tiếp theo lúc {next_analysis_time.isoformat()}")

            if now >= next_status_time:
                send_telegram(tg_token, chat_log, format_status_message(state, cfg), logger)
                next_status_time = now + status_interval

            sleep_seconds = min(5, max(0.5, (next_analysis_time - now).total_seconds()))
            time.sleep(sleep_seconds)

    finally:
        mt5.shutdown()
        state["mt5_connected"] = False
        send_telegram(tg_token, chat_log, "🛑 Bot đã dừng.", logger)
        logger.info("Bot dừng an toàn.")

if __name__ == "__main__":
    run()