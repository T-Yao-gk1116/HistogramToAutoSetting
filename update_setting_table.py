"""柱状図と圧入管理データから地層ごとの圧入自動運転設定値テーブルを更新するスクリプト

使用方法:
    python update_setting_table.py \\
        --borehole data/samples/BED0001.XML \\
        --press-in data/samples/No8_20240612134904_No.8.pilx

    python update_setting_table.py \\
        --borehole data/samples/BED0001.XML \\
        --press-in data/samples/PIN_SY75_5001_20260416065715.bin

    # XMLなしでPILXのフッター柱状図を使う場合
    python update_setting_table.py \\
        --press-in data/samples/No8_20240612134904_No.8.pilx

    # 出力先を指定する場合
    python update_setting_table.py \\
        --borehole data/samples/BED0001.XML \\
        --press-in data/samples/No8_20240612134904_No.8.pilx \\
        --records-table data/table/layer_records.csv \\
        --setting-table data/table/setting_table.csv

出力:
    data/table/layer_records.csv  - レベル1：地層ごとの設定値レコード（蓄積）
    data/table/setting_table.csv  - レベル2：土質×N値ビンの集約推奨設定値テーブル
"""

from __future__ import annotations

import argparse
import csv
import struct
import sys
from dataclasses import dataclass, field, fields, asdict
from pathlib import Path
from statistics import mode as stat_mode
from typing import Optional
import xml.etree.ElementTree as ET

# ---------------------------------------------------------------------------
# 設定値パラメータ定義
# ---------------------------------------------------------------------------

# PILX データセクションの設定値カラム名
# （[ITEMLIST_START] で確認した実際の列名を使用）
SETTING_COLUMNS_PILX: dict[str, str] = {
    "a1_圧入力設定":               "圧入力設定",
    "a2_圧入力下限設定":           "圧入力下限設定",
    "b1_圧入ストローク設定":       "圧入ストローク設定",
    "b2_引抜ストローク設定":       "引抜ストローク設定",
    "c1_機械前後傾斜制限設定":     "機械前後傾斜制限設定",
    "c2_機械左右傾斜制限設定":     "機械左右傾斜制限設定",
    "d4_チャック上スピード設定":   "チャック上げスピード設定",
    "d5_チャック下スピード設定":   "チャック下スピード設定",
    "g1_オーガ正転トルク設定":     "オーガ正転トルク設定",
    "g2_オーガ正転トルク下限設定": "オーガ正転トルク下限設定",
    "g3_オーガ逆転トルク設定":     "オーガ逆転トルク設定",
    "g9_オーガ正転スピード設定":   "オーガ正転スピード設定",
    "g10_オーガ逆転スピード設定":  "オーガ逆転スピード設定",
    "h1_チャック正転トルク設定":   "チャック正転トルク設定",
    "h2_チャック正転トルク下限設定": "チャック正転トルク下限設定",
    "h3_チャック逆転トルク設定":   "チャック逆転トルク設定",
    "h7_チャック正転スピード設定": "チャック正転スピード設定",
    "h8_チャック逆転スピード設定": "チャック逆転スピード設定",
    "i1a_設定水量LS-A":            "設定水量(LS-A)",
    "i1b_設定水量LS-B":            "設定水量(LS-B)",
    "i1c_設定水量LS-C":            "設定水量(LS-C)",
    "i1d_設定水量LS-D":            "設定水量(LS-D)",
}

# バイナリデータの設定値フィールド名（parse_bin.py の dict キーに対応）
SETTING_COLUMNS_BIN: dict[str, str] = {
    "a1_圧入力設定":               "圧入力設定_x10kN",
    "a2_圧入力下限設定":           "圧入力下限設定_kN",
    "b1_圧入ストローク設定":       "圧入ストローク設定_mm",
    "b2_引抜ストローク設定":       "引抜ストローク設定_mm",
    "c1_機械前後傾斜制限設定":     "パイラー前後傾斜設定_0.1deg",
    "c2_機械左右傾斜制限設定":     "パイラー左右傾斜設定_0.1deg",
    "d4_チャック上スピード設定":   "チャック上スピード設定",
    "d5_チャック下スピード設定":   "チャック下スピード設定",
    "g1_オーガ正転トルク設定":     "正転トルク設定_kNm",
    "g2_オーガ正転トルク下限設定": "正転トルク下限設定_kNm",
    "g3_オーガ逆転トルク設定":     "逆転トルク設定_kNm",
    "g9_オーガ正転スピード設定":   "オーガ正転スピード設定_0.1rpm",
    "g10_オーガ逆転スピード設定":  "オーガ逆転スピード設定_0.1rpm",
    "h1_チャック正転トルク設定":   None,                                # バイナリに独立したトルク設定なし
    "h2_チャック正転トルク下限設定": None,                               # バイナリに無し
    "h3_チャック逆転トルク設定":   None,                                 # バイナリに無し
    "h7_チャック正転スピード設定": "チャック正転スピード設定_0.1rpm",
    "h8_チャック逆転スピード設定": "チャック逆転スピード設定_0.1rpm",
    "i1a_設定水量LS-A":            "LS水量_A_Lmin",
    "i1b_設定水量LS-B":            "LS水量_B_Lmin",
    "i1c_設定水量LS-C":            "LS水量_C_Lmin",
    "i1d_設定水量LS-D":            "LS水量_D_Lmin",
}

SETTING_PARAM_IDS = list(SETTING_COLUMNS_PILX.keys())

# ---------------------------------------------------------------------------
# 土質大分類 / N値ビン 定義
# ---------------------------------------------------------------------------

# 土質記号（大文字化後）→ 大分類
SYMBOL_TO_CATEGORY: dict[str, str] = {
    # 粘性土
    "C": "粘性土", "CL": "粘性土", "CH": "粘性土", "CI": "粘性土",
    "OL": "粘性土", "OH": "粘性土",
    # シルト質土
    "M": "シルト質土", "ML": "シルト質土", "MH": "シルト質土",
    "SM": "シルト質土",
    # 砂質土
    "S": "砂質土", "SF": "砂質土", "SW": "砂質土", "SP": "砂質土",
    "SC": "砂質土",
    # 礫質土
    "G": "礫質土", "GF": "礫質土", "GW": "礫質土", "GP": "礫質土",
    "GC": "礫質土", "GM": "礫質土", "GS": "礫質土",
    # 岩盤
    "WR": "岩盤", "MR": "岩盤", "HR": "岩盤", "R": "岩盤",
    # 埋土（記号から再分類できないためそのまま）
    "FI": "埋土",
}

# 土質名キーワード（記号が不明な場合の fallback）
KEYWORD_TO_CATEGORY: list[tuple[list[str], str]] = [
    (["岩", "軟岩", "硬岩", "中硬岩"], "岩盤"),
    (["礫", "砂礫", "玉石"], "礫質土"),
    (["粘土", "粘性土"], "粘性土"),
    (["シルト"], "シルト質土"),
    (["砂"], "砂質土"),
    (["埋土", "盛土"], "埋土"),
]

# N値ビン定義 (soil_category → [(下限, 上限, ラベル), ...])
# 上限は exclusive (< 上限)
N_VALUE_BINS: dict[str, list[tuple[float, float, str]]] = {
    "粘性土": [
        (0, 2, "N=0-2"), (2, 4, "N=2-4"), (4, 8, "N=4-8"),
        (8, 15, "N=8-15"), (15, float("inf"), "N≥15"),
    ],
    "シルト質土": [
        (0, 2, "N=0-2"), (2, 4, "N=2-4"), (4, 8, "N=4-8"),
        (8, 15, "N=8-15"), (15, float("inf"), "N≥15"),
    ],
    "砂質土": [
        (0, 4, "N=0-4"), (4, 10, "N=4-10"), (10, 30, "N=10-30"),
        (30, 50, "N=30-50"), (50, float("inf"), "N≥50"),
    ],
    "礫質土": [
        (0, 10, "N=0-10"), (10, 30, "N=10-30"), (30, 50, "N=30-50"),
        (50, float("inf"), "N≥50"),
    ],
    "岩盤": [
        (0, float("inf"), "N≥50"),
    ],
    "埋土": [
        (0, float("inf"), "N=0-50+"),
    ],
}

# N値拒否（99999）の代替値（打撃拒否時に使用する代替 N 値）
N_VALUE_WHEN_REFUSED = 60.0


# ---------------------------------------------------------------------------
# データモデル
# ---------------------------------------------------------------------------

@dataclass
class SoilLayer:
    """地層（柱状図から得られる1層分のデータ）"""
    depth_top_mm: float       # 上端深度 (mm)
    depth_bottom_mm: float    # 下端深度 (mm)
    soil_name: str            # 土質名
    soil_symbol: str          # 土質記号
    soil_category: str        # 大分類
    n_values: list[float] = field(default_factory=list)  # この層内のN値リスト
    avg_n_value: Optional[float] = None
    max_n_value: Optional[float] = None

    @property
    def n_value_bin(self) -> str:
        bins = N_VALUE_BINS.get(self.soil_category, N_VALUE_BINS["埋土"])
        n = self.avg_n_value if self.avg_n_value is not None else 0.0
        for lo, hi, label in bins:
            if lo <= n < hi:
                return label
        return bins[-1][2]


@dataclass
class BoreholeData:
    """柱状図データ（XML または PILX フッターから得られる）"""
    source_file: str
    borehole_id: str = ""
    depth_total_m: Optional[float] = None
    water_level_m: Optional[float] = None
    layers: list[SoilLayer] = field(default_factory=list)


@dataclass
class PressInRecord:
    """圧入管理データの1行（PILX または バイナリから正規化済み）"""
    depth_mm: float
    chuck_down: int          # チャック下フラグ (0/1)
    auto_mode: int           # 圧入自動フラグ (0/1)
    settings: dict[str, Optional[float]] = field(default_factory=dict)

    # 工法フラグ（解析用）
    method_flags: dict[str, int] = field(default_factory=dict)


@dataclass
class LayerRecord:
    """地層ごとの圧入設定値レコード（Level-1テーブルの1行）"""
    source_borehole: str
    source_press_in: str
    soil_name: str
    soil_symbol: str
    soil_category: str
    depth_top_mm: float
    depth_bottom_mm: float
    layer_thickness_mm: float
    avg_n_value: Optional[float]
    max_n_value: Optional[float]
    n_value_bin: str
    sample_rows: int
    method: str
    # 設定値（最頻値）
    a1_圧入力設定: Optional[float] = None
    a2_圧入力下限設定: Optional[float] = None
    b1_圧入ストローク設定: Optional[float] = None
    b2_引抜ストローク設定: Optional[float] = None
    c1_機械前後傾斜制限設定: Optional[float] = None
    c2_機械左右傾斜制限設定: Optional[float] = None
    d4_チャック上スピード設定: Optional[float] = None
    d5_チャック下スピード設定: Optional[float] = None
    g1_オーガ正転トルク設定: Optional[float] = None
    g2_オーガ正転トルク下限設定: Optional[float] = None
    g3_オーガ逆転トルク設定: Optional[float] = None
    g9_オーガ正転スピード設定: Optional[float] = None
    g10_オーガ逆転スピード設定: Optional[float] = None
    h1_チャック正転トルク設定: Optional[float] = None
    h2_チャック正転トルク下限設定: Optional[float] = None
    h3_チャック逆転トルク設定: Optional[float] = None
    h7_チャック正転スピード設定: Optional[float] = None
    h8_チャック逆転スピード設定: Optional[float] = None
    i1a_設定水量LS_A: Optional[float] = None
    i1b_設定水量LS_B: Optional[float] = None
    i1c_設定水量LS_C: Optional[float] = None
    i1d_設定水量LS_D: Optional[float] = None


# ---------------------------------------------------------------------------
# ユーティリティ
# ---------------------------------------------------------------------------

def classify_soil(symbol: str, name: str) -> str:
    """土質記号・土質名から大分類を返す"""
    sym = symbol.strip().upper() if symbol else ""
    if sym in SYMBOL_TO_CATEGORY:
        return SYMBOL_TO_CATEGORY[sym]
    # 記号でマッチしない場合はキーワード検索
    for keywords, category in KEYWORD_TO_CATEGORY:
        for kw in keywords:
            if kw in name:
                return category
    return "その他"


def assign_n_to_layers(layers: list[SoilLayer], spt_points: list[tuple[float, float]]) -> None:
    """N値測定点を地層に割り当て、avg/max を計算する"""
    for layer in layers:
        layer.n_values = []
        for depth_mm, n_val in spt_points:
            if layer.depth_top_mm <= depth_mm < layer.depth_bottom_mm:
                layer.n_values.append(n_val)
        if layer.n_values:
            layer.avg_n_value = sum(layer.n_values) / len(layer.n_values)
            layer.max_n_value = max(layer.n_values)


def safe_mode(values: list) -> Optional[float]:
    """最頻値を返す。空の場合は None"""
    cleaned = [v for v in values if v is not None]
    if not cleaned:
        return None
    # Python 3.8+ では multimode も使えるが、最初の最頻値を返す
    counts: dict = {}
    for v in cleaned:
        counts[v] = counts.get(v, 0) + 1
    return max(counts, key=lambda k: counts[k])


def safe_mean(values: list) -> Optional[float]:
    cleaned = [v for v in values if v is not None]
    if not cleaned:
        return None
    return sum(cleaned) / len(cleaned)


def confidence_level(n: int) -> str:
    if n >= 10:
        return "高"
    if n >= 3:
        return "中"
    return "低"


# ---------------------------------------------------------------------------
# 柱状図パーサ（XML）
# ---------------------------------------------------------------------------

# DTD バージョン → 地層情報要素名
SOIL_ELEMENT_MAP: dict[str, str] = {
    "1.02": "土質岩種区分", "1.10": "土質岩種区分",
    "2.00": "土質岩種区分", "2.01": "土質岩種区分", "2.10": "土質岩種区分",
    "3.00": "岩石土区分",
    "4.00": "工学的地質区分名現場土質名",
    "5.00": "工学的地質区分名現場土質名",
}

# DTD バージョン → SPT 開始深度要素名
SPT_DEPTH_ELEMENT_MAP: dict[str, str] = {
    # 全バージョン共通
    "DEFAULT": "標準貫入試験_開始深度",
}

# DTD バージョン → 総削孔長要素名
TOTAL_DEPTH_ELEMENT_MAP: dict[str, str] = {
    "1.02": "総掘進長", "1.10": "総掘進長", "2.00": "総掘進長",
    "2.01": "総掘進長", "2.10": "総掘進長", "3.00": "総掘進長",
    "4.00": "総削孔長", "5.00": "総削孔長",
}

# 貫入量の単位が mm になったバージョン（それ以前は cm）
MM_UNIT_VERSION = (4, 0)


def _version_tuple(ver: str) -> tuple[int, int]:
    parts = ver.split(".")
    major = int(parts[0]) if parts else 0
    minor = int(parts[1]) if len(parts) > 1 else 0
    return (major, minor)


def parse_borehole_xml(xml_path: Path) -> BoreholeData:
    """XML柱状図をパースして BoreholeData を返す（全DTDバージョン対応）"""
    # Shift_JIS で読み込み
    with open(xml_path, encoding="shift_jis", errors="replace") as f:
        content = f.read()

    # DTD 宣言を除去してパース（ElementTree は DOCTYPE に対応しないため）
    import re
    content_no_dtd = re.sub(r"<!DOCTYPE[^>]*>", "", content)
    root = ET.fromstring(content_no_dtd)

    dtd_version = root.get("DTD_version", "5.00")
    ver_tuple = _version_tuple(dtd_version)

    borehole_id = ""
    depth_total_m: Optional[float] = None
    water_level_m: Optional[float] = None

    # ボーリング基本情報
    total_depth_elem = TOTAL_DEPTH_ELEMENT_MAP.get(dtd_version, "総削孔長")
    for elem in root.iter():
        tag = elem.tag
        if tag in ("ボーリング基本情報",):
            for child in elem:
                if child.tag in ("総削孔長", "総掘進長") and child.text:
                    try:
                        depth_total_m = float(child.text.strip())
                    except ValueError:
                        pass
        if tag == "ボーリング名" and elem.text:
            borehole_id = elem.text.strip()

    # 孔内水位
    for elem in root.iter("孔内水位"):
        for child in elem:
            if child.tag == "孔内水位_孔内水位" and child.text:
                try:
                    water_level_m = float(child.text.strip())
                except ValueError:
                    pass
                break
        break

    # 地層情報要素名の決定
    soil_elem_name = SOIL_ELEMENT_MAP.get(dtd_version, "工学的地質区分名現場土質名")

    layers: list[SoilLayer] = []
    prev_bottom_mm = 0.0

    for soil_elem in root.iter(soil_elem_name):
        depth_bottom_m: Optional[float] = None
        soil_name = ""
        soil_symbol = ""

        for child in soil_elem:
            tag = child.tag
            text = (child.text or "").strip()
            # 下端深度（要素名はバージョンによって異なる可能性があるため末尾で判定）
            if tag.endswith("_下端深度") and text:
                try:
                    depth_bottom_m = float(text)
                except ValueError:
                    pass
            # 土質名
            elif (tag.endswith("_土質岩種名") or tag.endswith("_岩石土名")
                  or tag.endswith("_工学的地質区分名現場土質名")) and text:
                soil_name = text
            # 土質記号
            elif (tag.endswith("_土質岩種名記号") or tag.endswith("_岩石土名記号")
                  or tag.endswith("_工学的地質区分名現場土質名記号")) and text:
                soil_symbol = text

        if depth_bottom_m is None:
            continue

        depth_bottom_mm = depth_bottom_m * 1000.0
        layer = SoilLayer(
            depth_top_mm=prev_bottom_mm,
            depth_bottom_mm=depth_bottom_mm,
            soil_name=soil_name,
            soil_symbol=soil_symbol,
            soil_category=classify_soil(soil_symbol, soil_name),
        )
        layers.append(layer)
        prev_bottom_mm = depth_bottom_mm

    # SPT（標準貫入試験）N値
    spt_points: list[tuple[float, float]] = []
    for spt_elem in root.iter("標準貫入試験"):
        start_depth_m: Optional[float] = None
        total_hits: Optional[int] = None
        total_pen_raw: Optional[int] = None
        spt_remarks = ""

        for child in spt_elem:
            tag = child.tag
            text = (child.text or "").strip()
            if tag.endswith("_開始深度") and text:
                try:
                    start_depth_m = float(text)
                except ValueError:
                    pass
            elif tag.endswith("_合計打撃回数") and text:
                try:
                    total_hits = int(text)
                except ValueError:
                    pass
            elif tag.endswith("_合計貫入量") and text:
                try:
                    total_pen_raw = int(text)
                except ValueError:
                    pass
            elif tag.endswith("_備考") and text:
                spt_remarks = text

        if start_depth_m is None or total_hits is None:
            continue

        # 貫入量の単位正規化（v3.00以前は cm → mm 変換）
        total_pen_mm: Optional[int] = None
        if total_pen_raw is not None:
            if ver_tuple < MM_UNIT_VERSION:
                total_pen_mm = total_pen_raw * 10  # cm → mm
            else:
                total_pen_mm = total_pen_raw

        # N値計算
        if total_hits == 0 and "自沈" in spt_remarks:
            n_value = 0.0
        elif total_pen_mm is not None and total_pen_mm >= 300:
            n_value = float(total_hits)
        else:
            # 打撃拒否（300mm 未到達）
            n_value = N_VALUE_WHEN_REFUSED

        spt_points.append((start_depth_m * 1000.0, n_value))

    assign_n_to_layers(layers, spt_points)

    return BoreholeData(
        source_file=str(xml_path),
        borehole_id=borehole_id,
        depth_total_m=depth_total_m,
        water_level_m=water_level_m,
        layers=layers,
    )


# ---------------------------------------------------------------------------
# 柱状図パーサ（PILX フッター）
# ---------------------------------------------------------------------------

def parse_borehole_pilx_footer(footer_text: str, source_file: str) -> BoreholeData:
    """PILX フッターの [COLUMNAR START] セクションをパースして BoreholeData を返す"""
    layers: list[SoilLayer] = []
    spt_points: list[tuple[float, float]] = []
    water_level_m: Optional[float] = None

    lines = footer_text.splitlines()
    mode = None
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if line.startswith("//柱状図"):
            i += 1
            if i < len(lines):
                d1_line = lines[i].strip()
                if d1_line.startswith("D1,"):
                    num_layers = int(d1_line.split(",")[1])
                    i += 1
                    for _ in range(num_layers):
                        # 深度行: 上端(cm), 下端(cm), 0, 0, 0
                        depth_line = lines[i].strip().split(",")
                        i += 1
                        top_cm = float(depth_line[0])
                        bottom_cm = float(depth_line[1])
                        # 土質名行: K00,土質名
                        soil_name = ""
                        while i < len(lines):
                            k_line = lines[i].strip()
                            i += 1
                            if k_line.startswith("K00,"):
                                soil_name = k_line[4:]
                            elif k_line == "KEND":
                                break
                        # コメント行: C00, ... CEND
                        while i < len(lines):
                            c_line = lines[i].strip()
                            i += 1
                            if c_line == "CEND":
                                break
                        layer = SoilLayer(
                            depth_top_mm=top_cm * 10.0,   # cm → mm
                            depth_bottom_mm=bottom_cm * 10.0,
                            soil_name=soil_name,
                            soil_symbol="",
                            soil_category=classify_soil("", soil_name),
                        )
                        layers.append(layer)
                    continue
        elif line.startswith("//N値データ"):
            i += 1
            if i < len(lines):
                d2_line = lines[i].strip()
                if d2_line.startswith("D2,"):
                    num_pts = int(d2_line.split(",")[1])
                    i += 1
                    for _ in range(num_pts):
                        if i < len(lines):
                            parts = lines[i].strip().split(",")
                            i += 1
                            if len(parts) >= 2:
                                depth_cm = float(parts[0])
                                n_raw = float(parts[1])
                                if n_raw >= 999:
                                    n_val = N_VALUE_WHEN_REFUSED
                                else:
                                    n_val = n_raw
                                spt_points.append((depth_cm * 10.0, n_val))
                    continue
        elif line.startswith("//水位データ"):
            i += 1
            if i < len(lines):
                d3_line = lines[i].strip()
                if d3_line.startswith("D3,"):
                    num_pts = int(d3_line.split(",")[1])
                    i += 1
                    for _ in range(num_pts):
                        if i < len(lines):
                            parts = lines[i].strip().split(",")
                            i += 1
                            if len(parts) >= 1:
                                try:
                                    water_level_m = float(parts[0]) / 100.0
                                except ValueError:
                                    pass
                    continue
        i += 1

    assign_n_to_layers(layers, spt_points)

    return BoreholeData(
        source_file=source_file,
        layers=layers,
        water_level_m=water_level_m,
    )


# ---------------------------------------------------------------------------
# 圧入管理データパーサ（PILX）
# ---------------------------------------------------------------------------

def parse_press_in_pilx(pilx_path: Path) -> tuple[list[PressInRecord], BoreholeData]:
    """PILX ファイルをパースして (圧入レコードリスト, PILXフッター柱状図) を返す"""
    with open(pilx_path, encoding="utf-8", errors="replace") as f:
        content = f.read()

    # セクション分割
    itemlist_start = content.find("[ITEMLIST_START]")
    itemlist_end = content.find("[ITEMLIST_END]")
    graph_start = content.find("[GRAPH_START]")
    graph_end = content.find("[GRAPH_END]")
    columnar_start = content.find("[COLUMNAR START]")
    columnar_end = content.find("[COLUMNAR END]")

    # カラムヘッダー取得
    columns: list[str] = []
    if itemlist_start >= 0 and itemlist_end >= 0:
        itemlist_text = content[itemlist_start + len("[ITEMLIST_START]"):itemlist_end].strip()
        columns = [c.strip() for c in itemlist_text.split(",")]

    # データ部取得
    records: list[PressInRecord] = []
    if graph_start >= 0 and graph_end >= 0:
        data_text = content[graph_start + len("[GRAPH_START]"):graph_end]
        col_index: dict[str, int] = {name: idx for idx, name in enumerate(columns)}

        # 必要なカラムのインデックス
        depth_idx = col_index.get("深度", 1)
        chuck_down_idx = col_index.get("チャック下", 59)
        auto_idx = col_index.get("圧入自動", 76)

        for line in data_text.splitlines():
            line = line.strip()
            if not line or line.startswith("["):
                continue
            vals = line.split(",")
            if len(vals) < depth_idx + 1:
                continue
            try:
                depth_mm = float(vals[depth_idx])
            except (ValueError, IndexError):
                continue

            chuck_down = int(float(vals[chuck_down_idx])) if chuck_down_idx < len(vals) else 0
            auto_mode = int(float(vals[auto_idx])) if auto_idx < len(vals) else 0

            # 設定値抽出
            settings: dict[str, Optional[float]] = {}
            for param_id, col_name in SETTING_COLUMNS_PILX.items():
                idx = col_index.get(col_name)
                if idx is not None and idx < len(vals):
                    try:
                        settings[param_id] = float(vals[idx])
                    except (ValueError, IndexError):
                        settings[param_id] = None
                else:
                    settings[param_id] = None

            # 工法フラグ
            method_flags: dict[str, int] = {}
            for col_name in ["矢板単独", "矢板ジェット併用", "矢板オーガ併用", "コンビジャイロ",
                             "鋼管単独", "鋼管ジェット併用", "鋼管オーガ併用", "ジャイロ"]:
                idx = col_index.get(col_name)
                if idx is not None and idx < len(vals):
                    try:
                        method_flags[col_name] = int(float(vals[idx]))
                    except (ValueError, IndexError):
                        method_flags[col_name] = 0
                else:
                    method_flags[col_name] = 0

            records.append(PressInRecord(
                depth_mm=depth_mm,
                chuck_down=chuck_down,
                auto_mode=auto_mode,
                settings=settings,
                method_flags=method_flags,
            ))

    # フッター柱状図
    footer_borehole = BoreholeData(source_file=str(pilx_path))
    if columnar_start >= 0 and columnar_end >= 0:
        footer_text = content[columnar_start + len("[COLUMNAR START]"):columnar_end]
        footer_borehole = parse_borehole_pilx_footer(footer_text, str(pilx_path))

    return records, footer_borehole


# ---------------------------------------------------------------------------
# 圧入管理データパーサ（バイナリ）
# ---------------------------------------------------------------------------

def _u16(rec: bytes, offset: int) -> int:
    return (rec[offset] << 8) | rec[offset + 1]


def _s16_sign(rec: bytes, offset: int) -> int:
    raw = _u16(rec, offset)
    return -(raw & 0x7FFF) if (raw & 0x8000) else (raw & 0x7FFF)


def _u24(rec: bytes, offset: int) -> int:
    return (rec[offset] << 16) | (rec[offset + 1] << 8) | rec[offset + 2]


def _s24_sign(rec: bytes, offset: int) -> int:
    raw = _u24(rec, offset)
    return -(raw & 0x7FFFFF) if (raw & 0x800000) else (raw & 0x7FFFFF)


def _u32be(rec: bytes, offset: int) -> int:
    return struct.unpack_from(">I", rec, offset)[0]


def _parse_bin_record(rec: bytes) -> dict:
    """128 バイトの 1 レコードを解析して dict で返す（parse_bin.py 準拠）"""
    b2 = rec[2]  # BYTE 23: 状態フラグ
    b3 = rec[3]  # BYTE 24: 動作フラグ

    return {
        "チャック下":         (b3 >> 1) & 1,
        "圧入自動":           (b2 >> 2) & 1,
        "鋼矢板単独":         (rec[1] >> 0) & 1,
        "鋼矢板ジェット":     (rec[1] >> 1) & 1,
        "鋼矢板オーガ":       (rec[1] >> 2) & 1,
        "鋼管単独":           (rec[1] >> 4) & 1,
        "鋼管ジェット":       (rec[1] >> 5) & 1,
        "鋼管オーガ":         (rec[1] >> 6) & 1,
        # 設定値
        "圧入力設定_x10kN":            _u16(rec, 60),
        "圧入ストローク設定_mm":        _u16(rec, 62),
        "引抜ストローク設定_mm":        _u16(rec, 64),
        "正転トルク設定_kNm":           _u16(rec, 66),
        "逆転トルク設定_kNm":           _u16(rec, 68),
        "オーガ正転スピード設定_0.1rpm": _u16(rec, 70),
        "オーガ逆転スピード設定_0.1rpm": _u16(rec, 72),
        "チャック正転スピード設定_0.1rpm": _u16(rec, 74),
        "チャック逆転スピード設定_0.1rpm": _u16(rec, 76),
        "チャック上スピード設定":        rec[78],
        "チャック下スピード設定":        rec[79],
        "パイラー前後傾斜設定_0.1deg":  _s16_sign(rec, 84),
        "パイラー左右傾斜設定_0.1deg":  _s16_sign(rec, 86),
        "水量_Lmin":                    _u16(rec, 90),
        "圧入力下限設定_kN":            _u16(rec, 116),
        "正転トルク下限設定_kNm":       _u16(rec, 118),
        "LS水量_A_Lmin": rec[120],
        "LS水量_B_Lmin": rec[121],
        "LS水量_C_Lmin": rec[122],
        "LS水量_D_Lmin": rec[123],
        # 深度
        "貫入深度_mm": _s24_sign(rec, 100),
    }


def parse_press_in_binary(bin_path: Path) -> list[PressInRecord]:
    """バイナリファイルをパースして圧入レコードリストを返す"""
    HEADER_SIZE = 20
    FOOTER_SIZE = 30

    raw = bin_path.read_bytes()
    total = len(raw)
    data_size = total - HEADER_SIZE - FOOTER_SIZE

    # レコード長の自動検出
    # 192 バイト: 拡張フォーマット（例: SY75 NG ファイル）
    # 128 バイト: 標準フォーマット（余剰バイトは無視）
    if data_size % 192 == 0:
        record_size = 192
    else:
        record_size = 128

    num_records = data_size // record_size
    print(f"  バイナリ: {num_records} レコード (record_size={record_size}B)")

    records: list[PressInRecord] = []
    for i in range(num_records):
        offset = HEADER_SIZE + i * record_size
        rec_bytes = raw[offset: offset + 128]  # 常に先頭128バイトを使用
        if len(rec_bytes) < 128:
            break
        d = _parse_bin_record(rec_bytes)

        depth_mm = float(d["貫入深度_mm"])
        chuck_down = d["チャック下"]
        auto_mode = d["圧入自動"]

        settings: dict[str, Optional[float]] = {}
        for param_id, bin_key in SETTING_COLUMNS_BIN.items():
            if bin_key is None:
                settings[param_id] = None
            else:
                v = d.get(bin_key)
                settings[param_id] = float(v) if v is not None else None

        method_flags = {
            "鋼矢板単独": d.get("鋼矢板単独", 0),
            "鋼矢板ジェット": d.get("鋼矢板ジェット", 0),
            "鋼矢板オーガ": d.get("鋼矢板オーガ", 0),
            "鋼管単独": d.get("鋼管単独", 0),
            "鋼管ジェット": d.get("鋼管ジェット", 0),
            "鋼管オーガ": d.get("鋼管オーガ", 0),
        }

        records.append(PressInRecord(
            depth_mm=depth_mm,
            chuck_down=chuck_down,
            auto_mode=auto_mode,
            settings=settings,
            method_flags=method_flags,
        ))

    return records


# ---------------------------------------------------------------------------
# 深度アライメント & 設定値抽出
# ---------------------------------------------------------------------------

def determine_method(method_flags: dict[str, int]) -> str:
    """工法フラグから工法名を返す"""
    # PILX 形式
    if method_flags.get("コンビジャイロ"):
        return "コンビジャイロ"
    if method_flags.get("矢板オーガ併用") or method_flags.get("鋼矢板オーガ"):
        return "矢板オーガ併用"
    if method_flags.get("矢板ジェット併用") or method_flags.get("鋼矢板ジェット"):
        return "矢板ジェット併用"
    if method_flags.get("矢板単独") or method_flags.get("鋼矢板単独"):
        return "矢板単独"
    if method_flags.get("鋼管オーガ") or method_flags.get("鋼管オーガ併用"):
        return "鋼管オーガ併用"
    if method_flags.get("鋼管ジェット") or method_flags.get("鋼管ジェット併用"):
        return "鋼管ジェット併用"
    if method_flags.get("鋼管単独"):
        return "鋼管単独"
    if method_flags.get("ジャイロ"):
        return "ジャイロ"
    return "不明"


def align_and_extract(
    borehole: BoreholeData,
    press_in_records: list[PressInRecord],
    source_borehole: str,
    source_press_in: str,
    auto_only: bool = False,
) -> list[LayerRecord]:
    """地層と圧入データを深度でアライメントし、地層ごとの設定値を抽出する"""
    layer_records: list[LayerRecord] = []

    for layer in borehole.layers:
        # 地層区間のレコードを抽出
        segment = [
            r for r in press_in_records
            if layer.depth_top_mm <= r.depth_mm < layer.depth_bottom_mm
            and r.chuck_down == 1
        ]
        if auto_only:
            segment = [r for r in segment if r.auto_mode == 1]

        if len(segment) == 0:
            continue  # データなしの地層はスキップ

        # 工法（最頻値）
        all_method_flags: dict[str, list[int]] = {}
        for r in segment:
            for k, v in r.method_flags.items():
                all_method_flags.setdefault(k, []).append(v)
        dominant_flags = {k: (sum(v) > len(v) / 2) for k, v in all_method_flags.items()}
        method = determine_method({k: int(v) for k, v in dominant_flags.items()})

        # 設定値の最頻値
        settings_by_param: dict[str, list] = {p: [] for p in SETTING_PARAM_IDS}
        for r in segment:
            for param_id in SETTING_PARAM_IDS:
                v = r.settings.get(param_id)
                if v is not None:
                    settings_by_param[param_id].append(v)

        rec = LayerRecord(
            source_borehole=source_borehole,
            source_press_in=source_press_in,
            soil_name=layer.soil_name,
            soil_symbol=layer.soil_symbol,
            soil_category=layer.soil_category,
            depth_top_mm=layer.depth_top_mm,
            depth_bottom_mm=layer.depth_bottom_mm,
            layer_thickness_mm=layer.depth_bottom_mm - layer.depth_top_mm,
            avg_n_value=layer.avg_n_value,
            max_n_value=layer.max_n_value,
            n_value_bin=layer.n_value_bin,
            sample_rows=len(segment),
            method=method,
        )
        # 各設定値の最頻値をセット（フィールド名の "-" を "_" に変換済み）
        field_map = {
            "a1_圧入力設定":            "a1_圧入力設定",
            "a2_圧入力下限設定":        "a2_圧入力下限設定",
            "b1_圧入ストローク設定":    "b1_圧入ストローク設定",
            "b2_引抜ストローク設定":    "b2_引抜ストローク設定",
            "c1_機械前後傾斜制限設定":  "c1_機械前後傾斜制限設定",
            "c2_機械左右傾斜制限設定":  "c2_機械左右傾斜制限設定",
            "d4_チャック上スピード設定": "d4_チャック上スピード設定",
            "d5_チャック下スピード設定": "d5_チャック下スピード設定",
            "g1_オーガ正転トルク設定":  "g1_オーガ正転トルク設定",
            "g2_オーガ正転トルク下限設定": "g2_オーガ正転トルク下限設定",
            "g3_オーガ逆転トルク設定":  "g3_オーガ逆転トルク設定",
            "g9_オーガ正転スピード設定": "g9_オーガ正転スピード設定",
            "g10_オーガ逆転スピード設定": "g10_オーガ逆転スピード設定",
            "h1_チャック正転トルク設定": "h1_チャック正転トルク設定",
            "h2_チャック正転トルク下限設定": "h2_チャック正転トルク下限設定",
            "h3_チャック逆転トルク設定": "h3_チャック逆転トルク設定",
            "h7_チャック正転スピード設定": "h7_チャック正転スピード設定",
            "h8_チャック逆転スピード設定": "h8_チャック逆転スピード設定",
            "i1a_設定水量LS-A": "i1a_設定水量LS_A",
            "i1b_設定水量LS-B": "i1b_設定水量LS_B",
            "i1c_設定水量LS-C": "i1c_設定水量LS_C",
            "i1d_設定水量LS-D": "i1d_設定水量LS_D",
        }
        for param_id, attr_name in field_map.items():
            mode_val = safe_mode(settings_by_param[param_id])
            setattr(rec, attr_name, mode_val)

        layer_records.append(rec)

    return layer_records


# ---------------------------------------------------------------------------
# テーブル I/O
# ---------------------------------------------------------------------------

# LayerRecord の全フィールド名
LAYER_RECORD_FIELDS = [f.name for f in fields(LayerRecord)]


def load_layer_records(path: Path) -> list[dict]:
    """レベル1テーブルCSVを読み込む"""
    if not path.exists():
        return []
    rows = []
    with open(path, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)
    return rows


def save_layer_records(path: Path, records: list[LayerRecord], existing: list[dict]) -> None:
    """レベル1テーブルCSVに追記保存する"""
    path.parent.mkdir(parents=True, exist_ok=True)
    new_rows = [asdict(r) for r in records]

    all_rows = existing + new_rows
    if not all_rows:
        return

    all_fields = LAYER_RECORD_FIELDS
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=all_fields, extrasaction="ignore")
        writer.writeheader()
        for row in all_rows:
            writer.writerow(row)
    print(f"  レベル1テーブル更新: {path} ({len(all_rows)} 行)")


def build_setting_table(all_records: list[dict]) -> list[dict]:
    """レベル1テーブルからレベル2集約テーブルを生成する"""
    # グループ化
    groups: dict[tuple, list[dict]] = {}
    for row in all_records:
        key = (row.get("soil_category", ""), row.get("n_value_bin", ""))
        groups.setdefault(key, []).append(row)

    result = []
    for (cat, nbin), group_rows in sorted(groups.items()):
        entry: dict = {
            "soil_category": cat,
            "n_value_bin": nbin,
            "sample_count": len(group_rows),
            "confidence": confidence_level(len(group_rows)),
        }
        for param_id in SETTING_PARAM_IDS:
            attr = param_id.replace("-", "_")
            values = []
            for row in group_rows:
                v = row.get(attr)
                if v not in (None, "", "None"):
                    try:
                        values.append(float(v))
                    except (ValueError, TypeError):
                        pass
            entry[f"{attr}_recommended"] = safe_mode(values)
            entry[f"{attr}_mean"] = (
                round(safe_mean(values), 2) if safe_mean(values) is not None else None
            )
            entry[f"{attr}_min"] = min(values) if values else None
            entry[f"{attr}_max"] = max(values) if values else None
        result.append(entry)

    return result


def save_setting_table(path: Path, table: list[dict]) -> None:
    """レベル2集約テーブルをCSVに保存する"""
    if not table:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    all_keys: list[str] = []
    for row in table:
        for k in row:
            if k not in all_keys:
                all_keys.append(k)

    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=all_keys, extrasaction="ignore")
        writer.writeheader()
        for row in table:
            writer.writerow({k: (v if v is not None else "") for k, v in row.items()})
    print(f"  レベル2テーブル更新: {path} ({len(table)} 行)")


# ---------------------------------------------------------------------------
# メイン処理
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="柱状図と圧入管理データから地層ごとの圧入自動運転設定値テーブルを更新する",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--borehole", "-b",
        help="柱状図 XML ファイル（BED?????.XML）。省略時は PILX フッター柱状図を使用",
    )
    parser.add_argument(
        "--press-in", "-p", required=True,
        help="圧入管理データファイル（.pilx または .bin）",
    )
    parser.add_argument(
        "--records-table", "-r",
        default="data/table/layer_records.csv",
        help="レベル1テーブル CSV パス（デフォルト: data/table/layer_records.csv）",
    )
    parser.add_argument(
        "--setting-table", "-s",
        default="data/table/setting_table.csv",
        help="レベル2テーブル CSV パス（デフォルト: data/table/setting_table.csv）",
    )
    parser.add_argument(
        "--auto-only", action="store_true",
        help="自動運転中のデータのみを対象にする（デフォルト: 圧入中全行）",
    )

    args = parser.parse_args(argv)

    press_in_path = Path(args.press_in)
    if not press_in_path.exists():
        print(f"エラー: 圧入管理データファイルが見つかりません: {press_in_path}", file=sys.stderr)
        return 1

    records_table_path = Path(args.records_table)
    setting_table_path = Path(args.setting_table)

    # ------ 圧入管理データのパース ------
    suffix = press_in_path.suffix.lower()
    print(f"圧入管理データを読み込み中: {press_in_path.name}")

    press_in_records: list[PressInRecord]
    pilx_borehole: Optional[BoreholeData] = None

    if suffix == ".pilx":
        press_in_records, pilx_borehole = parse_press_in_pilx(press_in_path)
        print(f"  PILX: {len(press_in_records)} 行読み込み")
    elif suffix == ".bin":
        press_in_records = parse_press_in_binary(press_in_path)
    else:
        print(f"エラー: 未対応の圧入管理データ形式: {suffix}（.pilx または .bin のみ対応）",
              file=sys.stderr)
        return 1

    # ------ 柱状図のパース ------
    borehole: BoreholeData
    if args.borehole:
        borehole_path = Path(args.borehole)
        if not borehole_path.exists():
            print(f"エラー: 柱状図ファイルが見つかりません: {borehole_path}", file=sys.stderr)
            return 1
        print(f"柱状図を読み込み中: {borehole_path.name}")
        borehole = parse_borehole_xml(borehole_path)
        print(f"  XML: {len(borehole.layers)} 層, N値測定点数: "
              f"{sum(len(l.n_values) for l in borehole.layers)}")
    elif pilx_borehole is not None and pilx_borehole.layers:
        print("柱状図: PILX フッターを使用")
        borehole = pilx_borehole
        print(f"  PILX フッター: {len(borehole.layers)} 層")
    else:
        print("エラー: 柱状図データが得られませんでした。"
              "--borehole で XML ファイルを指定するか、PILX ファイルのフッターを確認してください",
              file=sys.stderr)
        return 1

    if not borehole.layers:
        print("警告: 柱状図に地層データが含まれていません", file=sys.stderr)
        return 0

    # ------ 深度アライメント & 設定値抽出 ------
    print("深度アライメントと設定値抽出を実行中...")
    layer_records = align_and_extract(
        borehole=borehole,
        press_in_records=press_in_records,
        source_borehole=str(args.borehole or "PILX_footer"),
        source_press_in=str(press_in_path),
        auto_only=args.auto_only,
    )

    if not layer_records:
        print("警告: 地層と圧入データのマッチングが取れませんでした。"
              "深度の単位やゼロ点を確認してください", file=sys.stderr)

    for lr in layer_records:
        n_str = f"{lr.avg_n_value:.1f}" if lr.avg_n_value is not None else "なし"
        print(f"  地層: {lr.soil_name} ({lr.soil_category}) "
              f"深度 {lr.depth_top_mm/1000:.2f}-{lr.depth_bottom_mm/1000:.2f}m "
              f"N={n_str} サンプル={lr.sample_rows}行")

    # ------ テーブル更新 ------
    print("テーブルを更新中...")
    existing_records = load_layer_records(records_table_path)
    save_layer_records(records_table_path, layer_records, existing_records)

    # レベル1全データからレベル2を再生成
    all_as_dicts = existing_records + [asdict(r) for r in layer_records]
    setting_table = build_setting_table(all_as_dicts)
    save_setting_table(setting_table_path, setting_table)

    print("完了")
    return 0


if __name__ == "__main__":
    sys.exit(main())
