"""
ชุดทดสอบการดึงตัวเลขของ extract_bep()
วางไฟล์นี้ไว้โฟลเดอร์เดียวกับ main.py แล้วรัน:  py test_extract.py

แต่ละเคส = (รหัส, ประโยคที่ผู้ใช้พิมพ์, คำตอบที่ถูก)
None = ข้อความไม่ได้บอก AI ต้องตอบ null ห้ามเดา
"""

from main import extract_bep

# รันแต่ละเคสกี่รอบ (temperature ไม่ใช่ 0 คำตอบอาจไม่เหมือนเดิมทุกรอบ)
# ตั้ง 3 ขึ้นไปถ้าอยากเช็คว่าผลนิ่งไหม
RUNS = 3

CASES = [
    # --- เคสพื้นฐาน ---
    ("T01", "ค่าเช่า 8000 ขายจานละ 50 ต้นทุนจานละ 20",
     {"fixed_cost": 8000, "price": 50, "unit_cost": 20}),
    ("T02", "ค่าเช่าเดือนละ 15000 ขายแก้วละ 45",
     {"fixed_cost": 15000, "price": 45, "unit_cost": None}),
    ("T03", "ขายแก้วละ 40 ต้นทุนแก้วละ 15",
     {"fixed_cost": None, "price": 40, "unit_cost": 15}),

    # --- ตัวเลขเป็นคำไทย / มีหน่วย ---
    ("T04", "ค่าเช่าหมื่นห้า ขายแก้วละ 45 ทุนแก้วละ 20",
     {"fixed_cost": 15000, "price": 45, "unit_cost": 20}),
    ("T05", "ค่าเช่า 1.5 หมื่น ขายชิ้นละ 30 ต้นทุนชิ้นละ 12",
     {"fixed_cost": 15000, "price": 30, "unit_cost": 12}),
    ("T06", "ค่าเช่า 12,000 บาท ขายกล่องละ 55 ต้นทุนกล่องละ 25",
     {"fixed_cost": 12000, "price": 55, "unit_cost": 25}),

    # --- คำย่อ / สลับลำดับ ---
    ("T07", "ขาย 45 ทุน 20 ค่าเช่า 9000",
     {"fixed_cost": 9000, "price": 45, "unit_cost": 20}),

    # --- ค่าใช้จ่ายหลายตัวต้องรวมกัน ---
    ("T08", "ค่าเช่า 8000 ค่าไฟ 2000 ขายจานละ 60 ต้นทุนจานละ 30",
     {"fixed_cost": 10000, "price": 60, "unit_cost": 30}),

    # --- หน่วยเวลาไม่ใช่ต่อเดือน: ต้องไม่เดาจำนวนวันเอง ---
    ("T09", "ค่าแรงวันละ 400 ขายจานละ 50 ต้นทุนจานละ 20",
     {"fixed_cost": None, "price": 50, "unit_cost": 20}),

    # --- มีตัวเลขหลอก (จำนวนลูกค้า / งบ) ที่ไม่ควรถูกดึง ---
    ("T10", "ร้านกาแฟ ค่าเช่า 7000 ขายแก้วละ 35 ต้นทุน 12 บาท ลูกค้าวันละ 80 คน",
     {"fixed_cost": 7000, "price": 35, "unit_cost": 12}),
    ("T11", "อยากเปิดร้านอาหาร มีงบ 50000",
     {"fixed_cost": None, "price": None, "unit_cost": None}),
]


def same(got, want) -> bool:
    if want is None:
        return got is None
    return got is not None and abs(got - want) < 0.01


def fmt(v):
    return "null" if v is None else f"{v:,.0f}"


def main():
    total = 0
    passed = 0
    failed_ids = []

    for case_id, text, expected in CASES:
        for run in range(1, RUNS + 1):
            total += 1
            tag = case_id if RUNS == 1 else f"{case_id}#{run}"
            try:
                got = extract_bep(text)
            except Exception as e:
                print(f"[ERROR] {tag}  {text}\n        {type(e).__name__}: {e}\n")
                failed_ids.append(tag)
                continue

            wrong = [k for k in expected if not same(got.get(k), expected[k])]
            if not wrong:
                passed += 1
                print(f"[ผ่าน ] {tag}  {text}")
            else:
                failed_ids.append(tag)
                print(f"[ไม่ผ่าน] {tag}  {text}")
                for k in wrong:
                    print(f"        {k}: ได้ {fmt(got.get(k))}  ควรเป็น {fmt(expected[k])}")
                print()

    print("\n" + "=" * 50)
    print(f"ผ่าน {passed}/{total}")
    if failed_ids:
        print("ไม่ผ่าน:", ", ".join(failed_ids))


if __name__ == "__main__":
    main()
