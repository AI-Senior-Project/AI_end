import json
import ollama
from check_language import get_clean_reply
from thai_numbers import normalize_thai_numbers
from guards import drop_budget_as_fixed_cost

MODEL = "sme-thai"

EXTRACT_PROMPT = """ดึงตัวเลขจากข้อความ ตอบเป็น JSON เท่านั้น ค่าต้องเป็นตัวเลข ไม่ใส่เครื่องหมายคำพูด
key ที่ต้องมี:
- fixed_cost = ค่าใช้จ่ายคงที่ต่อเดือน เช่น ค่าเช่า ค่าแรง ค่าน้ำไฟ
- price = ราคาขายต่อชิ้น/จาน/แก้ว (คำว่า "ขาย...ละ")
- unit_cost = ต้นทุนวัตถุดิบต่อชิ้น/จาน/แก้ว (คำว่า "ต้นทุน...ละ")
ถ้าข้อความไม่ได้บอก ให้ใส่ null ห้ามเดา

ตัวอย่าง: "ค่าเช่า 8000 ขายจานละ 50 ต้นทุนจานละ 20"
ตอบ: {"fixed_cost": 8000, "price": 50, "unit_cost": 20}
ตัวอย่าง: "ค่าเช่า 5000 ขายแก้วละ 40"
ตอบ: {"fixed_cost": 5000, "price": 40, "unit_cost": null}"""

LABELS = {
    "fixed_cost": "ค่าใช้จ่ายคงที่ต่อเดือน",
    "price": "ราคาขายต่อชิ้น",
    "unit_cost": "ต้นทุนต่อชิ้น",
}



# 1) คุยทั่วไป: Python เรียก AI แล้วส่งคำตอบผ่านด่านตรวจ
def chat(user_msg: str) -> str:
    def generate():
        r = ollama.chat(model=MODEL, messages=[
            {"role": "user", "content": user_msg}
        ])
        return r["message"]["content"]
    return get_clean_reply(generate)


def to_number(v):
    if v is None:
        return None
    try:
        return float(str(v).replace(",", ""))
    except ValueError:
        return None


def extract_bep(user_msg: str) -> dict:
    user_msg = normalize_thai_numbers(user_msg)
    r = ollama.chat(model=MODEL, format="json", messages=[
        {"role": "system", "content": EXTRACT_PROMPT},
        {"role": "user", "content": user_msg},
    ])
    raw = json.loads(r["message"]["content"])
    data = {k: to_number(raw.get(k)) for k in LABELS}
    return drop_budget_as_fixed_cost(user_msg, data)


def calc_bep(d: dict):
    if None in (d.get("fixed_cost"), d.get("price"), d.get("unit_cost")):
        return None  # ข้อมูลไม่ครบ ต้องถามผู้ใช้เพิ่ม
    margin = d["price"] - d["unit_cost"]
    if margin <= 0:
        return None
    return d["fixed_cost"] / margin


if __name__ == "__main__":
    data = extract_bep(input("พิมพ์ข้อมูลร้าน: "))

    # ถามช่องที่ขาดก่อน ไม่ให้ไปถึงขั้นคำนวณแบบไม่ครบ
    for k, label in LABELS.items():
        while data[k] is None:
            data[k] = to_number(input(f"ยังไม่ทราบ{label} กรุณาระบุ (บาท): "))

    print("\nสรุปข้อมูลที่ระบบเข้าใจ:")
    for k, label in LABELS.items():
        print(f"  {label}: {data[k]:,.0f} บาท")

    ok = input("ถูกต้องไหม (y/n): ").strip().lower()
    if ok in ("y", "yes", "ั", "ใช่", "ช"):
        bep = calc_bep(data)
        if bep is None:
            print("ราคาขายต้องสูงกว่าต้นทุนต่อชิ้นถึงจะคำนวณจุดคุ้มทุนได้")
        else:
            print(f"ต้องขายเดือนละ {bep:,.0f} ชิ้นถึงจะคุ้มทุน")
    else:
        print("ยกเลิก ลองพิมพ์ข้อมูลใหม่อีกครั้งนะครับ")