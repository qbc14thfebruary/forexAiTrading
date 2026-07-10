# TÀI LIỆU ĐẶC TẢ YÊU CẦU & PHƯƠNG ÁN KỸ THUẬT (PRD & TECHNICAL PROPOSAL) — v3.0
**Dự án:** Nghiên cứu & Dự đoán Hành động giá ngắn hạn (M5) bằng Mô hình hóa Định lượng — **XAUUSD (Vàng/Gold)**
**Vị trí:** Business Analyst / Product Owner
**Đối tượng trình bày:** Đội ngũ Kỹ sư Phát triển (Python / Data Engineering Team)
**Symbol giao dịch:** `XAUUSD` (toàn bộ tài liệu, code mẫu, cấu hình đều áp dụng riêng cho cặp này — không còn tổng quát cho mọi cặp forex)
**Quy ước đơn vị "giá":** Trong tài liệu này, **1 "giá" = 1.0 USD** biến động trên giá XAUUSD (VD: giá từ 2350.00 lên 2358.00 = tăng 8 giá). Đây là quy ước phổ biến trong cộng đồng trade vàng, cần xác nhận lại với broker/kỹ sư trước khi code để tránh nhầm lẫn với "point" (0.01) hoặc "pip".
**Tham số Entry/TP/SL cố định theo yêu cầu:**
- **Take Profit (TP):** 8 – 10 giá (tức 8.0 – 10.0 USD tính từ Entry)
- **Stop Loss (SL):** 3 – 5 giá (tức 3.0 – 5.0 USD tính từ Entry)
- → Risk:Reward dao động trong khoảng **1:1.6 đến 1:3.33** tùy tổ hợp TP/SL thực tế được chọn, đều thỏa `min_risk_reward` đề xuất trước đây.

**Thay đổi so với v2:** Toàn bộ tài liệu được cập nhật đồng bộ cho XAUUSD thay vì forex tổng quát (EURUSD làm ví dụ trước đây); logic tính Entry/TP/SL (mục 3.6) được thiết kế lại theo khoảng cố định 8-10 giá / 3-5 giá thay vì suy ra hoàn toàn từ ATR/magnitude; các đơn vị "pip" trong backtest, cấu hình, và tin nhắn Telegram được đổi thành "giá" (USD) cho đúng bản chất symbol vàng.


---

## 0. TÓM TẮT THAY ĐỔI (CHANGELOG)

| # | Vấn đề ở bản v1 | Bổ sung ở bản v2 |
|---|---|---|
| 1 | Chỉ có nhãn Tăng/Giảm nhị phân, bỏ quên "biên độ" dù mục tiêu ban đầu có nhắc | Thêm **Regression Head** dự đoán biên độ nến 11 (mục 3.3) |
| 2 | Nhãn nhị phân tại vùng gần 0 gây nhiễu | Thêm **Dead-zone / 3-class labeling** (mục 3.3) |
| 3 | Train/Test trong cùng 1 tháng, không đủ tin cậy | Thêm **Walk-Forward Validation** nhiều tháng (mục 3.4) |
| 4 | Chỉ dùng OHLC+Spread M5 thuần, SNR thấp | Thêm **Feature đa khung thời gian & ngữ cảnh phiên** (mục 2.3) |
| 5 | Backtest chưa trừ chi phí giao dịch thực tế | Thêm **Cost-aware Backtest Engine** (mục 3.5) |
| 6 | KNN/DTW trên 40 chiều bị curse of dimensionality | Thêm **giảm chiều (PCA) / ANN Index (FAISS)** cho Hướng A (mục 3.2) |
| 7 | Chưa phân biệt forex vs BTC | Thêm **Phụ lục B: lưu ý riêng cho BTC/Crypto** |
| 8 | Chưa có cách quy đổi tín hiệu mô hình thành lệnh giao dịch cụ thể | Thêm **cách tính Entry/TP/SL + kiểm tra Risk:Reward** (mục 3.6) |
| 9 | Heartbeat chỉ báo "còn sống", chưa có báo cáo vận hành định kỳ | Thêm **Status Report tự động theo chu kỳ cấu hình được** (mục 5.3) |
| 10 | Chưa xác định rõ mô hình vận hành/triển khai thực tế | Thêm **mục 7: yêu cầu local, cấu trúc `run.py`, output song song Terminal + Telegram** |
| 11 | Tài liệu tổng quát cho forex, chưa gắn cụ thể symbol nào | **Chốt symbol = XAUUSD**, TP/SL cố định 8-10 giá / 3-5 giá, toàn bộ code/config/tin nhắn cập nhật theo (mục 3.6, 5.1, 5.2) |

---

## 1. TỔNG QUAN BÀI TOÁN & MỤC TIÊU (giữ nguyên từ v1)

### 1.1. Bài toán đặt ra
Trong giao dịch tần suất ngắn hạn (khung M5) trên cặp **XAUUSD (Vàng/Gold)**, các chuỗi nến liên tiếp mang cấu trúc đặc biệt chứa đựng xung lực thị trường (Momentum) và hành vi phe phái rất mạnh — đặc biệt rõ nét ở vàng do biên độ dao động lớn và nhạy với tin tức vĩ mô (lãi suất, DXY, địa chính trị). Việc nhận diện bằng mắt thường mang tính cảm tính và không thể lượng hóa.

### 1.2. Mục tiêu cốt lõi
* **Xây dựng hệ thống định lượng (Quantitative Model)** quét dữ liệu lịch sử nến M5 (quy mô mẫu: 1 tháng ~ 6.300+ cây nến).
* **Nhận diện và khớp mẫu (Pattern Matching):** chuỗi **10 cây nến liên tiếp**.
* **Dự đoán mục tiêu kép cho cây nến thứ 11:**
  1. **Hướng đi** (Tăng / Giảm / Đi ngang) — bài toán phân loại.
  2. **Biên độ biến động** (magnitude, đơn vị %) — bài toán hồi quy.

> ⚠️ **Lưu ý quan trọng:** Bản v1 chỉ triển khai mục tiêu (1) và bỏ sót mục tiêu (2). Bản v2 khôi phục đầy đủ theo đúng mục tiêu ban đầu bằng kiến trúc multi-task ở mục 3.3.

---

## 2. PHẠM VI & ĐẶC TẢ DỮ LIỆU ĐẦU VÀO

### 2.1. Dữ liệu gốc
Symbol: **XAUUSD**. Mỗi cây nến $t$: `Open, High, Low, Close, Spread`.

> **Lưu ý:** Spread của XAUUSD thường lớn hơn và biến động mạnh hơn nhiều so với các cặp forex chính (VD: EURUSD spread thường 0.1-0.3 giá tương đương, trong khi XAUUSD có thể 0.2-0.5 giá lúc thanh khoản thấp và giãn rất mạnh quanh giờ tin NFP/CPI/Fed) — cần backtest riêng ngưỡng Spread Anomaly Filter (mục 3, giai đoạn 3) cho XAUUSD, không dùng lại ngưỡng đã tune cho forex.

### 2.2. Feature Engineering cấp nến (giữ nguyên từ v1)
4 chiều/nến: `Δ%Body`, `Δ%Upper`, `Δ%Lower`, `Spread_norm` → chuỗi 10 nến = **40 features**.

```python
def candle_to_vector(o, h, l, c, spread):
    body   = (c - o) / o * 100
    upper  = (h - max(o, c)) / o * 100
    lower  = (min(o, c) - l) / o * 100
    rng    = max(h - l, 1e-9)          # tránh chia 0
    spread_norm = spread / rng
    return [body, upper, lower, spread_norm]
```

### 2.3. [MỚI] Feature bổ sung để tăng SNR

Lý do bổ sung: dự đoán chỉ từ 10 nến M5 OHLC thuần có tỷ lệ tín hiệu/nhiễu (signal-to-noise ratio) rất thấp — gần với random walk. Cần thêm ngữ cảnh để mô hình có cơ hội học được pattern thật thay vì nhiễu.

**Nhóm A — Ngữ cảnh đa khung thời gian (Multi-timeframe context):**
| Feature | Mô tả | Cách tính |
|---|---|---|
| `atr_h1_norm` | ATR khung H1 tại thời điểm nến 10, chuẩn hóa theo giá | `ATR(H1, 14) / Close_t * 100` |
| `trend_h1` | Xu hướng khung H1 (EMA20 vs EMA50) | -1/0/1 |
| `dist_to_h1_high_low` | Khoảng cách giá hiện tại đến đỉnh/đáy H1 gần nhất | % |

**Nhóm B — Ngữ cảnh phiên giao dịch:**
| Feature | Mô tả |
|---|---|
| `session` | Á/Âu/Mỹ (one-hot hoặc cyclical encoding theo giờ) |
| `hour_sin`, `hour_cos` | Encode giờ trong ngày dạng cyclical để mô hình học pattern theo giờ |
| `is_news_window` | Cờ đánh dấu ±15 phút quanh tin tức High Impact (nếu có nguồn lịch kinh tế) |

**Nhóm C — Volume/Tick (nếu broker cung cấp qua MT5):**
| Feature | Mô tả |
|---|---|
| `tick_volume_norm` | Tick volume của nến, chuẩn hóa theo trung bình 20 nến gần nhất |

> **Khuyến nghị triển khai:** Bắt đầu MVP chỉ với 40 features gốc (v1) để có baseline. Sau đó thêm dần nhóm A → B → C, đo lường mức tăng AUC/accuracy từng bước (ablation study) trước khi giữ lại nhóm feature nào thực sự có ích — tránh nhồi feature không có giá trị gây overfitting.

---

## 3. GIẢI PHÁP KỸ THUẬT CHI TIẾT

### 3.1. Kiến trúc pipeline tổng thể (không đổi so với v1)
3 giai đoạn: Feature Engineering → Modeling → Backtesting/Risk Filter.

### 3.2. [CẬP NHẬT] Hướng tiếp cận A: Clustering & KNN

**Vấn đề với bản v1:** không gian 40 chiều (hoặc cao hơn nếu thêm mục 2.3) khiến "similarity > 95%" gần như không tồn tại trong tập dữ liệu chỉ ~6.300 mẫu/tháng — đây là hiện tượng **curse of dimensionality**: trong không gian nhiều chiều, khoảng cách giữa các điểm dữ liệu có xu hướng hội tụ về giá trị tương tự nhau, làm mất khả năng phân biệt "gần" và "xa" thực sự.

**Giải pháp bổ sung:**
1. **Giảm chiều trước khi tính khoảng cách:**
   ```python
   from sklearn.decomposition import PCA
   pca = PCA(n_components=8)  # giữ ~90% variance, cần thử nghiệm
   X_reduced = pca.fit_transform(X_40dim)
   ```
2. **Dùng Approximate Nearest Neighbor (ANN) thay vì brute-force Euclidean** để đảm bảo tốc độ khi historical pool tăng dần theo thời gian (mục 4):
   ```python
   import faiss
   index = faiss.IndexFlatL2(pca.n_components_)
   index.add(X_reduced.astype('float32'))
   distances, indices = index.search(query_vector, k=K)
   ```
3. **Với DTW:** chỉ nên áp dụng trên chuỗi thô (không giảm chiều), nhưng giới hạn kích thước cửa sổ tìm kiếm (Sakoe-Chiba band) để giảm độ phức tạp tính toán từ $O(n^2)$ xuống mức chấp nhận được cho real-time.
4. **Khuyến nghị:** Hướng A phù hợp làm công cụ **giải thích (explainability)** — hiển thị "10 case lịch sử giống nhất" cho người dùng xem — hơn là làm mô hình dự đoán chính (production signal). Hướng B (ML Classification) nên là **primary model**.

### 3.3. [CẬP NHẬT] Hướng tiếp cận B: Machine Learning — Multi-task (Classification + Regression)

**Vấn đề với bản v1:** chỉ có nhãn nhị phân Tăng/Giảm, bỏ sót yêu cầu biên độ, và nhãn tại vùng `Close ≈ Open` (chênh lệch cực nhỏ) tạo nhiễu nhãn — mô hình bị ép học phân loại các case gần như "tung đồng xu".

**Thiết kế nhãn mới (Target Labeling v2):**

```python
def label_candle_11(open_11, close_11, atr_threshold):
    """
    atr_threshold: ngưỡng biến động tối thiểu để coi là 'có xu hướng',
    thường lấy = 0.1 * ATR(14) tại thời điểm đó, cần backtest để tune.
    """
    pct_change = (close_11 - open_11) / open_11 * 100

    # --- Nhãn phân loại (3 lớp, có dead-zone) ---
    if pct_change > atr_threshold:
        direction_label = 1        # Tăng rõ ràng
    elif pct_change < -atr_threshold:
        direction_label = -1       # Giảm rõ ràng
    else:
        direction_label = 0        # Đi ngang / nhiễu -> loại khỏi tập train hướng đi
                                    # (hoặc train riêng như 1 lớp "No Trade")

    # --- Nhãn hồi quy (biên độ) ---
    magnitude_label = abs(pct_change)   # dùng cho regression head

    return direction_label, magnitude_label
```

**Kiến trúc mô hình đề xuất — Multi-task với XGBoost (2 model riêng biệt, đơn giản & dễ maintain hơn 1 model đa đầu ra):**

```python
import xgboost as xgb

# Model 1: Phân loại hướng đi (loại bỏ nhãn 0 - dead zone khỏi tập train)
clf_model = xgb.XGBClassifier(
    objective='multi:softprob',
    num_class=2,          # chỉ Tăng (1) / Giảm (-1) sau khi lọc dead-zone
    max_depth=6,
    n_estimators=300,
    eval_metric='mlogloss'
)

# Model 2: Hồi quy biên độ (train trên toàn bộ dữ liệu, không lọc dead-zone)
reg_model = xgb.XGBRegressor(
    objective='reg:squarederror',
    max_depth=6,
    n_estimators=300,
    eval_metric='rmse'
)
```

**Quy tắc kết hợp output khi sinh tín hiệu thực tế:**
- Chỉ phát tín hiệu khi: `clf_model` cho xác suất > ngưỡng tin cậy (VD 65%) **VÀ** `reg_model` dự đoán biên độ đủ lớn để bù chi phí giao dịch (spread + slippage, xem mục 3.5).
- Nếu `direction_label` rơi vào dead-zone dự đoán → không phát tín hiệu (No Trade), tương tự bộ lọc Spread Anomaly ở v1.

### 3.4. [MỚI] Chiến lược Validation: Walk-Forward thay vì Train/Test 1 tháng

**Vấn đề với bản v1:** Train 3 tuần / Test 1 tuần trong **cùng một tháng** không đủ để kiểm chứng mô hình có hoạt động ổn định qua các regime thị trường khác nhau (trend mạnh, sideway, volatility cao/thấp). Rủi ro: mô hình "học vẹt" đặc thù của 1 tháng cụ thể (overfitting theo thời gian).

**Thiết kế Walk-Forward Validation:**

```
Tháng 1 (Train) → Tháng 2 (Test) 
Tháng 1-2 (Train) → Tháng 3 (Test)
Tháng 1-3 (Train) → Tháng 4 (Test)
...
```

```python
def walk_forward_split(df, min_train_months=1):
    months = df['month'].unique()
    for i in range(min_train_months, len(months)):
        train_months = months[:i]
        test_month = months[i]
        train_df = df[df['month'].isin(train_months)]
        test_df  = df[df['month'] == test_month]
        yield train_df, test_df
```

- Yêu cầu tối thiểu **6 tháng dữ liệu lịch sử** để có ít nhất 5 fold walk-forward, đủ để đánh giá tính ổn định (stability) của accuracy/AUC qua thời gian — nếu performance dao động mạnh giữa các fold, mô hình chưa đủ tin cậy để live.
- Ghi lại metric theo từng fold (không chỉ lấy trung bình) để phát hiện tháng nào mô hình thất bại và tìm nguyên nhân (VD: tháng có tin tức lớn, thay đổi regime).

### 3.5. [MỚI] Backtest Engine có tính chi phí giao dịch thực tế

**Vấn đề với bản v1:** Bộ lọc Spread Anomaly chỉ loại bỏ tín hiệu khi spread bất thường, nhưng chưa trừ chi phí spread/slippage trung bình vào PnL khi backtest — dẫn đến kết quả "thắng trên giấy" nhưng có thể lỗ thực tế, đặc biệt với chiến lược tần suất cao ở M5.

```python
def backtest_pnl(signals_df, avg_spread_usd, slippage_usd=0.3):
    """
    signals_df: cột ['predicted_direction', 'actual_close', 'entry_price']
    Đơn vị: USD (1 "giá" = 1.0 USD trên XAUUSD), không dùng pip_value như forex.
    """
    total_cost_usd = avg_spread_usd + slippage_usd
    pnl = []
    for _, row in signals_df.iterrows():
        raw_move_usd = row['actual_close'] - row['entry_price']
        net_move_usd = raw_move_usd - total_cost_usd if row['predicted_direction'] == 1 \
                   else -raw_move_usd - total_cost_usd
        pnl.append(net_move_usd)
    return pnl
```

**Yêu cầu bắt buộc trước khi coi 1 phiên bản mô hình là "khả thi":**
- Win rate và Expectancy (kỳ vọng lãi/lỗ trung bình mỗi trade) phải được tính **sau khi trừ chi phí**, không phải trước.
- Nên có báo cáo tách biệt: PnL gộp (gross) vs PnL ròng (net) để đội ngũ vận hành thấy rõ chi phí đang ăn mòn bao nhiêu %.
- Với chiến lược M5 tần suất cao, khuyến nghị đặt ngưỡng biên độ dự đoán tối thiểu (từ `reg_model` ở mục 3.3) phải **> 2x chi phí giao dịch** mới phát tín hiệu, để có biên an toàn.

### 3.6. [CẬP NHẬT v3] Tính toán Entry / Take Profit / Stop Loss cho XAUUSD (TP 8-10 giá, SL 3-5 giá)

**Vấn đề:** Mục 3.3 cho ra Hướng (direction) + Biên độ dự đoán (magnitude %). Theo yêu cầu thực tế, thay vì để TP/SL hoàn toàn tự do theo ATR/magnitude như thiết kế trước, hệ thống cần **giới hạn TP trong khoảng 8-10 giá và SL trong khoảng 3-5 giá** (đơn vị USD trên XAUUSD) — đây là khung quản trị rủi ro cố định do người dùng quyết định, mô hình chỉ có vai trò **chọn vị trí cụ thể trong khung đó** dựa trên độ tự tin và biên độ dự đoán, không được vượt ra ngoài khung.

**Nguyên tắc thiết kế:**
- **Entry** lấy tại giá đóng cửa của nến thứ 10 (thời điểm phát tín hiệu).
- **TP** = nội suy tuyến tính trong khoảng `[8, 10]` giá dựa trên độ tự tin (`confidence`) của model — tự tin càng cao, TP càng gần mức 10; tự tin thấp hơn (nhưng vẫn đủ ngưỡng phát tín hiệu) thì TP thận trọng hơn, gần mức 8.
- **SL** = nội suy tuyến tính trong khoảng `[3, 5]` giá dựa trên **volatility hiện tại (ATR)** so với volatility trung bình lịch sử — thị trường biến động mạnh hơn bình thường thì SL nới về phía 5 để tránh bị quét do nhiễu ngắn hạn; biến động thấp thì SL có thể siết về phía 3.
- Kết quả R:R vì vậy luôn nằm trong khoảng **1:1.6 (TP 8 / SL 5)** đến **1:3.33 (TP 10 / SL 3)** — không cần kiểm tra `min_risk_reward` riêng vì bản thân khung 8-10/3-5 đã đảm bảo R:R dương an toàn ở mọi tổ hợp.

```python
def calculate_entry_tp_sl_xauusd(
    entry_price: float,
    direction: int,                 # 1 = Long, -1 = Short
    confidence: float,              # xác suất từ clf_model, 0.0 - 1.0
    atr_current: float,             # ATR(14) hiện tại, đơn vị USD
    atr_average: float,             # ATR(14) trung bình lịch sử (VD 20 ngày), đơn vị USD
    config: dict
):
    """
    config mẫu (config.yaml -> trade_setup):
    {
        "tp_min_usd": 8.0,
        "tp_max_usd": 10.0,
        "sl_min_usd": 3.0,
        "sl_max_usd": 5.0,
        "confidence_floor": 0.65,   # confidence tối thiểu để còn được coi là tín hiệu (map về TP=tp_min)
        "confidence_ceiling": 0.90, # confidence từ mức này trở lên -> TP=tp_max
        "atr_ratio_floor": 0.8,     # atr_current/atr_average <= mức này -> SL=sl_min
        "atr_ratio_ceiling": 1.5,   # atr_current/atr_average >= mức này -> SL=sl_max
    }
    """
    def _lerp_clamped(value, in_min, in_max, out_min, out_max):
        ratio = (value - in_min) / (in_max - in_min) if in_max != in_min else 0
        ratio = max(0.0, min(1.0, ratio))     # clamp về [0, 1]
        return out_min + ratio * (out_max - out_min)

    # --- TP: nội suy theo confidence, luôn nằm trong [tp_min_usd, tp_max_usd] ---
    tp_distance = _lerp_clamped(
        confidence,
        config["confidence_floor"], config["confidence_ceiling"],
        config["tp_min_usd"], config["tp_max_usd"]
    )

    # --- SL: nội suy theo tỷ lệ biến động hiện tại/trung bình, luôn nằm trong [sl_min_usd, sl_max_usd] ---
    atr_ratio = atr_current / atr_average if atr_average > 0 else 1.0
    sl_distance = _lerp_clamped(
        atr_ratio,
        config["atr_ratio_floor"], config["atr_ratio_ceiling"],
        config["sl_min_usd"], config["sl_max_usd"]
    )

    if direction == 1:   # Long
        tp_price = entry_price + tp_distance
        sl_price = entry_price - sl_distance
    else:                 # Short
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
        "valid": confidence >= config["confidence_floor"]   # điều kiện tối thiểu để phát tín hiệu
    }
```

**Bổ sung config (nối vào `config.yaml` mục 5.1):**

```yaml
trade_setup:
  tp_min_usd: 8.0                # TP tối thiểu, theo yêu cầu: 8 giá
  tp_max_usd: 10.0                # TP tối đa, theo yêu cầu: 10 giá
  sl_min_usd: 3.0                 # SL tối thiểu, theo yêu cầu: 3 giá
  sl_max_usd: 5.0                 # SL tối đa, theo yêu cầu: 5 giá
  confidence_floor: 0.65          # confidence dưới mức này -> không phát tín hiệu
  confidence_ceiling: 0.90        # confidence từ mức này trở lên -> TP lấy giá trị tối đa (10 giá)
  atr_ratio_floor: 0.8            # biến động thấp hơn mức này -> SL lấy giá trị tối thiểu (3 giá)
  atr_ratio_ceiling: 1.5          # biến động cao hơn mức này -> SL lấy giá trị tối đa (5 giá)
  atr_period: 14
  atr_timeframe: "M5"
```

**Lưu ý quan trọng khi kỹ sư triển khai:**
1. **Khung 8-10 / 3-5 là ràng buộc cứng (hard constraint)** — bất kể model dự đoán biên độ (`magnitude_pct`) lớn thế nào, TP không bao giờ vượt quá 10 giá; SL không bao giờ vượt quá 5 giá. Đây là quyết định quản trị rủi ro độc lập với độ tin cậy của mô hình, không nên để kỹ sư "linh hoạt" nới khung này khi thấy model tự tin cao — nếu cần thay đổi khung, phải thông qua cấu hình `tp_min_usd/tp_max_usd/sl_min_usd/sl_max_usd`, không sửa cứng trong code.
2. **`atr_average` nên tính rolling trên khung thời gian đủ dài** (VD trung bình ATR(14) của 20-30 ngày gần nhất) để phản ánh đúng "mức biến động bình thường" của XAUUSD, tránh lấy trung bình quá ngắn hạn khiến tỷ lệ `atr_ratio` bị nhiễu.
3. **Kiểm tra `valid` (confidence đạt ngưỡng) TRƯỚC bộ lọc Spread Anomaly** (mục 3, giai đoạn 3) và **TRƯỚC ngưỡng magnitude vs chi phí giao dịch** (mục 3.5) — tín hiệu chỉ thực sự được gửi đi khi vượt qua **cả 3 lớp lọc**: confidence đạt ngưỡng → biên độ dự đoán đủ lớn hơn chi phí giao dịch → spread bình thường.
4. Nên log lại đầy đủ `entry/tp/sl/tp_distance_usd/sl_distance_usd/risk_reward` của mọi tín hiệu (kể cả tín hiệu bị loại) vào database để sau này phân tích: TP/SL nội suy theo confidence/ATR có thực sự tối ưu hơn so với việc cố định cứng TP=9/SL=4 hay không.

---

## 4. QUY TRÌNH KHỞI TẠO & CẬP NHẬT DỮ LIỆU ĐỘNG (giữ nguyên từ v1, không có thay đổi lớn)

### 4.1. Bootstrap Phase
1. Tải 100% dữ liệu M5 (OHLC + Spread) của tháng dương lịch liền kề trước đó.
2. Tải tiếp dữ liệu M5 từ đầu tháng hiện tại đến thời điểm Bot Start.

### 4.2. Real-time Rolling Update
1. Bắt sự kiện đóng nến (Candle Close Event) qua Webhook/WebSocket.
2. Chuyển nến vừa đóng thành Vector 4 (hoặc nhiều hơn nếu áp dụng mục 2.3) chiều, Append vào kho dữ liệu nền.
3. Tự động dùng dữ liệu mới cho vòng dự đoán tiếp theo.

> **Bổ sung kỹ thuật nhỏ:** Nên giới hạn kích thước tối đa của historical pool trong RAM (VD: giữ tối đa 6 tháng gần nhất, đẩy dữ liệu cũ hơn xuống lưu trữ lạnh/database) để tránh memory leak khi Bot chạy liên tục nhiều tháng.

---

## 5. THIẾT KẾ HỆ THỐNG CẢNH BÁO & GIÁM SÁT QUA TELEGRAM (giữ nguyên từ v1)

### 5.1. File cấu hình

```yaml
symbol: "XAUUSD"

telegram:
  bot_token: "YOUR_TELEGRAM_BOT_TOKEN"
  chat_id: "YOUR_TELEGRAM_CHAT_ID"

monitor:
  heartbeat_interval_minutes: 5

performance:
  max_latency_seconds: 5

# [MỚI] bổ sung ngưỡng liên quan đến model v2
signal_filter:
  min_confidence_threshold: 0.65      # ngưỡng xác suất tối thiểu từ clf_model
  min_magnitude_multiple_of_cost: 2.0 # biên độ dự đoán phải > N lần chi phí giao dịch
  atr_deadzone_multiplier: 0.1        # hệ số xác định vùng "đi ngang" khi gán nhãn
```

### 5.2. [CẬP NHẬT] Nội dung tin nhắn Alert — gộp chung Entry/TP/SL vào cùng 1 tin nhắn

**Yêu cầu:** Tin nhắn tín hiệu gửi về Telegram phải là **1 tin nhắn duy nhất, đầy đủ**, gộp cả kết quả dự đoán của model (hướng, độ tin cậy, biên độ) **và** kết quả tính toán Entry/TP/SL/R:R từ hàm `calculate_entry_tp_sl()` (mục 3.6) — không tách thành 2 tin nhắn riêng, để người đọc có đủ thông tin đặt lệnh ngay mà không phải tra cứu thêm.

**Luồng xử lý (signal engine → Telegram):**

```python
def build_signal_message(symbol: str, model_output: dict, trade_setup: dict, cost_estimate: dict) -> str:
    """
    model_output   : output từ clf_model + reg_model (mục 3.3)
                      { "direction": 1, "confidence": 0.78, "magnitude_pct": 0.18 }
    trade_setup     : output từ calculate_entry_tp_sl_xauusd() (mục 3.6)
                      { "entry": 2350.45, "tp": 2359.20, "sl": 2346.30,
                        "tp_distance_usd": 8.75, "sl_distance_usd": 4.15,
                        "risk_reward": 2.11, "valid": True }
    cost_estimate   : { "spread_usd": 0.35, "slippage_usd": 0.3, "safety_multiple": 2.4 }
    """
    direction_text = "TĂNG 📈" if model_output["direction"] == 1 else "GIẢM 📉"

    return (
        f"📊 [TÍN HIỆU M5 - {symbol}]\n"
        f"Hướng dự đoán: {direction_text} (độ tin cậy {model_output['confidence']*100:.0f}%)\n"
        f"Biên độ dự đoán: ~{model_output['magnitude_pct']:.3f}%\n"
        f"─────────────\n"
        f"🎯 Entry: {trade_setup['entry']}\n"
        f"✅ TP: {trade_setup['tp']}  (+{trade_setup['tp_distance_usd']:.1f} giá)\n"
        f"🛑 SL: {trade_setup['sl']}  (-{trade_setup['sl_distance_usd']:.1f} giá)\n"
        f"⚖️ Risk:Reward = 1:{trade_setup['risk_reward']}\n"
        f"─────────────\n"
        f"Chi phí ước tính (spread+slippage): ~{cost_estimate['spread_usd'] + cost_estimate['slippage_usd']:.2f} giá\n"
        f"Biên an toàn: {cost_estimate['safety_multiple']:.1f}x chi phí {'✅' if cost_estimate['safety_multiple'] >= 2.0 else '⚠️'}\n"
        f"Thời điểm: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    )
```

**Ví dụ tin nhắn thực tế được gửi:**

```
📊 [TÍN HIỆU M5 - XAUUSD]
Hướng dự đoán: TĂNG 📈 (độ tin cậy 78%)
Biên độ dự đoán: ~0.180%
─────────────
🎯 Entry: 2350.45
✅ TP: 2359.20  (+8.8 giá)
🛑 SL: 2346.30  (-4.2 giá)
⚖️ Risk:Reward = 1:2.11
─────────────
Chi phí ước tính (spread+slippage): ~0.65 giá
Biên an toàn: 2.4x chi phí ✅
Thời điểm: 2026-07-10 14:35:00
```

**Lưu ý quan trọng:**
1. Chỉ gọi `build_signal_message()` **sau khi** tín hiệu đã đi qua đủ 3 lớp lọc ở mục 3.6 (confidence đạt ngưỡng → biên độ > N lần chi phí → spread bình thường) — tin nhắn gửi đi luôn là tín hiệu đã được duyệt, tránh gửi nhiễu về Telegram.
2. Nếu `trade_setup["valid"] == False` (confidence chưa đạt ngưỡng), **không gọi hàm gửi tin nhắn** — có thể ghi log riêng để phân tích tỷ lệ tín hiệu bị loại, nhưng không đẩy lên Telegram để tránh gây nhiễu loạn quyết định người theo dõi.
3. Vì TP/SL đã bị giới hạn cứng trong khung 8-10/3-5 giá (mục 3.6), tin nhắn không cần hiển thị cảnh báo "TP/SL bất thường" như với thiết kế cũ dựa hoàn toàn vào ATR/magnitude tự do — khung cố định tự thân đã đảm bảo tính nhất quán giữa các tín hiệu.

### 5.3. [MỚI] Báo cáo trạng thái Bot định kỳ (Scheduled Status Report)

**Phân biệt với Heartbeat (mục 5.1):** Heartbeat chỉ là tín hiệu "còn sống" đơn giản ("I am alive"), không mang thông tin vận hành. Báo cáo trạng thái định kỳ (Status Report) là một module riêng, chạy theo chu kỳ **cấu hình được** (VD: mỗi 1h, 4h, hoặc cuối ngày), tổng hợp và gửi các chỉ số vận hành + hiệu suất giao dịch tính đến thời điểm đó.

**Nội dung Status Report cần có:**
1. Thời gian uptime của bot kể từ lần start gần nhất.
2. Số tín hiệu đã phát ra trong chu kỳ (và tổng số tín hiệu bị lọc bởi từng lớp filter: R:R, spread, magnitude — xem mục 3.6).
3. Số lệnh đang mở (nếu bot tự động đặt lệnh) và PnL tạm tính (floating PnL).
4. Win rate / Net PnL của các lệnh đã đóng trong chu kỳ.
5. Cảnh báo nếu có bất thường: latency vượt ngưỡng (`max_latency_seconds`), mất kết nối MT5/API, hoặc số lượng tín hiệu bị lọc bất thường cao (dấu hiệu thị trường đang biến động mạnh hoặc model có vấn đề).

**Bổ sung config (nối tiếp `config.yaml`):**

```yaml
monitor:
  heartbeat_interval_minutes: 5
  status_report_interval_minutes: 60   # chu kỳ gửi báo cáo trạng thái, tùy chỉnh được
```

**Thiết kế kỹ thuật (dùng scheduler độc lập, không block main loop xử lý tín hiệu):**

```python
import asyncio
from datetime import datetime

class StatusReporter:
    def __init__(self, bot_state, telegram_client, interval_minutes: int):
        self.bot_state = bot_state          # object/singleton lưu trạng thái runtime
        self.telegram_client = telegram_client
        self.interval_seconds = interval_minutes * 60
        self.start_time = datetime.now()

    async def run(self):
        while True:
            await asyncio.sleep(self.interval_seconds)
            report = self._build_report()
            await self.telegram_client.send_message(report)

    def _build_report(self) -> str:
        uptime = datetime.now() - self.start_time
        s = self.bot_state  # rút gọn tham chiếu

        return (
            f"🤖 [BÁO CÁO TRẠNG THÁI BOT]\n"
            f"Uptime: {str(uptime).split('.')[0]}\n"
            f"Tín hiệu phát ra: {s.signals_sent}\n"
            f"  - Bị loại (R:R thấp): {s.filtered_by_rr}\n"
            f"  - Bị loại (Spread bất thường): {s.filtered_by_spread}\n"
            f"  - Bị loại (Biên độ < chi phí): {s.filtered_by_magnitude}\n"
            f"Lệnh đang mở: {s.open_positions} | Floating PnL: {s.floating_pnl:.2f}%\n"
            f"Lệnh đã đóng (chu kỳ này): {s.closed_trades} | Win rate: {s.win_rate:.1f}%\n"
            f"Net PnL (chu kỳ này): {s.net_pnl:.2f}%\n"
            f"Latency hiện tại: {s.last_latency_seconds:.2f}s "
            f"{'⚠️ VƯỢT NGƯỠNG' if s.last_latency_seconds > s.max_latency_seconds else '✅'}\n"
            f"Kết nối MT5: {'✅ OK' if s.mt5_connected else '❌ MẤT KẾT NỐI'}"
        )
```

**Lưu ý triển khai:**
- `StatusReporter` nên chạy như một **task bất đồng bộ độc lập** (asyncio task riêng hoặc thread riêng), tránh làm chậm/nghẽn vòng lặp chính xử lý tín hiệu real-time (mục 4.2).
- `bot_state` nên là 1 object dùng chung (shared state), được các module khác (signal engine, order manager) cập nhật liên tục — cần cân nhắc thread-safety nếu dùng đa luồng (VD dùng `asyncio.Lock` hoặc queue thay vì truy cập trực tiếp).
- Nếu phát hiện bất thường nghiêm trọng (mất kết nối MT5, latency vượt ngưỡng nhiều chu kỳ liên tiếp), nên gửi **alert riêng ngay lập tức** thay vì chờ đến chu kỳ status report tiếp theo — tách biệt 2 luồng: cảnh báo tức thời (event-driven) và báo cáo định kỳ (schedule-driven).

---

## 6. LỘ TRÌNH TRIỂN KHAI ĐỀ XUẤT CHO KỸ SƯ

| Giai đoạn | Nội dung | Output |
|---|---|---|
| **Sprint 1** | Data pipeline: đọc CSV OHLCV Exness/MT5, chuẩn hóa timeframe/symbol, xây `candle_to_vector()` | DataFrame 40-feature sạch |
| **Sprint 2** | Baseline model: XGBoost classification nhị phân (như v1), walk-forward validation cơ bản | Báo cáo accuracy/AUC theo từng fold |
| **Sprint 3** | Nâng cấp nhãn: dead-zone 3-class + regression head biên độ | 2 model (clf + reg) |
| **Sprint 4** | Backtest engine có chi phí giao dịch, so sánh Gross vs Net PnL | Báo cáo backtest |
| **Sprint 5** | Thêm feature nhóm A/B (multi-timeframe, session) theo kiểu ablation study | So sánh performance trước/sau |
| **Sprint 6** | Module tính Entry/TP/SL + kiểm tra Risk:Reward (mục 3.6), tích hợp vào signal engine | Hàm `calculate_entry_tp_sl()` hoạt động end-to-end |
| **Sprint 7** | Module Telegram Alert + Heartbeat + Status Report định kỳ (mục 5.3), tích hợp signal_filter từ config | Bot chạy demo real-time, có báo cáo trạng thái tự động |
| **Sprint 8** | Forward test trên tài khoản demo tối thiểu 4-6 tuần trước khi cân nhắc live | Log giao dịch demo |

> ⚠️ Không khuyến nghị chuyển sang tài khoản live cho đến khi có kết quả walk-forward validation ổn định qua **tối thiểu 4-6 fold** và forward test demo cho kết quả Net PnL dương nhất quán.

---

## 7. [MỚI] YÊU CẦU TRIỂN KHAI & MÔ HÌNH VẬN HÀNH LOCAL (LOCAL DEPLOYMENT)

### 7.1. Xác nhận mô hình vận hành tối thiểu

Theo yêu cầu, hệ thống được thiết kế để chạy ở **chế độ local đơn giản nhất**, không cần server/cloud, không cần Docker hay dịch vụ nền phức tạp:

| Thành phần | Yêu cầu |
|---|---|
| Symbol giao dịch | **XAUUSD** (đã cấu hình cố định trong `config.yaml`, xem mục 5.1) |
| Máy tính | 1 máy local (Windows — bắt buộc, xem lưu ý 7.2), đã **mở sẵn và đăng nhập** ứng dụng MetaTrader 5 desktop |
| Kết nối | 1 đường internet ổn định (để MT5 cập nhật giá + gửi tin nhắn Telegram qua API) |
| Môi trường code | VS Code + Python đã cài các thư viện cần thiết (`requirements.txt`) |
| Lệnh chạy | `python run.py` — khởi động toàn bộ pipeline: kết nối MT5 → bootstrap dữ liệu → vòng lặp real-time → xử lý tín hiệu → xuất kết quả |

### 7.2. ⚠️ Lưu ý kỹ thuật bắt buộc (dễ bị bỏ sót)

1. **Thư viện `MetaTrader5` (package Python chính thức) chỉ chạy được trên Windows**, vì nó giao tiếp trực tiếp với MT5 terminal desktop qua cơ chế IPC nội bộ — **không chạy được trên macOS/Linux thuần**. Nếu kỹ sư dùng máy Mac/Linux, cần chạy qua máy ảo Windows hoặc dùng giải pháp thay thế (VD kết nối qua broker API/FIX riêng) — cần xác nhận trước khi bắt đầu code.
2. **MT5 desktop phải đang mở và đã đăng nhập sẵn** trước khi chạy `run.py` — package `MetaTrader5` không tự động mở/đăng nhập MT5 nếu ứng dụng đã đóng hoàn toàn, nó chỉ **attach** vào tiến trình MT5 đang chạy.
3. **Không tắt máy / để máy sleep** trong thời gian bot chạy — vì đây là mô hình local, không có cơ chế failover, mất kết nối = bot dừng hoàn toàn cho đến khi chạy lại `run.py`.

### 7.3. Kiến trúc `run.py` — output song song Terminal + Telegram

**Nguyên tắc:**
- **Terminal luôn nhận đầy đủ log** ở mọi chu kỳ xử lý (mỗi khi có nến mới đóng), bất kể có phát tín hiệu hay không — dùng để kỹ sư theo dõi trực tiếp khi ngồi máy.
- **Telegram chỉ nhận khi có tín hiệu hợp lệ** (đã qua đủ 3 lớp lọc mục 3.6) hoặc khi đến chu kỳ Status Report (mục 5.3) hoặc khi có cảnh báo bất thường (mục 5.3).
- Cả hai kênh dùng **chung 1 hàm build message**, đảm bảo nội dung nhất quán — terminal in ra bằng `print()`, Telegram gửi qua Bot API, không tạo 2 luồng logic tính toán riêng biệt để tránh lệch dữ liệu.

```python
# run.py — điểm khởi chạy chính của hệ thống

import time
import logging
from datetime import datetime

from core.mt5_connector import MT5Connector
from core.feature_engineer import FeatureEngineer
from core.model_engine import ModelEngine
from core.trade_setup import calculate_entry_tp_sl_xauusd
from core.telegram_notifier import TelegramNotifier
from core.status_reporter import StatusReporter
from core.bot_state import BotState
import config_loader

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger("run")


def main():
    cfg = config_loader.load("config.yaml")

    logger.info("Đang kết nối MT5 (yêu cầu MT5 desktop đã mở & đăng nhập sẵn)...")
    mt5 = MT5Connector(symbol=cfg["symbol"])
    if not mt5.connect():
        logger.error("❌ Không kết nối được MT5. Kiểm tra MT5 đã mở & login chưa.")
        return

    telegram = TelegramNotifier(cfg["telegram"]["bot_token"], cfg["telegram"]["chat_id"])
    state = BotState()
    model = ModelEngine.load(cfg["model_path"])
    feature_engineer = FeatureEngineer(cfg)

    logger.info("Bootstrap dữ liệu lịch sử (tháng trước + tháng hiện tại)...")
    history_df = mt5.load_bootstrap_history()
    logger.info(f"✅ Đã nạp {len(history_df)} nến vào bộ nhớ đệm.")

    # Chạy song song bộ đếm Status Report (không block vòng lặp chính)
    status_reporter = StatusReporter(state, telegram, cfg["monitor"]["status_report_interval_minutes"])
    status_reporter.start_background()

    telegram.send_message("🤖 Bot đã khởi động thành công và bắt đầu theo dõi thị trường.")
    logger.info("=== BẮT ĐẦU VÒNG LẶP REAL-TIME (Ctrl+C để dừng) ===")

    try:
        while True:
            new_candle = mt5.wait_for_next_candle_close()   # block đến khi nến M5 mới đóng
            history_df = feature_engineer.append_candle(history_df, new_candle)

            last_10 = feature_engineer.get_last_n(history_df, n=10)
            model_output = model.predict(last_10)            # {direction, confidence, magnitude_pct}

            trade_setup = calculate_entry_tp_sl_xauusd(
                entry_price=new_candle["close"],
                direction=model_output["direction"],
                confidence=model_output["confidence"],
                atr_current=feature_engineer.get_atr(history_df, cfg["trade_setup"]["atr_period"]),
                atr_average=feature_engineer.get_atr_average(history_df, cfg["trade_setup"]["atr_period"]),
                config=cfg["trade_setup"]
            )

            cost_estimate = mt5.get_cost_estimate()
            passed_filters = evaluate_signal_filters(model_output, trade_setup, cost_estimate, cfg)

            # --- LUÔN in ra terminal, kể cả khi tín hiệu bị loại ---
            log_line = format_terminal_log(new_candle, model_output, trade_setup, passed_filters)
            print(log_line)

            # --- CHỈ gửi Telegram khi tín hiệu hợp lệ ---
            if passed_filters:
                message = build_signal_message(cfg["symbol"], model_output, trade_setup, cost_estimate)
                telegram.send_message(message)
                state.record_signal_sent(trade_setup)
            else:
                state.record_signal_filtered(reason=passed_filters.reason)

    except KeyboardInterrupt:
        logger.info("Đã dừng bot theo yêu cầu người dùng.")
    finally:
        mt5.disconnect()
        telegram.send_message("🔴 Bot đã dừng hoạt động.")


if __name__ == "__main__":
    main()
```

**Ví dụ output trên terminal (mỗi khi có nến mới đóng — kể cả khi không đủ điều kiện gửi Telegram):**

```
2026-07-10 14:35:02 [INFO] Nến mới đóng: XAUUSD M5 | O=2350.10 H=2350.80 L=2349.60 C=2350.45
2026-07-10 14:35:02 [INFO] Model output: direction=TĂNG confidence=0.68 magnitude=0.12%
2026-07-10 14:35:02 [INFO] Trade setup: entry=2350.45 tp=2358.45 sl=2346.20 (TP +8.0 giá, SL -4.25 giá) R:R=1:1.88
2026-07-10 14:35:02 [INFO] ⚠️ Tín hiệu BỊ LOẠI — lý do: confidence (0.68) chưa vượt biên an toàn chi phí giao dịch
------------------------------------------------------------
2026-07-10 14:40:05 [INFO] Nến mới đóng: XAUUSD M5 | O=2350.45 H=2351.90 L=2350.20 C=2351.60
2026-07-10 14:40:05 [INFO] Model output: direction=TĂNG confidence=0.78 magnitude=0.180%
2026-07-10 14:40:05 [INFO] Trade setup: entry=2351.60 tp=2360.35 sl=2347.45 (TP +8.75 giá, SL -4.15 giá) R:R=1:2.11
2026-07-10 14:40:05 [INFO] ✅ Tín hiệu HỢP LỆ — đã gửi Telegram
------------------------------------------------------------
```

→ Tại thời điểm `14:40:05`, cả **terminal và Telegram đều nhận được cùng nội dung** (định dạng khác nhau: terminal dạng log ngắn gọn, Telegram dạng tin nhắn đầy đủ theo mẫu mục 5.2), vì cùng dùng chung dữ liệu `model_output` + `trade_setup` từ 1 vòng xử lý.

### 7.4. `requirements.txt` tối thiểu cho môi trường local

```
MetaTrader5>=5.0.45
xgboost>=2.0.0
pandas>=2.0.0
numpy>=1.24.0
scikit-learn>=1.3.0
python-telegram-bot>=21.0
pyyaml>=6.0
faiss-cpu>=1.7.4          # chỉ cần nếu triển khai Hướng A (mục 3.2)
```

### 7.5. Checklist trước khi chạy `python run.py`

- [ ] MT5 desktop đã mở, đã đăng nhập tài khoản demo/live thành công.
- [ ] File `config.yaml` đã điền đúng `bot_token`, `chat_id`, `symbol`, các ngưỡng filter.
- [ ] Đã train và lưu model (`clf_model`, `reg_model`) vào đúng `model_path` trong config.
- [ ] Kết nối internet ổn định (kiểm tra bằng cách ping thử Telegram API trước).
- [ ] Đã chạy thử ở tài khoản **demo** trước, chưa vội chuyển sang live (theo khuyến nghị Sprint 8, mục 6).

---

## PHỤ LỤC A: Rủi ro kỹ thuật cần lưu ý khi code

1. **Look-ahead bias:** đảm bảo feature của nến $t$ tuyệt đối không dùng thông tin từ nến $t+1$ trở đi (đặc biệt dễ mắc lỗi khi tính ATR/EMA nếu dùng thư viện không căn chỉnh index đúng).
2. **Timezone/DST:** dữ liệu Exness/MT5 thường theo giờ broker server, cần đồng bộ rõ ràng với giờ hệ thống khi tính session/hour feature (mục 2.3).
3. **Gap dữ liệu cuối tuần / ngày lễ:** cần xử lý riêng, không để mô hình học nhầm gap giá cuối tuần như 1 "cây nến" bình thường.
4. **Retrain định kỳ:** vì thị trường thay đổi regime theo thời gian, nên có lịch retrain định kỳ (VD: hàng tháng) thay vì dùng 1 model cố định vô thời hạn.

## PHỤ LỤC B: Lưu ý riêng khi áp dụng cho BTC/Crypto (tham khảo mở rộng — ngoài phạm vi hiện tại)

> **Lưu ý:** Phạm vi triển khai hiện tại đã chốt là **XAUUSD**. Phần này giữ lại chỉ để tham khảo cho khả năng mở rộng sang BTC trong tương lai, không nằm trong scope Sprint hiện tại (mục 6).

- BTC giao dịch 24/7, không có khái niệm "phiên đóng cửa" như forex/vàng → feature `session` (mục 2.3) cần thiết kế lại theo giờ hoạt động của các sàn lớn (Á/Âu/Mỹ) thay vì phiên giao dịch truyền thống.
- Volatility clustering ở BTC thường mạnh và kéo dài hơn — cân nhắc thêm feature GARCH-based volatility hoặc rolling realized volatility thay vì chỉ ATR đơn thuần.
- Nếu có dữ liệu order book/funding rate (qua Binance/Bybit API), đây thường là tín hiệu có giá trị cao hơn OHLC thuần túy — nên đưa vào roadmap Sprint sau khi MVP XAUUSD chạy ổn định.
- Spread trên BTC-CFD của broker MT5 có cơ chế biến động khác XAUUSD (thường giãn mạnh hơn nhiều vào giờ thấp thanh khoản) — ngưỡng filter cần tune riêng, không dùng chung tham số.
- Khung TP/SL cố định 8-10/3-5 giá (mục 3.6) được thiết kế riêng cho biên độ dao động của XAUUSD — nếu mở rộng sang BTC cần tính lại hoàn toàn theo biên độ USD đặc thù của BTC (thường lớn hơn nhiều lần).