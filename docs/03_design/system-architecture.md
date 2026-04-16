# システム構成設計

## 概要

圧入管理データ（.pilx）と柱状図データ（XML）をペアで読み込み、地層ごとの圧入自動運転設定パラメータテーブルを構築・更新するシステムの全体構成を定義する。

## コンセプト

```
                 ┌────────────────────┐
                 │  データペア入力     │
                 │  (.pilx + XML)     │
                 └────────┬───────────┘
                          │
                          ▼
              ┌──────────────────────┐
              │  ① パーサ層          │
              │  ├ PILX パーサ       │
              │  └ XML パーサ        │
              │    (全DTDバージョン)  │
              └────────┬─────────────┘
                       │ 正規化済みデータ
                       ▼
              ┌──────────────────────┐
              │  ② 深度アライメント  │
              │  地層区間 × 圧入データ│
              │  の突き合わせ        │
              └────────┬─────────────┘
                       │ 地層別圧入実績
                       ▼
              ┌──────────────────────┐
              │  ③ 特徴量抽出        │
              │  地層ごとの圧入      │
              │  パラメータ統計      │
              └────────┬─────────────┘
                       │ 地層別統計量
                       ▼
              ┌──────────────────────┐
              │  ④ テーブル更新      │
              │  既存テーブルと      │
              │  マージ・統計更新    │
              └────────┬─────────────┘
                       │
                       ▼
              ┌──────────────────────┐
              │ パラメータテーブル    │
              │ (土質×N値→設定値)   │
              └──────────────────────┘
```

## データフロー詳細

### 入力データペア

1組の入力は以下の2ファイル：

| データ | ファイル | 役割 |
|---|---|---|
| 圧入管理データ | `.pilx` | 実際の施工パラメータ（実績） |
| 柱状図データ | `BED?????.XML` | 地層構成・N値（地盤条件） |

> **注記：** `.pilx` のフッター柱状図はXML不在時の代替として使用可能。ただしXMLのほうが情報量が多いためXMLを優先する。

### 入力→出力の変換イメージ

```
入力ペア #1 (現場A-杭1)
  柱状図: [砂(N=5, 0-3m)] [粘土(N=2, 3-7m)] [砂礫(N=30, 7-10m)]
  圧入実績: 深度0-10mの100ms時系列データ
      ↓ 深度アライメント＋特徴量抽出
  結果: 砂(N=5)→{圧入力avg=120kN, 速度avg=80mm/min, ...}
        粘土(N=2)→{圧入力avg=60kN, 速度avg=150mm/min, ...}
        砂礫(N=30)→{圧入力avg=350kN, 速度avg=20mm/min, ...}
      ↓ テーブル更新
入力ペア #2 (現場B-杭3)
  柱状図: [砂(N=8, 0-5m)] [岩(N=50, 5-8m)]
  圧入実績: 深度0-8mの100ms時系列データ
      ↓ 深度アライメント＋特徴量抽出
  結果: 砂(N=8)→{圧入力avg=180kN, ...}
        岩(N=50)→{圧入力avg=500kN, ...}
      ↓ テーブル更新（既存データとマージ）

パラメータテーブル（累積）:
| 土質分類 | N値範囲 | サンプル数 | 圧入力avg | 圧入力std | 速度avg | ... |
|---------|---------|-----------|-----------|-----------|---------|-----|
| 砂      | 0-10    | 2         | 150       | 42        | ...     | ... |
| 粘土    | 0-4     | 1         | 60        | —         | ...     | ... |
| 砂礫    | 20-50   | 1         | 350       | —         | ...     | ... |
| 岩      | ≥50     | 1         | 500       | —         | ...     | ... |
```

---

## コンポーネント設計

### ① パーサ層

2種のファイルを共通の内部データモデルに変換する。

#### PILX パーサ

```
入力: .pilx ファイル
出力: PileRecord
  ├── header: PileHeader        # INIパラメータ、メタ情報
  ├── timeseries: DataFrame     # 100ms間隔の91列時系列データ
  └── footer: BoreholeSimple    # 簡易柱状図（地層、N値、水位）
```

**処理内容：**
- ヘッダーセクションのINI1〜INI67をパース
- CSVデータセクションを DataFrame に変換（91列）
- フッターの柱状図データ（地層・N値・水位）をパース
- 深度単位を mm に統一（フッターは cm→mm 変換）

#### XML パーサ

```
入力: BED?????.XML ファイル
出力: BoreholeRecord
  ├── meta: BoreholeMeta         # 調査基本情報、座標、会社
  ├── basic: BoreholeBasic       # 孔口標高、総削孔長
  ├── layers: List[SoilLayer]    # 地層（土質名、記号、深度）
  ├── spt: List[SPTResult]       # 標準貫入試験（N値）
  └── water_level: float | None  # 地下水位
```

**処理内容：**
- DTD_version を判定し、要素名マッピングを適用
- 貫入量の単位正規化（v3.00以前: cm→mm）
- `Shift_JIS` エンコーディングで読み込み
- 深度単位を mm に統一

#### 内部データモデル

```python
@dataclass
class SoilLayer:
    """地層"""
    depth_top: float     # 上端深度 (mm)
    depth_bottom: float  # 下端深度 (mm)
    soil_name: str       # 土質名（例: シルト質砂）
    soil_symbol: str     # 記号（例: SM）
    soil_category: str   # 大分類（粘性土/砂質土/礫質土/岩盤）
    n_values: list[int]  # この層内のN値リスト
    avg_n_value: float   # この層内のN値平均

@dataclass
class PressInSegment:
    """地層に対応する圧入実績データの区間"""
    layer: SoilLayer
    timeseries: DataFrame  # 当該深度区間の時系列データ（部分）
    duration: float        # 区間の施工時間 (s)
    depth_range: tuple[float, float]  # (mm, mm)
```

---

### ② 深度アライメント

柱状図の地層区間と圧入管理データの時系列を深度で突き合わせる。

#### アライメントロジック

```
柱状図:
  Layer 1: 0 ─── 2800mm (埋土)
  Layer 2: 2800 ─ 3550mm (砂)
  Layer 3: 3550 ─ 4900mm (砂礫)

圧入データ (時系列, 深度列で切り出し):
  t=0s    → depth=0mm
  t=10s   → depth=500mm     ← Layer 1 の区間
  ...
  t=120s  → depth=2800mm    ← Layer 1/2 の境界
  t=130s  → depth=3000mm    ← Layer 2 の区間
  ...
```

**処理ステップ：**

1. **圧入データの深度列を参照**し、各行がどの地層に属するかを判定
2. 地層境界の深度で時系列データを**分割**
3. 各地層に属するデータ行を `PressInSegment` として切り出す

#### 考慮事項

| 課題 | 対処 |
|---|---|
| 圧入深度と柱状図深度のゼロ点ずれ | 孔口標高・開始深度で補正 |
| 引抜中のデータ | 動作フラグ（チャック上/下）で圧入区間のみ抽出 |
| チャック掴み替え中の停滞 | 深度変化がない区間を除外するオプション |
| 柱状図とPILXの地層不一致 | PILXフッター柱状図 vs XML柱状図の選択ルール |

#### ペアリング（どのXMLとどのPILXを組み合わせるか）

現時点では手動指定。将来的には以下でマッチング可能：

- 現場名（INI6 ↔ 事業工事名）
- 座標（INI21/22 ↔ 経度緯度情報）
- 日付（INI24/25 ↔ 調査期間）

---

### ③ 特徴量抽出

各 `PressInSegment` から、地層ごとの圧入自動運転設定値を抽出する。

> **設計判断:** 地層ごとに定義する設定値は、圧入データ内に同じ設定値カラムが存在するため、そのまま抽出する（地層区間での最頻値）。

#### 抽出対象: 自動運転設定パラメータ（36項目）

PILX のデータカラムから抽出する設定値。詳細は [parameter-mapping.md](parameter-mapping.md) を参照。

| カテゴリ | パラメータ数 | 主要項目 |
|---|---|---|
| A. 圧入力・引抜力 | 3 | 圧入力上下限、引抜力 |
| B. ストローク・圧入長 | 3 | 圧入/引抜ストローク、圧入長 |
| C. 傾斜 | 2 | 前後・左右傾斜 |
| D. チャック上下速度 | 6 | スピードモード・スピード値 |
| E. 把持力 | 2 | チャック・クランプ |
| F. ウォータージェット | 1 | WJ水量 |
| G. オーガ | 10 | トルク・スピード・待機時間 |
| H. チャック回転 | 8 | トルク・スピード・待機時間 |
| I. LS個別水量 | 1 | LS個別水量 |
| **合計** | **36** | |

#### 抽出方法

設定値カラムはオペレータが地層に応じて変更した値なので、地層区間での**最頻値（mode）**を取る。

```python
# 各設定値カラムに対して
for param in SETTING_PARAMS:  # 36パラメータ
    values = segment.timeseries[param.column]
    recommended = values.mode().iloc[0]  # 最頻値
```

#### フィルタリング条件

特徴量抽出前に以下のフィルタを適用：

| フィルタ | 条件 | 理由 |
|---|---|---|
| 圧入動作のみ | カラム60（チャック下）= 1 | 引抜・停止中のデータを除外 |
| 自動運転のみ | カラム77（圧入自動）= 1 | 手動操作データを除外（オプション） |
| 深度変化あり | Δdepth > 0 | チャック掴み替え等の停滞除外 |

#### 出力フォーマット

```python
@dataclass
class LayerSettings:
    """地層ごとの自動運転設定値"""
    # 地盤条件
    soil_category: str      # 土質大分類
    soil_name: str          # 土質名
    soil_symbol: str        # 土質記号
    avg_n_value: float      # 平均N値
    n_value_range: tuple[int, int]  # N値範囲
    layer_thickness: float  # 層厚 (mm)
    depth_range: tuple[float, float]  # 深度範囲 (mm)

    # A. 圧入力・引抜力
    a1_press_force_upper: float     # 圧入力設定（上限）[kN]
    a2_press_force_lower: float     # 圧入力設定（下限）[kN]
    a3_pull_force: float            # 引抜力設定 [kN]

    # B. ストローク・圧入長
    b1_press_stroke: float          # 圧入ストローク設定 [×0.1mm]
    b2_pull_stroke: float           # 引抜ストローク設定 [×0.1mm]
    b3_press_pull_length: float     # 圧入長/引抜長設定 [×0.1m]

    # C. 傾斜
    c1_tilt_fb: float               # パイラー前後傾斜設定 [×0.01度]
    c2_tilt_lr: float               # パイラー左右傾斜設定 [×0.01度]

    # D. チャック上下速度
    d1_chuck_up_speed_mode: int     # チャック上スピードモード
    d2_chuck_down_new_speed_mode: int    # チャック下（新規地盤）モード
    d3_chuck_down_after_pull_speed_mode: int  # チャック下（引抜後）モード
    d4_chuck_up_speed: float        # チャック上スピード [mm/s]
    d5_chuck_down_new_speed: float  # チャック下（新規地盤）[mm/s]
    d6_chuck_down_after_pull_speed: float  # チャック下（引抜後）[mm/s]

    # E. 把持力
    e1_chuck_grip: float            # チャック把持力設定
    e2_clamp_grip: float            # クランプ把持力設定

    # F. ウォータージェット
    f1_wj_water: float              # WJ水量 [×0.1 L/min]

    # G. オーガ
    g1_auger_torque_fwd_upper: float    # オーガ正転トルク上限 [kN・m]
    g2_auger_torque_fwd_lower: float    # オーガ正転トルク下限 [kN・m]
    g3_auger_torque_rev: float          # オーガ逆転トルク [kN・m]
    g4_press_force_wait: float          # 圧入力超過待機時間 [×0.1s]
    g5_auger_torque_wait: float         # オーガトルク超過待機時間 [×0.1s]
    g6_casing_ud_speed_mode: int        # ケーシング上下モード
    g7_auger_ud_speed_mode: int         # オーガ上下モード
    g8_auger_rot_speed_mode: int        # オーガ回転モード
    g9_auger_speed_fwd: float           # オーガ正転スピード [×0.1 min⁻¹]
    g10_auger_speed_rev: float          # オーガ逆転スピード [×0.1 min⁻¹]

    # H. チャック回転
    h1_chuck_torque_fwd_upper: float    # チャック正転トルク上限 [kN・m]
    h2_chuck_torque_fwd_lower: float    # チャック正転トルク下限 [kN・m]
    h3_chuck_torque_rev: float          # チャック逆転トルク [kN・m]
    h4_press_force_wait_rot: float      # 圧入力超過待機時間 [×0.1s]
    h5_chuck_torque_wait: float         # チャックトルク超過待機時間 [×0.1s]
    h6_chuck_rot_speed_mode: int        # チャック回転モード
    h7_chuck_speed_fwd: float           # チャック正転スピード [×0.1 min⁻¹]
    h8_chuck_speed_rev: float           # チャック逆転スピード [×0.1 min⁻¹]

    # I. LS個別水量
    i1_ls_water: float                  # LS個別水量 [×0.1 L/min]

    # メタ情報
    source_pilx: str            # 元ファイル名
    source_xml: str             # 元ファイル名
    pile_spec: str              # 杭仕様
    method: str                 # 工法（単独/ジェット併用/オーガ併用等）
```

---

### ④ テーブル更新

蓄積型のパラメータテーブルを管理する。新しいデータペアが投入されるたびにテーブルが更新される。

#### テーブル構造

**レベル1: 個別レコード（生データ）**

すべての地層別設定値を蓄積する。1データペアの1地層が1行。1行に36個の設定値カラムを持つ。

```
layer_records.csv:
| record_id | source_pilx | source_xml | soil_category | soil_name | avg_n_value | method | a1 | a2 | a3 | b1 | ... | i1 |
```

**レベル2: 集約テーブル（推奨設定値）**

土質大分類×N値レンジで集約した推奨設定値テーブル。36パラメータそれぞれにつき推奨値・参考範囲を持つ。

```
parameter_table.csv:
| soil_category | n_value_min | n_value_max | sample_count | a1_recommended | a1_min | a1_max | a2_recommended | ... | i1_recommended | confidence |
```

#### 更新ロジック

```
新しいデータペア投入時:
  1. パース → アライメント → 特徴量抽出
  2. レベル1テーブルに個別レコードを追加（append）
  3. レベル2テーブルを再集約（全レコードから再計算）
```

#### 集約ルール

| 推奨値の算出方法 | 説明 |
|---|---|
| 実績の中央値 | 外れ値に強い。サンプル少数時に安定 |
| 設定値の最頻値 | 熟練オペレータの判断を反映 |
| 信頼度 | サンプル数に基づく（n<3: 低、3≤n<10: 中、n≥10: 高） |

```python
# 集約例
def aggregate_table(records: DataFrame) -> DataFrame:
    """個別レコードから推奨設定値テーブルを生成"""
    setting_cols = [f"{cat}{num}" for cat, num in SETTING_PARAM_IDS]  # a1, a2, ..., i1
    grouped = records.groupby(["soil_category", "n_value_bin"])

    agg_dict = {"record_id": "count"}
    for col in setting_cols:
        agg_dict[f"{col}_recommended"] = (col, lambda x: x.mode().iloc[0])
        agg_dict[f"{col}_min"] = (col, "min")
        agg_dict[f"{col}_max"] = (col, "max")

    table = grouped.agg(**agg_dict)
    table.rename(columns={"record_id": "sample_count"}, inplace=True)

    # 信頼度の付与
    table["confidence"] = table["sample_count"].apply(
        lambda n: "高" if n >= 10 else ("中" if n >= 3 else "低")
    )
    return table
```

#### N値のビニング（区間分割）

| 土質大分類 | N値ビン | 根拠 |
|---|---|---|
| 粘性土 | 0-2, 2-4, 4-8, 8-15, ≥15 | 稠度区分に対応 |
| 砂質土 | 0-4, 4-10, 10-30, 30-50, ≥50 | 相対密度区分に対応 |
| 礫質土 | 0-10, 10-30, 30-50, ≥50 | — |
| 岩盤 | ≥50（N値拒否含む） | — |

---

## モジュール構成

```
src/
├── parsers/                     # ① パーサ層
│   ├── __init__.py
│   ├── pilx_parser.py           # .pilx ファイルパーサ
│   ├── xml_parser.py            # XML ボーリングデータパーサ
│   ├── dtd_mapping.py           # DTDバージョン別要素名マッピング
│   └── models.py                # 内部データモデル定義
│
├── alignment/                   # ② 深度アライメント
│   ├── __init__.py
│   └── depth_aligner.py         # 地層×時系列の突き合わせ
│
├── features/                    # ③ 特徴量抽出
│   ├── __init__.py
│   ├── extractor.py             # 地層別特徴量抽出
│   └── filters.py               # 圧入区間フィルタ
│
├── table/                       # ④ テーブル管理
│   ├── __init__.py
│   ├── record_store.py          # 個別レコードの永続化
│   ├── aggregator.py            # 集約ロジック
│   └── parameter_table.py       # 推奨設定値テーブル
│
├── pipeline.py                  # パイプライン統合（①→②→③→④）
└── config.py                    # 設定（N値ビン定義、フィルタ条件等）

data/
├── samples/                     # 入力サンプル
│   ├── No8_20240612134904_No.8.pilx
│   └── BED0001.XML
├── schemas/                     # スキーマ定義
├── records/                     # レベル1: 個別レコード蓄積
│   └── layer_records.csv
└── tables/                      # レベル2: 推奨設定値テーブル
    └── parameter_table.csv
```

---

## パイプライン実行フロー

```python
# 1データペアの処理
def process_pair(pilx_path: str, xml_path: str) -> None:
    # ① パース
    pile = pilx_parser.parse(pilx_path)
    borehole = xml_parser.parse(xml_path)

    # ② 深度アライメント
    segments = depth_aligner.align(
        layers=borehole.layers,
        timeseries=pile.timeseries,
        spt=borehole.spt,
    )

    # ③ 特徴量抽出
    features = [extractor.extract(seg) for seg in segments]

    # ④ テーブル更新
    record_store.append(features)
    parameter_table.rebuild(record_store.all_records())
```

```python
# 複数ペアの逐次投入
pairs = [
    ("site_A/pile_1.pilx", "site_A/BED0001.XML"),
    ("site_A/pile_2.pilx", "site_A/BED0001.XML"),  # 同じ柱状図を複数杭で共有
    ("site_B/pile_1.pilx", "site_B/BED0001.XML"),
]
for pilx, xml in pairs:
    process_pair(pilx, xml)

# テーブル確認
print(parameter_table.to_dataframe())
```

---

## パラメータテーブルの利用（将来）

蓄積されたテーブルは以下の用途で利用する：

```
新規現場の柱状図 → パラメータテーブル参照 → 圧入自動運転設定値を自動生成

  ┌────────────┐     ┌────────────────┐     ┌──────────────┐
  │ 新規柱状図  │────▶│ テーブル検索    │────▶│ 設定値出力    │
  │ XML/PDF     │     │ 土質×N値で     │     │ 杭ごとの深度  │
  │             │     │ マッチング      │     │ 別設定プロファ │
  └────────────┘     └────────────────┘     │ イル          │
                                             └──────────────┘
```

---

## 設計上の判断事項（要検討）

| # | 項目 | 選択肢 | 現時点の方針 |
|---|---|---|---|
| 1 | 実績値 vs 設定値どちらを推奨値にするか | 実績の統計 / オペレータ設定の最頻値 / 両方併記 | 両方併記（実績=参考、設定=推奨） |
| 2 | 自動運転データのみ使うか | 自動のみ / 手動含む / 選択可能 | 選択可能（フィルタオプション） |
| 3 | 柱状図と杭のマッチング距離 | 同一ボーリング / 近傍50m以内 / 手動 | 手動指定（初期段階） |
| 4 | N値ビンの粒度 | 固定ビン / 適応的ビン | 固定ビン（まずは標準的な区分で） |
| 5 | テーブルの保存形式 | CSV / JSON / SQLite | CSV（透明性重視） |
| 6 | 外れ値の処理 | 除外 / ロバスト統計 | 中央値ベースの集約（外れ値に強い） |
| 7 | 杭仕様の影響 | テーブルに杭仕様を含めるか | 初期は含めない（サンプル不足のため） |

---

## 技術スタック

| 用途 | 技術 | 理由 |
|---|---|---|
| 言語 | Python 3.11+ | プロジェクト規約 |
| データ処理 | pandas | プロジェクト規約、時系列操作に適合 |
| XMLパース | xml.etree.ElementTree | 標準ライブラリ、DTD検証不要 |
| データ保存 | CSV (pandas I/O) | 人間可読、Excelで確認可能 |
| 設定管理 | YAML | N値ビン定義・フィルタ条件等 |
| テスト | pytest | 標準的 |
| 可視化（将来） | matplotlib | pandas と連携しやすい |
