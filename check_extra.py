from pathlib import Path

raw = Path('data/samples/PIN_SY75_5001_20260415073053_NG.bin').read_bytes()

HEADER = 20
FOOTER = 30

# ---- 余分64バイトのユニーク種類 ----
extra_set = {}
for i in range(784):
    base = HEADER + i * 192
    extra = bytes(raw[base + 128 : base + 192])
    extra_set[extra] = extra_set.get(extra, 0) + 1

print(f'余分64バイトのユニーク種類: {len(extra_set)}')
for e, cnt in list(extra_set.items())[:3]:
    print(f'  ({cnt}件) ' + ' '.join(f'{b:02X}' for b in e))
print()

# ---- 余分64バイトの先頭8バイト（先頭10レコード） ----
print('余分64バイトの先頭8バイト（先頭10レコード）:')
for i in range(10):
    base = HEADER + i * 192
    extra = raw[base + 128 : base + 192]
    print(f'  rec{i}: ' + ' '.join(f'{b:02X}' for b in extra[:8]))
print()

# ---- SY67との比較 ----
raw67 = Path('data/samples/PIN_SY67_0023_20260406070524.bin').read_bytes()
r67_0 = raw67[20:148]
r75_extra0 = raw[20+128:20+192]

print('SY67 rec0の先頭64バイト:')
print(' '.join(f'{b:02X}' for b in r67_0[:64]))
print()
print('SY75 extra0の64バイト:')
print(' '.join(f'{b:02X}' for b in r75_extra0))
