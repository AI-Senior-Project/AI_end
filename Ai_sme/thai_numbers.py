"""
แปลงตัวเลขที่เขียนเป็นคำไทยให้เป็นตัวเลขอารบิก ก่อนส่งข้อความเข้า AI

รองรับ:
  หมื่นห้า        -> 15000   (ภาษาพูด: หลักถัดไปหายไป)
  สองหมื่นห้า     -> 25000
  พันห้า          -> 1500
  แสนสอง         -> 120000
  สามพันห้าร้อย   -> 3500
  สิบห้า / ยี่สิบเอ็ด -> 15 / 21
  1.5 หมื่น / 2 แสน / 3 พัน -> 15000 / 200000 / 3000
"""

import re

DIGITS = {
    "หนึ่ง": 1, "เอ็ด": 1, "สอง": 2, "ยี่": 2, "สาม": 3, "สี่": 4,
    "ห้า": 5, "หก": 6, "เจ็ด": 7, "แปด": 8, "เก้า": 9,
}
UNITS = {
    "สิบ": 10, "ร้อย": 100, "พัน": 1000,
    "หมื่น": 10000, "แสน": 100000, "ล้าน": 1000000,
}

# เรียงคำยาวก่อน กันไม่ให้ "ห้า" ไปจับก่อนคำอื่น
_TOKENS = sorted(list(DIGITS) + list(UNITS), key=len, reverse=True)
_TOKEN_RE = "|".join(_TOKENS)
_RUN_RE = re.compile(f"(?:{_TOKEN_RE})+")
_SPLIT_RE = re.compile(_TOKEN_RE)

# ตัวเลข + หน่วย เช่น "1.5 หมื่น" (ไม่รวม "ร้อย" กันชนกับ "ร้อยละ")
_NUM_UNIT_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(หมื่น|แสน|พัน|ล้าน)")


def _parse_words(run: str):
    tokens = _SPLIT_RE.findall(run)

    # ต้องมีหน่วยอย่างน้อย 1 ตัว และไม่ใช่หน่วยเดี่ยว ๆ
    # กันคำอย่าง "พันธมิตร" "แสนดี" "ร้อยละ" "ห้าง" โดนแปลงผิด
    if not any(t in UNITS for t in tokens):
        return None
    if len(tokens) == 1:
        return None

    total = 0
    digit = None
    last_unit = None
    for t in tokens:
        if t in DIGITS:
            digit = DIGITS[t]
        else:
            unit = UNITS[t]
            total += (digit if digit is not None else 1) * unit
            digit = None
            last_unit = unit

    # ตัวเลขท้ายสุดที่ไม่มีหน่วยตาม = ภาษาพูด ใช้หน่วยถัดลงไป
    # หมื่นห้า -> 5 x 1000, สิบห้า -> 5 x 1
    if digit is not None:
        total += digit * (last_unit // 10 if last_unit else 1)

    return total


def normalize_thai_numbers(text: str) -> str:
    def num_unit(m):
        value = float(m.group(1)) * UNITS[m.group(2)]
        return str(int(value)) if value.is_integer() else str(value)

    text = _NUM_UNIT_RE.sub(num_unit, text)

    def words(m):
        value = _parse_words(m.group(0))
        return m.group(0) if value is None else str(value)

    return _RUN_RE.sub(words, text)


if __name__ == "__main__":
    checks = [
        ("ค่าเช่าหมื่นห้า", "ค่าเช่า15000"),
        ("ค่าเช่าสองหมื่นห้า", "ค่าเช่า25000"),
        ("ค่าเช่าสองหมื่นห้าพัน", "ค่าเช่า25000"),
        ("ค่าแรงพันห้า", "ค่าแรง1500"),
        ("ลงทุนแสนสอง", "ลงทุน120000"),
        ("ค่าไฟสามพันห้าร้อย", "ค่าไฟ3500"),
        ("ขายสิบห้าบาท", "ขาย15บาท"),
        ("ยี่สิบเอ็ดวัน", "21วัน"),
        ("ค่าเช่า 1.5 หมื่น", "ค่าเช่า 15000"),
        ("งบ 2 แสน", "งบ 200000"),
        # ต้องไม่โดนแปลง
        ("หาพันธมิตร", "หาพันธมิตร"),
        ("กำไรร้อยละ 20", "กำไรร้อยละ 20"),
        ("เจ้าของแสนดี", "เจ้าของแสนดี"),
        ("เปิดร้านในห้าง", "เปิดร้านในห้าง"),
        ("ค่าเช่า 8000 ขายจานละ 50", "ค่าเช่า 8000 ขายจานละ 50"),
    ]
    ok = 0
    for src, want in checks:
        got = normalize_thai_numbers(src)
        mark = "ผ่าน" if got == want else "ไม่ผ่าน"
        ok += got == want
        print(f"[{mark}] {src!r} -> {got!r}" + ("" if got == want else f"  (ควรเป็น {want!r})"))
    print(f"\nผ่าน {ok}/{len(checks)}")