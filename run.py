"""
run.py — Bot Tín hiệu XAUUSD M5 (Entry/TP/SL + Alert Telegram)

Cách chạy:
    1. Đảm bảo MT5 desktop đã mở & đăng nhập sẵn.
    2. pip install -r requirements.txt
    3. Điền đủ config.yaml (đặc biệt bot_token, chat_id)
    4. Đặt 2 file model đã train vào thư mục models/ (xem notebook/train_walk_forward.ipynb)
    5. python run.py

Output:
    - Terminal: in log ở MỌI chu kỳ (mỗi khi có nến M5 mới đóng), kể cả khi tín hiệu bị loại.
    - Telegram: CHỈ nhận khi tín hiệu hợp lệ, hoặc đến chu kỳ Status Report, hoặc có cảnh báo bất thường.
"""

import os
import sys
import time
import json
import logging
import threading
from datetime import datetime, timedelta

import yaml
import requests
import numpy as np
import pandas as pd
import xgboost as xgb

try:
    import MetaTrader5 as mt5
except ImportError:
    mt5 = None  # Cho phép import file này để test logic ở máy không có MT5 (sẽ báo lỗi khi thực sự chạy)


# ============================================================
# LOGGING
# ============================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("run")


# ============================================================
# CONFIG LOADER
# ============================================================
def load_config(path: str = "config.yaml") -> dict:
    if not os.path.exists(path):
        raise FileNotFoundError(f"Không tìm thấy {path}. Copy/tạo file config.yaml trước khi chạy.")
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


# ============================================================
# TRẠNG THÁI RUNTIME CỦA BOT (dùng chung cho log terminal + status report)
# ============================================================
class BotState:
    def __init__(self, max_latency_seconds: float):
        self.lock = threading.Lock()
        self.start_time = datetime.now()
        self.signals_sent = 0
        self.filtered_by_confidence = 0
        self.filtered_by_spread = 0
        self.filtered_by_magnitude = 0
        self.last_latency_seconds = 0.0
        self.max_latency_seconds = max_latency_seconds
        self.mt5_connected = True

    def record_signal_sent(self):
        with self.lock:
            self.signals_sent += 1

    def record_signal_filtered(self, reason: str):
        with self.lock:
            if reason == "confidence":
                self.filtered_by_confidence += 1
            elif reason == "spread":
                self.filtered_by_spread += 1
            elif reason == "magnitude":
                self.filtered_by_magnitude += 1

    def update_latency(self, seconds: float):
        with self.lock:
            self.last_latency_seconds = seconds

    def set_mt5_connected(self, connected: bool):
        with self.lock:
            self.mt5_connected = connected


# ============================================================
# TELEGRAM NOTIFIER (dùng requests trực tiếp, không cần thư viện async)
# ============================================================
class TelegramNotifier:
    def __init__(self, bot_token: str, chat_id: str):
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.api_url = f"https://api.telegram.org/bot{bot_token}/sendMessage"

    def send_message(self, text: str):
        if not self.bot_token or "YOUR_TELEGRAM" in self.bot_token:
            logger.warning("⚠️  Chưa cấu hình Telegram bot_token trong config.yaml — bỏ qua gửi tin nhắn.")
            return
        try:
            resp = requests.post(self.api_url, data={"chat_id": self.chat_id, "text": text}, timeout=10)
            if resp.status_code != 200:
                logger.error(f"❌ Gửi Telegram thất bại: {resp.status_code} - {resp.text}")
        except Exception as e:
            logger.error(f"❌ Lỗi khi gửi Telegram: {e}")


# ============================================================
# MT5 CONNECTOR
# ============================================================
class MT5Connector:
    def __init__(self, symbol: str, cfg: dict):
        self.symbol = symbol
        self.cfg = cfg
        self.timeframe = mt5.TIMEFRAME_M5 if mt5 else None

    def connect(self) -> bool:
        if mt5 is None:
            logger.error("❌ Chưa cài thư viện MetaTrader5, hoặc đang chạy trên hệ điều hành không hỗ trợ (chỉ Windows).")
            return False

        if not mt5.initialize():
            logger.error(f"❌ mt5.initialize() thất bại: {mt5.last_error()}")
            return False

        mt5_cfg = self.cfg.get("mt5", {})
        login = mt5_cfg.get("login", 0)
        password = mt5_cfg.get("password", "")
        server = mt5_cfg.get("server", "")
        if login and password and server:
            if not mt5.login(login, password=password, server=server):
                logger.error(f"❌ Login MT5 thất bại: {mt5.last_error()}")
                return False
            logger.info(f"✅ Đã login MT5 vào tài khoản {login} @ {server}")
        else:
            logger.info("Dùng phiên MT5 đang mở sẵn trên máy (không login lại).")

        if not mt5.symbol_select(self.symbol, True):
            logger.error(f"❌ Không tìm thấy/chọn được symbol {self.symbol} trên MT5.")
            return False

        return True

    def disconnect(self):
        if mt5 is not None:
            mt5.shutdown()

    def load_bootstrap_history(self, months_back: int = 1) -> pd.DataFrame:
        """Nạp dữ liệu tháng trước + tháng hiện tại đến thời điểm hiện tại (mục 4.1 tài liệu đặc tả)."""
        now = datetime.now()
        start = (now.replace(day=1) - timedelta(days=1)).replace(day=1)  # đầu tháng trước
        for _ in range(months_back - 1):
            start = (start - timedelta(days=1)).replace(day=1)

        rates = mt5.copy_rates_range(self.symbol, self.timeframe, start, now)
        if rates is None or len(rates) == 0:
            raise RuntimeError(f"Không lấy được dữ liệu lịch sử cho {self.symbol}: {mt5.last_error()}")

        df = pd.DataFrame(rates)
        df["time"] = pd.to_datetime(df["time"], unit="s")
        df = df.rename(columns={"spread": "spread_raw"})
        df["spread"] = df["spread_raw"] * self._point()
        return df[["time", "open", "high", "low", "close", "spread"]]

    def _point(self) -> float:
        info = mt5.symbol_info(self.symbol)
        return info.point if info else 0.01

    def wait_for_next_candle_close(self, poll_seconds: int = 2) -> dict:
        """Block đến khi có nến M5 mới đóng, trả về dict OHLC + spread của nến vừa đóng."""
        last_seen_time = None
        rates = mt5.copy_rates_from_pos(self.symbol, self.timeframe, 1, 1)
        if rates is not None and len(rates) > 0:
            last_seen_time = rates[0]["time"]

        while True:
            time.sleep(poll_seconds)
            rates = mt5.copy_rates_from_pos(self.symbol, self.timeframe, 1, 1)
            if rates is None or len(rates) == 0:
                continue
            candle = rates[0]
            if last_seen_time is None or candle["time"] != last_seen_time:
                return {
                    "time": pd.to_datetime(candle["time"], unit="s"),
                    "open": float(candle["open"]),
                    "high": float(candle["high"]),
                    "low": float(candle["low"]),
                    "close": float(candle["close"]),
                    "spread": float(candle["spread"]) * self._point(),
                }

    def get_cost_estimate(self, default_spread_usd: float, default_slippage_usd: float) -> dict:
        info = mt5.symbol_info(self.symbol)
        spread_usd = (info.spread * info.point) if info else default_spread_usd
        return {
            "spread_usd": round(spread_usd, 2) if spread_usd > 0 else default_spread_usd,
            "slippage_usd": default_slippage_usd,
        }


# ============================================================
# FEATURE ENGINEERING (khớp với notebook/train_walk_forward.ipynb)
# ============================================================
def candle_to_vector(o, h, l, c, spread):
    body = (c - o) / o * 100
    upper = (h - max(o, c)) / o * 100
    lower = (min(o, c) - l) / o * 100
    rng = max(h - l, 1e-9)
    spread_norm = spread / rng
    return body, upper, lower, spread_norm


class FeatureEngineer:
    def __init__(self, sequence_length: int, atr_period: int, atr_average_window: int):
        self.sequence_length = sequence_length
        self.atr_period = atr_period
        self.atr_average_window = atr_average_window

    def prepare(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        body, upper, lower, spread_norm = [], [], [], []
        for _, row in df.iterrows():
            b, u, lo, s = candle_to_vector(row["open"], row["high"], row["low"], row["close"], row["spread"])
            body.append(b); upper.append(u); lower.append(lo); spread_norm.append(s)
        df["body_pct"] = body
        df["upper_pct"] = upper
        df["lower_pct"] = lower
        df["spread_norm"] = spread_norm

        tr = pd.concat([
            df["high"] - df["low"],
            (df["high"] - df["close"].shift()).abs(),
            (df["low"] - df["close"].shift()).abs()
        ], axis=1).max(axis=1)
        df["atr"] = tr.rolling(self.atr_period).mean()
        df["atr_avg"] = df["atr"].rolling(self.atr_average_window).mean()

        return df

    def append_candle(self, df: pd.DataFrame, new_candle: dict) -> pd.DataFrame:
        new_row = pd.DataFrame([new_candle])
        df = pd.concat([df[["time", "open", "high", "low", "close", "spread"]], new_row], ignore_index=True)
        df = self.prepare(df)
        return df

    def get_last_n_features(self, df: pd.DataFrame) -> np.ndarray:
        feature_cols = ["body_pct", "upper_pct", "lower_pct", "spread_norm"]
        window = df[feature_cols].values[-self.sequence_length:]
        return window.flatten().reshape(1, -1)

    def get_atr(self, df: pd.DataFrame) -> float:
        return float(df["atr"].iloc[-1])

    def get_atr_average(self, df: pd.DataFrame) -> float:
        val = df["atr_avg"].iloc[-1]
        return float(val) if not pd.isna(val) else float(df["atr"].iloc[-1])


# ============================================================
# MODEL ENGINE
# ============================================================
class ModelEngine:
    def __init__(self, clf_model_path: str, reg_model_path: str):
        if not os.path.exists(clf_model_path) or not os.path.exists(reg_model_path):
            raise FileNotFoundError(
                f"Không tìm thấy model tại {clf_model_path} / {reg_model_path}. "
                f"Hãy train và tải model về từ notebook/train_walk_forward.ipynb trước."
            )
        self.clf_model = xgb.XGBClassifier()
        self.clf_model.load_model(clf_model_path)
        self.reg_model = xgb.XGBRegressor()
        self.reg_model.load_model(reg_model_path)

    def predict(self, X: np.ndarray) -> dict:
        proba = self.clf_model.predict_proba(X)[0]      # [P(Giảm), P(Tăng)]
        direction = 1 if proba[1] >= proba[0] else -1
        confidence = float(max(proba))
        magnitude_pct = float(self.reg_model.predict(X)[0])
        return {"direction": direction, "confidence": confidence, "magnitude_pct": magnitude_pct}


# ============================================================
# ENTRY / TP / SL — XAUUSD, khung cố định 8-10 giá / 3-5 giá (mục 3.6 tài liệu đặc tả)
# ============================================================
def _lerp_clamped(value, in_min, in_max, out_min, out_max):
    ratio = (value - in_min) / (in_max - in_min) if in_max != in_min else 0
    ratio = max(0.0, min(1.0, ratio))
    return out_min + ratio * (out_max - out_min)


def calculate_entry_tp_sl_xauusd(entry_price, direction, confidence, atr_current, atr_average, config: dict):
    tp_distance = _lerp_clamped(
        confidence,
        config["confidence_floor"], config["confidence_ceiling"],
        config["tp_min_usd"], config["tp_max_usd"]
    )
    atr_ratio = atr_current / atr_average if atr_average > 0 else 1.0
    sl_distance = _lerp_clamped(
        atr_ratio,
        config["atr_ratio_floor"], config["atr_ratio_ceiling"],
        config["sl_min_usd"], config["sl_max_usd"]
    )

    if direction == 1:
        tp_price = entry_price + tp_distance
        sl_price = entry_price - sl_distance
    else:
        tp_price = entry_price - tp_distance
        sl_price = entry_price + sl_distance

    risk_reward = tp_distance / sl_distance if sl_distance > 0 else 0

    return {
        "entry": round(entry_price, 2),
        "tp": round(tp_price, 2),
        "sl": round(sl_price, 2),
        "tp_distance_usd": round(tp_distance, 2),
        "sl_distance_usd": round(sl_distance, 2),
        "risk_reward": round(risk_reward, 2),
        "valid": confidence >= config["confidence_floor"],
    }


# ============================================================
# BỘ LỌC TÍN HIỆU (3 lớp — mục 3.6 tài liệu đặc tả)
# ============================================================
def evaluate_signal_filters(model_output: dict, trade_setup: dict, cost_estimate: dict, cfg: dict):
    sf = cfg["signal_filter"]

    if model_output["confidence"] < sf["min_confidence_threshold"] or not trade_setup["valid"]:
        return False, "confidence"

    total_cost_usd = cost_estimate["spread_usd"] + cost_estimate["slippage_usd"]
    if total_cost_usd <= 0:
        return False, "spread"
    safety_multiple = trade_setup["tp_distance_usd"] / total_cost_usd
    if safety_multiple < sf["min_magnitude_multiple_of_cost"]:
        return False, "magnitude"

    # Spread bất thường: nếu spread hiện tại vượt quá 3x spread mặc định coi là bất thường
    if cost_estimate["spread_usd"] > cfg["cost_estimate"]["default_spread_usd"] * 3:
        return False, "spread"

    return True, None


# ============================================================
# FORMAT LOG TERMINAL + TIN NHẮN TELEGRAM (mục 5.2, 7.3 tài liệu đặc tả)
# ============================================================
def format_terminal_log(symbol, candle, model_output, trade_setup, passed, reason) -> str:
    direction_text = "TĂNG" if model_output["direction"] == 1 else "GIẢM"
    lines = [
        f"Nến mới đóng: {symbol} M5 | O={candle['open']:.2f} H={candle['high']:.2f} "
        f"L={candle['low']:.2f} C={candle['close']:.2f}",
        f"Model output: direction={direction_text} confidence={model_output['confidence']:.2f} "
        f"magnitude={model_output['magnitude_pct']:.3f}%",
        f"Trade setup: entry={trade_setup['entry']} tp={trade_setup['tp']} sl={trade_setup['sl']} "
        f"(TP +{trade_setup['tp_distance_usd']} giá, SL -{trade_setup['sl_distance_usd']} giá) "
        f"R:R=1:{trade_setup['risk_reward']}",
    ]
    if passed:
        lines.append("✅ Tín hiệu HỢP LỆ — đã gửi Telegram")
    else:
        lines.append(f"⚠️ Tín hiệu BỊ LOẠI — lý do: {reason}")
    lines.append("-" * 60)
    return "\n".join(lines)


def build_signal_message(symbol, model_output, trade_setup, cost_estimate) -> str:
    direction_text = "TĂNG 📈" if model_output["direction"] == 1 else "GIẢM 📉"
    total_cost = cost_estimate["spread_usd"] + cost_estimate["slippage_usd"]
    safety_multiple = trade_setup["tp_distance_usd"] / total_cost if total_cost > 0 else 0
    return (
        f"📊 [TÍN HIỆU M5 - {symbol}]\n"
        f"Hướng dự đoán: {direction_text} (độ tin cậy {model_output['confidence']*100:.0f}%)\n"
        f"Biên độ dự đoán: ~{model_output['magnitude_pct']:.3f}%\n"
        f"─────────────\n"
        f"🎯 Entry: {trade_setup['entry']}\n"
        f"✅ TP: {trade_setup['tp']}  (+{trade_setup['tp_distance_usd']} giá)\n"
        f"🛑 SL: {trade_setup['sl']}  (-{trade_setup['sl_distance_usd']} giá)\n"
        f"⚖️ Risk:Reward = 1:{trade_setup['risk_reward']}\n"
        f"─────────────\n"
        f"Chi phí ước tính (spread+slippage): ~{total_cost:.2f} giá\n"
        f"Biên an toàn: {safety_multiple:.1f}x chi phí {'✅' if safety_multiple >= 2.0 else '⚠️'}\n"
        f"Thời điểm: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    )


# ============================================================
# STATUS REPORTER — chạy nền, gửi báo cáo định kỳ (mục 5.3 tài liệu đặc tả)
# ============================================================
class StatusReporter(threading.Thread):
    def __init__(self, state: BotState, telegram: TelegramNotifier, interval_minutes: int):
        super().__init__(daemon=True)
        self.state = state
        self.telegram = telegram
        self.interval_seconds = interval_minutes * 60
        self._stop_event = threading.Event()

    def run(self):
        while not self._stop_event.wait(self.interval_seconds):
            self.telegram.send_message(self._build_report())

    def stop(self):
        self._stop_event.set()

    def _build_report(self) -> str:
        s = self.state
        uptime = datetime.now() - s.start_time
        with s.lock:
            return (
                f"🤖 [BÁO CÁO TRẠNG THÁI BOT]\n"
                f"Uptime: {str(uptime).split('.')[0]}\n"
                f"Tín hiệu đã gửi: {s.signals_sent}\n"
                f"  - Bị loại (confidence thấp): {s.filtered_by_confidence}\n"
                f"  - Bị loại (spread bất thường): {s.filtered_by_spread}\n"
                f"  - Bị loại (biên độ < chi phí): {s.filtered_by_magnitude}\n"
                f"Latency hiện tại: {s.last_latency_seconds:.2f}s "
                f"{'⚠️ VƯỢT NGƯỠNG' if s.last_latency_seconds > s.max_latency_seconds else '✅'}\n"
                f"Kết nối MT5: {'✅ OK' if s.mt5_connected else '❌ MẤT KẾT NỐI'}"
            )


# ============================================================
# MAIN
# ============================================================
def main():
    cfg = load_config("config.yaml")
    symbol = cfg["symbol"]

    logger.info(f"Đang kết nối MT5 cho {symbol} (yêu cầu MT5 desktop đã mở & đăng nhập sẵn)...")
    connector = MT5Connector(symbol, cfg)
    if not connector.connect():
        logger.error("❌ Không kết nối được MT5. Kiểm tra MT5 đã mở & login chưa, hoặc thông tin trong config.yaml.")
        sys.exit(1)

    telegram = TelegramNotifier(cfg["telegram"]["bot_token"], cfg["telegram"]["chat_id"])
    state = BotState(max_latency_seconds=cfg["performance"]["max_latency_seconds"])

    logger.info("Đang load model từ thư mục models/ ...")
    model = ModelEngine(cfg["model"]["clf_model_path"], cfg["model"]["reg_model_path"])

    fe = FeatureEngineer(
        sequence_length=cfg["bootstrap"]["sequence_length"],
        atr_period=cfg["trade_setup"]["atr_period"],
        atr_average_window=cfg["trade_setup"]["atr_average_window"],
    )

    logger.info("Bootstrap dữ liệu lịch sử (tháng trước + tháng hiện tại)...")
    history_df = connector.load_bootstrap_history(months_back=cfg["bootstrap"]["months_back"])
    history_df = fe.prepare(history_df)
    logger.info(f"✅ Đã nạp {len(history_df)} nến vào bộ nhớ đệm.")

    status_reporter = StatusReporter(state, telegram, cfg["monitor"]["status_report_interval_minutes"])
    status_reporter.start()

    telegram.send_message(f"🤖 Bot {symbol} đã khởi động thành công và bắt đầu theo dõi thị trường.")
    logger.info("=== BẮT ĐẦU VÒNG LẶP REAL-TIME (Ctrl+C để dừng) ===")

    try:
        while True:
            t0 = time.time()
            new_candle = connector.wait_for_next_candle_close()
            history_df = fe.append_candle(history_df, new_candle)

            X = fe.get_last_n_features(history_df)
            model_output = model.predict(X)

            trade_setup = calculate_entry_tp_sl_xauusd(
                entry_price=new_candle["close"],
                direction=model_output["direction"],
                confidence=model_output["confidence"],
                atr_current=fe.get_atr(history_df),
                atr_average=fe.get_atr_average(history_df),
                config=cfg["trade_setup"],
            )

            cost_estimate = connector.get_cost_estimate(
                default_spread_usd=cfg["cost_estimate"]["default_spread_usd"],
                default_slippage_usd=cfg["cost_estimate"]["default_slippage_usd"],
            )

            passed, reason = evaluate_signal_filters(model_output, trade_setup, cost_estimate, cfg)

            # --- LUÔN in ra terminal ---
            print(format_terminal_log(symbol, new_candle, model_output, trade_setup, passed, reason))

            # --- CHỈ gửi Telegram khi tín hiệu hợp lệ ---
            if passed:
                telegram.send_message(build_signal_message(symbol, model_output, trade_setup, cost_estimate))
                state.record_signal_sent()
            else:
                state.record_signal_filtered(reason)

            state.update_latency(time.time() - t0)

    except KeyboardInterrupt:
        logger.info("Đã dừng bot theo yêu cầu người dùng (Ctrl+C).")
    except Exception as e:
        logger.error(f"❌ Lỗi không mong muốn: {e}", exc_info=True)
        state.set_mt5_connected(False)
        telegram.send_message(f"❌ [CẢNH BÁO] Bot gặp lỗi và đã dừng: {e}")
    finally:
        status_reporter.stop()
        connector.disconnect()
        telegram.send_message(f"🔴 Bot {symbol} đã dừng hoạt động.")


if __name__ == "__main__":
    main()
