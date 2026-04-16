"""
NGバイナリファイル診断スクリプト
経過時間の単調増加チェックにより、バイトずれ箇所を特定する
"""

from pathlib import Path

BIN_PATH = Path('data/samples/PIN_SY75_5001_20260415073053_NG.bin')
HEADER = 20
RECORD = 128
FOOTER = 30

# ユーティリティ
def u16(b, o): return (b[o] << 8) | b[o + 1]
def u24(b, o): return (b[o] << 16) | (b[o + 1] << 8) | b[o + 2]
def s24(b, o):
    v = u24(b, o)
    return -(v & 0x7FFFFF) if (v & 0x800000) else (v & 0x7FFFFF)

raw = BIN_PATH.read_bytes()
n = (len(raw) - HEADER - FOOTER) // RECORD

print(f"ファイルサイズ : {len(raw)} bytes")
print(f"総レコード数  : {n}")
print()

# --------------------------------------------------
# 1. 経過時間の単調増加チェック
# --------------------------------------------------
print("=== 経過時間 単調増加チェック ===")
prev_t = -1
anomalies = []
for i in range(n):
    base = HEADER + i * RECORD
    rec = raw[base:base + RECORD]
    t = u24(rec, 97)   # 経過時間 (×100ms)
    d = s24(rec, 100)  # 貫入深度 (mm)
    f = u16(rec, 26)   # 荷重 (×10kN)
    if prev_t >= 0:
        diff = t - prev_t
        if diff < 0 or diff > 500:  # 50秒以上のジャンプ or 負は異常
            anomalies.append((i, prev_t, t, diff, d, f))
    prev_t = t

if anomalies:
    print(f"異常レコード数: {len(anomalies)}")
    hdr = f"{'レコード':>8}  {'前t(x100ms)':>12}  {'現t(x100ms)':>12}  {'差分':>8}  {'貫入mm':>10}  {'荷重x10kN':>10}  file_offset"
    print(hdr)
    for rec_i, pt, ct, diff, d, f in anomalies[:30]:
        foff = HEADER + rec_i * RECORD
        print(f"{rec_i:>8}  {pt:>12}  {ct:>12}  {diff:>8}  {d:>10}  {f:>10}  {foff:#010x}")
else:
    print("異常なし（経過時間は単調増加）")

print()

# --------------------------------------------------
# 2. 異常箇所の前後バイトを詳細表示
# --------------------------------------------------
if anomalies:
    first_bad = anomalies[0][0]
    print(f"=== 最初の異常: レコード {first_bad} の前後バイト詳細 ===")
    for idx in range(max(0, first_bad - 2), min(n, first_bad + 3)):
        base = HEADER + idx * RECORD
        rec = raw[base:base + RECORD]
        t = u24(rec, 97)
        d = s24(rec, 100)
        marker = " <<< 異常" if idx == first_bad else ""
        print(f"  レコード {idx:5d}  (offset {base:#010x})  経過時間={t:7d}  貫入深度={d:7d}mm{marker}")
        # 当該レコードのバイト列（16進）
        if idx in (first_bad - 1, first_bad):
            hex_str = " ".join(f"{b:02X}" for b in rec)
            print(f"           hex: {hex_str}")

print()

# --------------------------------------------------
# 3. 最初・中間・最後のレコードサマリ
# --------------------------------------------------
print("=== レコードサマリ（先頭・1/4・1/2・3/4・末尾） ===")
targets = [0, n//4, n//2, 3*n//4, n-1]
for idx in targets:
    base = HEADER + idx * RECORD
    rec = raw[base:base + RECORD]
    t = u24(rec, 97)
    d = s24(rec, 100)
    f = u16(rec, 26)
    print(f"  レコード {idx:5d}  経過時間={t:7d}x100ms  貫入深度={d:7d}mm  荷重={f:5d}x10kN")
