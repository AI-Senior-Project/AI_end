"""
ชุดทดสอบ choose_mode()  รัน:  py test_mode.py

ประโยคในนี้ตั้งใจไม่ให้ซ้ำกับ FEW_SHOT ใน mode_router.py
ถ้าซ้ำ คะแนนจะดีเกินจริง (โมเดลแค่จำตัวอย่าง)
"""

from collections import Counter, defaultdict
from mode_router import choose_mode

RUNS = 3

CASES = [
    # --- bep ---
    ("B01", "ต้นทุนคงที่เดือนละ 20000 ขายแก้วละ 50 ต้นทุนแก้วละ 20 ต้องขายกี่แก้วถึงคุ้มทุน", "bep"),
    ("B02", "ร้านเปิดเดือนละ 26 วัน ต้นทุนคงที่ 30000 ต้องขายวันละกี่จานถึงจะไม่ขาดทุน", "bep"),  # แบบ C03
    ("B03", "ต้องขายได้เดือนละเท่าไหร่ถึงจะคืนทุน", "bep"),
    ("B04", "ต้องมีลูกค้าวันละกี่คนถึงจะพอจ่ายค่าเช่ากับค่าแรง", "bep"),

    # --- cashflow (มีคำชวนสับสนกับ bep) ---
    ("C01", "เดือนหน้าเงินสดจะพอจ่ายค่าเช่าไหม ตอนนี้มีเงินในบัญชี 40000 รายรับวันละ 3000", "cashflow"),
    ("C02", "อยากดูเงินเข้าออกแต่ละสัปดาห์ ว่าเงินจะช็อตช่วงไหน", "cashflow"),
    ("C03", "ต้นทุนคงที่เดือนละ 20000 เปิด 26 วัน เหลือเงิน 15000 อีก 3 เดือนเงินจะหมดไหม", "cashflow"),
    ("C04", "ลูกค้าจ่ายเครดิต 30 วัน แต่ต้องจ่ายซัพพลายเออร์เป็นเงินสด จะหมุนเงินทันไหม", "cashflow"),

    # --- profit ---
    ("P01", "เดือนนี้ขายได้ 120000 ต้นทุนรวม 85000 กำไรเท่าไหร่", "profit"),
    ("P02", "ร้านเปิด 26 วัน ขายได้วันละ 4000 ค่าใช้จ่ายทั้งเดือน 70000 เดือนนี้กำไรหรือขาดทุน", "profit"),
    ("P03", "ถ้าขึ้นราคาจานละ 5 บาท กำไรต่อเดือนจะเพิ่มขึ้นแค่ไหน", "profit"),

    # --- policy ---
    ("L01", "เปิดร้านอาหารต้องขอใบอนุญาตอะไรบ้าง", "policy"),
    ("L02", "รายได้เท่าไหร่ถึงต้องจด VAT", "policy"),
    ("L03", "ขายของออนไลน์ต้องจดทะเบียนพาณิชย์ไหม", "policy"),

    # --- startup_plan ---
    ("S01", "อยากเปิดร้านซักผ้า มีงบ 100000", "startup_plan"),
    ("S02", "อยากเปิดร้านอาหารตามสั่งแถวลาซาล มีงบ 50000 มีตู้เย็นแล้ว 1 เครื่อง", "startup_plan"),
    ("S03", "มีเงินเก็บสองแสน อยากทำธุรกิจเล็ก ๆ ควรเริ่มยังไง", "startup_plan"),

    # --- unclear ---
    ("U01", "สวัสดีครับ", "unclear"),
    ("U02", "วันนี้อากาศร้อนจัง", "unclear"),
]


def main():
    total = passed = 0
    failed = []
    confusion = defaultdict(Counter)  # confusion[ควรเป็น][ได้] = จำนวนครั้ง

    for case_id, text, want in CASES:
        results = []
        for _ in range(RUNS):
            try:
                got = choose_mode(text)
            except Exception as e:
                got = f"ERROR({type(e).__name__})"
            results.append(got)
            confusion[want][got] += 1
            total += 1
            passed += got == want

        n_ok = results.count(want)
        if n_ok == RUNS:
            print(f"[ผ่าน ] {case_id}  {text}")
        else:
            failed.append(case_id)
            wrong = ", ".join(f"{m}×{c}" for m, c in Counter(r for r in results if r != want).items())
            print(f"[ไม่ผ่าน] {case_id}  {text}")
            print(f"        ควรเป็น {want}  ผ่าน {n_ok}/{RUNS}  ได้ผิดเป็น: {wrong}\n")

    print("\n" + "=" * 50)
    print(f"ผ่าน {passed}/{total}")
    if failed:
        print("เคสที่ไม่ผ่าน:", ", ".join(failed))

    print("\nความแม่นรายโหมด:")
    for want, got_counts in confusion.items():
        ok = got_counts[want]
        n = sum(got_counts.values())
        mix = ", ".join(f"{m}×{c}" for m, c in got_counts.items() if m != want)
        print(f"  {want:<13} {ok}/{n}" + (f"   (หลุดไป: {mix})" if mix else ""))


if __name__ == "__main__":
    main()
