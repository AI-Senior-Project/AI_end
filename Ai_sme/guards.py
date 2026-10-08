"""
ด่านตรวจผลที่ AI ดึงมา ก่อนส่งให้ผู้ใช้ยืนยัน (Python ล้วน ไม่ใช้ AI)
"""

import re

# ตัวเลขที่ผู้ใช้บอกว่าเป็น "งบ/เงินทุน" (ไม่จับ "ทุนแก้วละ 20" ซึ่งเป็นต้นทุนต่อชิ้น)
BUDGET_RE = re.compile(
    r"(?:งบ(?:ลงทุน|ประมาณ)?|มีเงิน(?:เก็บ|ทุน)?|เงินทุน|ทุนเริ่มต้น)\s*(?:ประมาณ\s*)?(\d[\d,]*(?:\.\d+)?)"
)


def budget_amounts(text: str) -> set:
    return {float(m.replace(",", "")) for m in BUDGET_RE.findall(text)}


def drop_budget_as_fixed_cost(text: str, data: dict) -> dict:
    """งบลงทุนเป็นเงินก้อนตอนเริ่ม ไม่ใช่ค่าใช้จ่ายคงที่ต่อเดือน ถ้า AI ใส่มาให้ล้างทิ้ง"""
    if data.get("fixed_cost") is not None and data["fixed_cost"] in budget_amounts(text):
        data["fixed_cost"] = None
    return data


if __name__ == "__main__":
    checks = [
        ("อยากเปิดร้านงบ 50000 ต้องขายวันละกี่จานถึงคุ้มทุน", {"fixed_cost": 50000.0}, None),
        ("มีเงินเก็บ 200000 ค่าเช่า 8000", {"fixed_cost": 8000.0}, 8000.0),
        ("งบลงทุน 100,000 บาท", {"fixed_cost": 100000.0}, None),
        ("ค่าเช่า 9000 ทุนแก้วละ 20", {"fixed_cost": 9000.0}, 9000.0),
        ("ค่าเช่า 50000 งบ 50000", {"fixed_cost": 50000.0}, None),  # ชนกันพอดี → ล้างแล้วถามผู้ใช้เอง
    ]
    ok = 0
    for text, data, want in checks:
        got = drop_budget_as_fixed_cost(text, dict(data))["fixed_cost"]
        ok += got == want
        print(f"[{'ผ่าน' if got == want else 'ไม่ผ่าน'}] {text} -> fixed_cost={got}")
    print(f"ผ่าน {ok}/{len(checks)}")
