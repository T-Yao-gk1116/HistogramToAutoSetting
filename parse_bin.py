"""
PIN バイナリファイル → CSV 変換スクリプト
仕様: 20230406_G-Labox_データ管理仕様.csv に基づく

ファイル構成:
  ヘッダー部 :  20 バイト（BYTE  1- 20: 機種名・号機・記録時刻）
  データ部   : 128 バイト × N レコード（BYTE 21-148 が 1 レコード分）
  フッター部 :  30 バイト（GPS 測位データ）
"""

import struct
import csv
from pathlib import Path

HEADER_SIZE = 20    # ヘッダー部固定長
RECORD_SIZE = 128   # 1 レコードのバイト数（BYTE 21-148 = 128 バイト）
FOOTER_SIZE = 30    # フッター部固定長（GPS ASCII）


HEADER_SIZE = 20    # ヘッダー部固定長
RECORD_SIZE = 128   # 1 レコードのバイト数（BYTE 21-148 = 128 バイト）
FOOTER_SIZE = 30    # フッター部固定長（GPS ASCII）


# ---------------------------------------------------------------------------
# ユーティリティ
# ---------------------------------------------------------------------------

def u16(rec: bytes, offset: int) -> int:
    """ビッグエンディアン 16bit 符号なし（offset は 0-indexed）"""
    return (rec[offset] << 8) | rec[offset + 1]


def s16_sign(rec: bytes, offset: int) -> int:
    """bit15 が符号ビット、残り 15bit が値"""
    raw = u16(rec, offset)
    return -(raw & 0x7FFF) if (raw & 0x8000) else (raw & 0x7FFF)


def u24(rec: bytes, offset: int) -> int:
    """3 バイト符号なし整数（ビッグエンディアン）"""
    return (rec[offset] << 16) | (rec[offset + 1] << 8) | rec[offset + 2]


def s24_sign(rec: bytes, offset: int) -> int:
    """bit23 が符号ビット、残り 23bit が値"""
    raw = u24(rec, offset)
    return -(raw & 0x7FFFFF) if (raw & 0x800000) else (raw & 0x7FFFFF)


def u32be(rec: bytes, offset: int) -> int:
    return struct.unpack_from('>I', rec, offset)[0]


def ascii_str(data: bytes, offset: int, length: int) -> str:
    return data[offset:offset + length].decode('ascii', errors='replace').strip('\x00').strip()


# ---------------------------------------------------------------------------
# ヘッダー部（BYTE 1-20 = data[0:20]）
# ---------------------------------------------------------------------------

def parse_header(data: bytes) -> dict:
    """20 バイトのヘッダーを解析する"""
    return {
        '機種名':  ascii_str(data, 0, 10),   # BYTE 1-10
        '号機':    ascii_str(data, 10, 4),    # BYTE 11-14
        '年':      2000 + data[14],           # BYTE 15
        '月':      data[15],                  # BYTE 16
        '日':      data[16],                  # BYTE 17
        '時':      data[17],                  # BYTE 18
        '分':      data[18],                  # BYTE 19
        '秒':      data[19],                  # BYTE 20
    }


# ---------------------------------------------------------------------------
# データ部（1 レコード = 128 バイト、BYTE 21-148 に対応）
# rec[i] は BYTE (21+i) に対応（0-indexed）
# ---------------------------------------------------------------------------

def parse_record(rec: bytes) -> dict:
    """128 バイトの 1 レコードを解析して dict で返す"""

    # --- パイラーフラグ（BYTE 21-27 → rec[0-6]） ---
    b0 = rec[0]  # BYTE 21: パイラー状態フラグ
    b1 = rec[1]  # BYTE 22: 工法フラグ
    b2 = rec[2]  # BYTE 23: 状態フラグ
    b3 = rec[3]  # BYTE 24: 動作フラグ
    b4 = rec[4]  # BYTE 25: オーガフラグ

    row = {
        # BYTE 21: 安全フラグ
        'クランプ安全':         (b0 >> 0) & 1,
        'チャック安全':          (b0 >> 1) & 1,
        'ケーシング安全':        (b0 >> 2) & 1,
        'ケーシングロック安全':  (b0 >> 3) & 1,
        'チャック回転ロック安全': (b0 >> 4) & 1,
        'マスト旋回ロック安全':  (b0 >> 6) & 1,
        # BYTE 22: 工法フラグ
        '鋼矢板単独':      (b1 >> 0) & 1,
        '鋼矢板ジェット':  (b1 >> 1) & 1,
        '鋼矢板オーガ':    (b1 >> 2) & 1,
        '鋼管単独':        (b1 >> 4) & 1,
        '鋼管ジェット':    (b1 >> 5) & 1,
        '鋼管オーガ':      (b1 >> 6) & 1,
        '鋼管回転圧入':    (b1 >> 7) & 1,
        # BYTE 23: 状態フラグ
        'ITボタン':   (b2 >> 0) & 1,
        '設定中':     (b2 >> 1) & 1,
        '圧入自動':   (b2 >> 2) & 1,
        '引抜自動':   (b2 >> 3) & 1,
        'エラー表示': (b2 >> 4) & 1,
        # BYTE 24: 動作フラグ
        'チャック上':  (b3 >> 0) & 1,
        'チャック下':  (b3 >> 1) & 1,
        'オーガ正転':  (b3 >> 2) & 1,
        'オーガ逆転':  (b3 >> 3) & 1,
        'チャック正転': (b3 >> 4) & 1,
        'チャック逆転': (b3 >> 5) & 1,
        'ケーシング上': (b3 >> 6) & 1,
        'ケーシング下': (b3 >> 7) & 1,
        # BYTE 25: オーガフラグ
        'オーガ上': (b4 >> 6) & 1,
        'オーガ下': (b4 >> 7) & 1,
        # BYTE 26-27: モード
        '表示モード': rec[5] & 0x03,   # 0:グラフ 1:現在値 2:設定値
        '運転モード': rec[6] & 0x03,   # 0:手動 1:圧入自動 2:引抜自動
        # BYTE 28-30: インプラントNAVI
        'NAVI計測指定':  (rec[7] >> 0) & 1,
        'NAVI上部計測':  (rec[7] >> 1) & 1,
        'NAVI下部計測':  (rec[7] >> 2) & 1,
        'NAVIプリズム':  (rec[7] >> 3) & 1,
        'NAVI打下装置':  (rec[7] >> 4) & 1,
        'NAVI制御ID':    rec[9],        # BYTE 30 → rec[9]
    }

    # --- パイラーエラー（BYTE 31-38 = rec[10:18]、ERR1-ERR64） ---
    for i in range(8):
        eb = rec[10 + i]
        for bit in range(8):
            row[f'パイラーERR{i*8+bit+1}'] = (eb >> bit) & 1

    # --- ユニットエラー（BYTE 39-46 = rec[18:26]、ERR1-ERR64） ---
    for i in range(8):
        eb = rec[18 + i]
        for bit in range(8):
            row[f'ユニットERR{i*8+bit+1}'] = (eb >> bit) & 1

    # --- 計測値（BYTE 47-80 = rec[26:60]） ---
    row['荷重_x10kN']              = u16(rec, 26)   # BYTE 47-48
    row['オーガトルク_kNm']         = u16(rec, 28)   # BYTE 49-50
    row['チャックトルク_kNm']        = u16(rec, 30)   # BYTE 51-52
    row['オーガ推力_x10kN']         = u16(rec, 32)   # BYTE 53-54
    row['ケーシング推力_x10kN']      = u16(rec, 34)   # BYTE 55-56
    row['オーガストローク_mm']        = u16(rec, 36)   # BYTE 57-58
    row['ケーシングストローク_mm']     = u16(rec, 38)   # BYTE 59-60
    row['チャック上下スピード_0.1mmin'] = u16(rec, 40)  # BYTE 61-62
    row['オーガ上下スピード_0.1mmin']   = u16(rec, 42)  # BYTE 63-64
    row['ケーシング上下スピード_0.1mmin'] = u16(rec, 44) # BYTE 65-66
    row['オーガ回転スピード_0.1rpm']    = u16(rec, 46)  # BYTE 67-68
    row['チャック回転スピード_0.1rpm']   = u16(rec, 48)  # BYTE 69-70
    row['パイラー傾斜X_0.1deg']        = s16_sign(rec, 50)  # BYTE 71-72
    row['パイラー傾斜Y_0.1deg']        = s16_sign(rec, 52)  # BYTE 73-74
    row['杭傾斜X_0.1deg']             = s16_sign(rec, 54)  # BYTE 75-76
    row['杭傾斜Y_0.1deg']             = s16_sign(rec, 56)  # BYTE 77-78
    row['馬力_PS']                    = u16(rec, 58)   # BYTE 79-80

    # --- 設定値（BYTE 81-114 = rec[60:94]） ---
    row['圧入力設定_x10kN']            = u16(rec, 60)   # BYTE 81-82
    row['圧入ストローク設定_mm']         = u16(rec, 62)   # BYTE 83-84
    row['引抜ストローク設定_mm']         = u16(rec, 64)   # BYTE 85-86
    row['正転トルク設定_kNm']           = u16(rec, 66)   # BYTE 87-88
    row['逆転トルク設定_kNm']           = u16(rec, 68)   # BYTE 89-90
    row['オーガ正転スピード設定_0.1rpm']  = u16(rec, 70)  # BYTE 91-92
    row['オーガ逆転スピード設定_0.1rpm']  = u16(rec, 72)  # BYTE 93-94
    row['チャック正転スピード設定_0.1rpm'] = u16(rec, 74) # BYTE 95-96
    row['チャック逆転スピード設定_0.1rpm'] = u16(rec, 76) # BYTE 97-98
    row['チャック上スピード設定']         = rec[78]       # BYTE 99
    row['チャック下スピード設定']         = rec[79]       # BYTE 100
    row['オーガ上スピード設定']           = rec[80]       # BYTE 101
    row['オーガ下スピード設定']           = rec[81]       # BYTE 102
    row['ケーシング上スピード設定']        = rec[82]       # BYTE 103
    row['ケーシング下スピード設定']        = rec[83]       # BYTE 104
    row['パイラー前後傾斜設定_0.1deg']    = s16_sign(rec, 84)  # BYTE 105-106
    row['パイラー左右傾斜設定_0.1deg']    = s16_sign(rec, 86)  # BYTE 107-108
    row['チャック掴み力設定']             = rec[88]       # BYTE 109
    row['クランプ掴み力設定']             = rec[89]       # BYTE 110
    row['水量_Lmin']                    = u16(rec, 90)   # BYTE 111-112
    row['水圧_0.1MPa']                  = u16(rec, 92)   # BYTE 113-114

    # --- モード（BYTE 115-117 = rec[94:97]） ---
    row['手動モード']    = rec[94]   # BYTE 115
    row['圧入自動モード'] = rec[95]   # BYTE 116
    row['引抜自動モード'] = rec[96]   # BYTE 117

    # --- 時刻・位置（BYTE 118-128 = rec[97:108]） ---
    row['経過時間_x100ms'] = u24(rec, 97)        # BYTE 118-120
    row['貫入深度_mm']      = s24_sign(rec, 100)  # BYTE 121-123
    row['管内土距離_mm']    = u24(rec, 103)       # BYTE 124-126
    row['杭変位1_mm']       = u16(rec, 106)       # BYTE 127-128

    # --- 変位・消費（BYTE 129-136 = rec[108:116]） ---
    row['杭変位2_mm']    = u16(rec, 108)    # BYTE 129-130
    row['杭変位3_mm']    = u16(rec, 110)    # BYTE 131-132
    row['燃料消費量_L']  = u32be(rec, 112)  # BYTE 133-136

    # --- 下限設定（BYTE 137-140 = rec[116:120]） ---
    row['圧入力下限設定_kN']     = u16(rec, 116)  # BYTE 137-138
    row['正転トルク下限設定_kNm'] = u16(rec, 118)  # BYTE 139-140

    # --- LS 個別水量（BYTE 141-146 = rec[120:126]） ---
    for i, label in enumerate(['A', 'B', 'C', 'D', 'E', 'F']):
        row[f'LS水量_{label}_Lmin'] = rec[120 + i]  # BYTE 141-146

    # --- 予備（BYTE 147-148 = rec[126:128]） ---
    row['予備1'] = rec[126]
    row['予備2'] = rec[127]

    return row


# ---------------------------------------------------------------------------
# フッター部（末尾 30 バイト = GPS ASCII データ）
# ---------------------------------------------------------------------------

def parse_footer(data: bytes) -> dict:
    """末尾 30 バイトの GPS データを解析する"""
    foot = data[-FOOTER_SIZE:]
    return {
        'GPS測位時刻': ascii_str(foot, 0, 6),   # n-30 ～ n-25: hhmmss
        'GPS緯度':     ascii_str(foot, 6, 10),  # n-24 ～ n-15: ddmm.mmmmN
        'GPS経度':     ascii_str(foot, 16, 11), # n-14 ～ n-4 : dddmm.mmmmE
        'GPS測位状態': ascii_str(foot, 27, 1),  # n-3         : 0/1/2
        'GPS衛星数':   ascii_str(foot, 28, 2),  # n-2 ～ n-1  : 2桁
    }


# ---------------------------------------------------------------------------
# メイン変換処理
# ---------------------------------------------------------------------------

def convert(bin_path: Path, out_dir: Path) -> None:
    raw = bin_path.read_bytes()
    total = len(raw)
    data_size = total - HEADER_SIZE - FOOTER_SIZE
    num_records = data_size // RECORD_SIZE
    remainder = data_size % RECORD_SIZE

    print(f"ファイルサイズ : {total} bytes")
    print(f"ヘッダー部    : {HEADER_SIZE} bytes")
    print(f"データ部      : {data_size} bytes → {num_records} レコード (残余 {remainder} bytes)")
    print(f"フッター部     : {FOOTER_SIZE} bytes")

    header = parse_header(raw[:HEADER_SIZE])
    footer = parse_footer(raw)

    # --- ヘッダー CSV ---
    header_csv = out_dir / (bin_path.stem + '_header.csv')
    with open(header_csv, 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.writer(f)
        w.writerow(['項目', '値'])
        for k, v in header.items():
            w.writerow([k, v])
        w.writerow(['--- GPS ---', ''])
        for k, v in footer.items():
            w.writerow([k, v])
    print(f"ヘッダー CSV  : {header_csv}")

    # --- データ CSV ---
    data_csv = out_dir / (bin_path.stem + '_data.csv')
    records = []
    for i in range(num_records):
        offset = HEADER_SIZE + i * RECORD_SIZE
        rec_bytes = raw[offset:offset + RECORD_SIZE]
        row = parse_record(rec_bytes)
        row['レコード番号'] = i + 1
        records.append(row)

    if records:
        fieldnames = ['レコード番号'] + [k for k in records[0] if k != 'レコード番号']
        with open(data_csv, 'w', newline='', encoding='utf-8-sig') as f:
            w = csv.DictWriter(f, fieldnames=fieldnames)
            w.writeheader()
            w.writerows(records)
        print(f"データ CSV    : {data_csv} ({len(records)} レコード)")


if __name__ == '__main__':
    base = Path(__file__).parent
    bin_path = base / 'data/samples/PIN_SY75_5001_20260416065715.bin'
    convert(bin_path, bin_path.parent)

