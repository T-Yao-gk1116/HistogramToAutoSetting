# アルゴリズム仕様

## 概要

柱状図→圧入設定値の自動変換アルゴリズムの詳細仕様。本書では各処理ステップの具体的なアルゴリズムを定義する。

全体構成は [system-architecture.md](system-architecture.md) を参照。

## アルゴリズム1: 深度アライメント

### 入力

- `layers`: 地層リスト \[SoilLayer\]（depth_top, depth_bottom 昇順）
- `timeseries`: 圧入時系列データ（DataFrame、depth 列あり）

### 処理

```
for each layer in layers:
    mask = (timeseries.depth >= layer.depth_top) & (timeseries.depth < layer.depth_bottom)
    segment = timeseries[mask]
    yield PressInSegment(layer=layer, timeseries=segment)
```

### 境界処理

- 圧入データの深度が地層下端ちょうどの行 → 次の地層に含める（`<` で判定）
- 圧入データの最大深度 < 最深地層の下端 → 圧入データが到達した深度まで
- 地層にデータ行が0件 → 当該地層はスキップ（記録はするがテーブル更新に使わない）

## アルゴリズム2: 圧入区間フィルタ

### 入力

- `segment`: PressInSegment（地層1つ分の時系列）

### フィルタ条件

```
# 圧入動作中のみ（チャック下降中）
filtered = segment[segment.col_60 == 1]  # カラム60: チャック下

# オプション: 自動運転のみ
if auto_only:
    filtered = filtered[filtered.col_77 == 1]  # カラム77: 圧入自動

# 深度変化ありのみ（停滞除外）
filtered = filtered[filtered.depth.diff() > 0]
```

## アルゴリズム3: 圧入速度算出

```
depth_diff = segment.depth.diff()     # mm
time_diff = 0.1                        # 100ms = 0.1s
speed_mm_per_sec = depth_diff / time_diff
speed_mm_per_min = speed_mm_per_sec * 60

# 負の速度（引抜）と異常値を除外
speed_mm_per_min = speed_mm_per_min[speed_mm_per_min > 0]
speed_mm_per_min = speed_mm_per_min[speed_mm_per_min < threshold]  # 異常値カット
```

## アルゴリズム4: 設定値抽出

地層区間のフィルタ済みデータから、36個の自動運転設定パラメータを抽出する。

> **方針:** 圧入データ内に同じ設定値カラムが存在するため、そのまま最頻値を取る。

### パラメータ定義

設定パラメータの定義は [parameter-mapping.md](parameter-mapping.md) を参照（A1〜I1、全36項目）。

### 抽出処理

```python
# 設定パラメータとPILXカラムのマッピング（config.yaml で定義）
SETTING_PARAMS = {
    "a1": {"column": 34,  "name": "圧入力設定（上限）"},
    "a2": {"column": 82,  "name": "圧入力設定（下限）"},
    "a3": {"column": "?", "name": "引抜力設定"},
    "b1": {"column": 35,  "name": "圧入ストローク設定"},
    "b2": {"column": 36,  "name": "引抜ストローク設定"},
    "b3": {"column": "?", "name": "圧入長/引抜長設定"},
    "c1": {"column": 49,  "name": "パイラー前後傾斜設定"},
    "c2": {"column": 50,  "name": "パイラー左右傾斜設定"},
    "d1": {"column": "?", "name": "チャック上スピードモード設定"},
    "d2": {"column": "?", "name": "チャック下（新規地盤）スピードモード設定"},
    "d3": {"column": "?", "name": "チャック下（引抜動作後）スピードモード設定"},
    "d4": {"column": 33,  "name": "チャック上スピード設定"},
    "d5": {"column": 32,  "name": "チャック下（新規地盤）スピード設定"},
    "d6": {"column": "?", "name": "チャック下（引抜動作後）スピード設定"},
    "e1": {"column": "?", "name": "チャック把持力設定"},
    "e2": {"column": "?", "name": "クランプ把持力設定"},
    "f1": {"column": "?", "name": "WJ水量"},
    "g1": {"column": 37,  "name": "オーガ正転トルク設定（上限）"},
    "g2": {"column": 83,  "name": "オーガ正転トルク設定（下限）"},
    "g3": {"column": 38,  "name": "オーガ逆転トルク設定"},
    "g4": {"column": "?", "name": "圧入力超過待機時間設定"},
    "g5": {"column": "?", "name": "オーガ正転トルク超過待機時間設定"},
    "g6": {"column": "?", "name": "ケーシング上下スピードモード設定"},
    "g7": {"column": "?", "name": "オーガ上下スピードモード設定"},
    "g8": {"column": "?", "name": "オーガ回転スピードモード設定"},
    "g9": {"column": 39,  "name": "オーガ正転スピード設定"},
    "g10": {"column": 40, "name": "オーガ逆転スピード設定"},
    "h1": {"column": 43,  "name": "チャック正転トルク設定（上限）"},
    "h2": {"column": 84,  "name": "チャック正転トルク設定（下限）"},
    "h3": {"column": 44,  "name": "チャック逆転トルク設定"},
    "h4": {"column": "?", "name": "圧入力超過待機時間設定（回転時）"},
    "h5": {"column": "?", "name": "チャック正転トルク超過待機時間設定"},
    "h6": {"column": "?", "name": "チャック回転スピードモード設定"},
    "h7": {"column": 45,  "name": "チャック正転スピード設定"},
    "h8": {"column": 46,  "name": "チャック逆転スピード設定"},
    "i1": {"column": "86-89", "name": "LS個別水量"},
}
# "?" はカラム番号未特定。追加サンプルまたは機械仕様書で確認が必要。

for param_id, param_def in SETTING_PARAMS.items():
    col = param_def["column"]
    if col == "?":
        settings[param_id] = None  # 未特定
        continue
    values = filtered[col]
    settings[param_id] = values.mode().iloc[0] if len(values) > 0 else None
```

### 工法による有効パラメータの判定

工法フラグ（PILXカラム69-76）で使用工法を判定し、該当しないカテゴリのパラメータは null とする。

```python
METHOD_FLAGS = {
    69: "矢板単独",      70: "矢板ジェット併用",
    71: "矢板オーガ併用", 72: "コンビジャイロ",
    73: "鋼管単独",       74: "鋼管ジェット併用",
    75: "鋼管オーガ併用", 76: "ジャイロ",
}

# 工法ごとに有効なパラメータカテゴリ
ACTIVE_CATEGORIES = {
    "矢板単独":       ["A", "B", "C", "D", "E"],
    "矢板ジェット併用": ["A", "B", "C", "D", "E", "F", "I"],
    "矢板オーガ併用":  ["A", "B", "C", "D", "E", "F", "G", "I"],
    "コンビジャイロ":  ["A", "B", "C", "D", "E", "F", "G", "H", "I"],
    # ...
}
```

## アルゴリズム5: N値ビニング

```
def n_value_bin(soil_category: str, avg_n: float) -> str:
    bins = N_VALUE_BINS[soil_category]  # 設定ファイルから取得
    for min_val, max_val, label in bins:
        if min_val <= avg_n < max_val:
            return label
    return bins[-1].label  # 最大区間
```

## アルゴリズム6: テーブル集約

36パラメータそれぞれについて、同一キー（土質×N値ビン）内のレコードから推奨値を算出する。

```python
setting_cols = ["a1", "a2", "a3", "b1", ..., "i1"]  # 36列

grouped = all_records.groupby(["soil_category", "n_value_bin"])

for (cat, nbin), group in grouped:
    result = {
        "soil_category": cat,
        "n_value_bin": nbin,
        "sample_count": len(group),
    }
    for col in setting_cols:
        valid = group[col].dropna()
        if len(valid) > 0:
            result[f"{col}_recommended"] = valid.mode().iloc[0]  # 最頻値
            result[f"{col}_min"] = valid.min()
            result[f"{col}_max"] = valid.max()
        else:
            result[f"{col}_recommended"] = None
    result["confidence"] = confidence_level(len(group))
```

## 未定事項

| 項目 | 状態 | 備考 |
|---|---|---|
| PILXカラム番号の未特定分（"?"） | 要確認 | 追加サンプルデータまたは機械仕様書で特定する |
| N値拒否（99999）の扱い | 要検討 | N=60 として扱う案 |
| 埋土（FI）の土質再分類 | 要検討 | 中身に応じて砂/粘土に再分類するか |
| LS個別水量のカラム構造 | 要確認 | 86-89（LS-A〜D）の扱い方 |
| スピードモード値の意味 | 要確認 | モード整数値の定義（1=低速, 2=中速, ...等） |
