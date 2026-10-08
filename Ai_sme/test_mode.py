"""
ชุดทดสอบ choose_mode()  รัน:  py test_mode.py

ประโยคในนี้ตั้งใจไม่ให้ซ้ำกับ FEW_SHOT ใน mode_router.py
ถ้าซ้ำ คะแนนจะดีเกินจริง (โมเดลแค่จำตัวอย่าง)
"""

from collections import Counter, defaultdict
from mode_router import extract_business, extract_owned, detect_modes, resolve, split_questions, START_RE

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

    # --- คำถามหลายเรื่อง (ต้องได้ mixed แล้ว resolve() ตัดสินต่อ) ---
    ("M01", "อยากเปิดร้านงบ 50000 ต้องขายวันละกี่จานถึงคุ้มทุน", "mixed"),
    ("M02", "จะเปิดร้านน้ำปั่นต้องขออนุญาตอะไรบ้าง แล้วต้องขายวันละกี่แก้วถึงคุ้ม", "mixed"),
    ("M03", "เดือนนี้กำไรเท่าไหร่ แล้วเงินจะพอจ่ายค่าเช่าเดือนหน้าไหม", "mixed"),
]

# กติกาตัดสินของ resolve() เป็น Python ล้วน ไม่เรียก AI รันเร็ว
RESOLVE_CASES = [
    # (modes, รู้ธุรกิจแล้วไหม, ผลที่ควรได้)
    (["bep"], False, ("go", "bep")),
    (["startup_plan", "bep"], False, ("ask", ["startup_plan", "bep"])),   # ยังไม่รู้ธุรกิจ → ถามกลับ
    (["startup_plan", "bep"], True, ("go", "bep")),                       # รู้แล้ว → ตอบ bep เลย
    (["policy", "bep"], True, ("ask", ["policy", "bep"])),                # ไม่มี startup_plan ให้ตัด → ถามกลับ
    (["startup_plan", "policy", "bep"], True, ("ask", ["policy", "bep"])),
    (["profit", "cashflow"], True, ("ask", ["profit", "cashflow"])),
]


# กติกาฝั่ง Python ล้วน: (ประโยค, ควรแยกเป็นกี่ท่อน, ควรเจอคำว่าจะเริ่มธุรกิจไหม)
RULE_CASES = [
    ("อยากเปิดร้านอาหารตามสั่งแถวลาซาล มีงบ 50000 มีตู้เย็นแล้ว 1 เครื่อง", 1, True),   # "แล้ว" ติดคำ ห้ามตัด
    ("จะเปิดร้านน้ำปั่นต้องขออนุญาตอะไรบ้าง แล้วต้องขายวันละกี่แก้วถึงคุ้ม", 2, True),
    ("เดือนนี้กำไรเท่าไหร่ แล้วเงินจะพอจ่ายค่าเช่าเดือนหน้าไหม", 2, False),
    ("เปิดร้านอาหารต้องขอใบอนุญาตอะไรบ้าง", 1, False),                              # มีร้านแล้วก็พูดได้
    ("ร้านเปิดเดือนละ 26 วัน ต้นทุนคงที่ 30000 ต้องขายวันละกี่จานถึงจะไม่ขาดทุน", 1, False),
]


# ชื่อธุรกิจต้องตรงกับที่ผู้ใช้พิมพ์ (บั๊กที่เจอ: ข้าวมันไก่/ราเมง กลายเป็นร้านอาหารตามสั่ง)
BUSINESS_CASES = [
    ("อยากเปิดร้านข้าวมันไก่", "ร้านข้าวมันไก่"),
    ("อยากเปิดร้านราเมงแถวลาซาล มีงบ 100000 มีหม้อและถ้วยราเมง", "ร้านราเมง"),
    ("อยากเปิดร้านน้ำแถวลาซาลมีงบ30000", "ร้านน้ำ"),
    ("อยากเปิดร้านงบ 50000 ต้องขายวันละกี่จานถึงคุ้มทุน", None),
]


def check_business():
    ok = 0
    for text, want in BUSINESS_CASES:
        got = extract_business(text)
        ok += got == want
        print(f"[{'ผ่าน ' if got == want else 'ไม่ผ่าน'}] ธุรกิจ={got}" + ("" if got == want else f"  ควรเป็น {want}") + f"  {text}")
    print(f"ดึงชื่อธุรกิจ ผ่าน {ok}/{len(BUSINESS_CASES)}\n")


# อุปกรณ์ที่ผู้ใช้บอกว่ามีแล้ว (เทียบแบบไม่สนลำดับ)
OWNED_CASES = [
    ("อยากเปิดร้านไก่ย่างแถววัดด่าน งบ5000 มีโต๊ะพับและตู้เย็นเล็ก", {"โต๊ะพับ", "ตู้เย็นเล็ก"}),
    ("อยากเปิดร้านราเมงแถวลาซาล มีงบ 100000 มีหม้อและถ้วยราเมง", {"หม้อ", "ถ้วยราเมง"}),
    ("อยากเปิดร้านอาหารตามสั่งแถวลาซาล มีงบ 50000 มีตู้เย็นแล้ว 1 เครื่อง", {"ตู้เย็น"}),
    ("อยากเปิดร้านไก่ย่างแถวลาซาล มีงบ 10000 มีโต๊ะพับกับถาดวางแล้ว", {"โต๊ะพับ", "ถาดวาง"}),
    ("อยากเปิดร้านซักผ้า มีงบ 100000", set()),
]


def check_owned():
    ok = 0
    for text, want in OWNED_CASES:
        got = set(extract_owned(text))
        ok += got == want
        print(f"[{'ผ่าน ' if got == want else 'ไม่ผ่าน'}] มีแล้ว={sorted(got)}" + ("" if got == want else f"  ควรเป็น {sorted(want)}") + f"  {text}")
    print(f"ดึงของที่มีแล้ว ผ่าน {ok}/{len(OWNED_CASES)}\n")


def check_rules():
    ok = 0
    for text, n_parts, start in RULE_CASES:
        got_n, got_s = len(split_questions(text)), bool(START_RE.search(text))
        good = got_n == n_parts and got_s == start
        ok += good
        print(f"[{'ผ่าน ' if good else 'ไม่ผ่าน'}] แยก {got_n} ท่อน, จะเริ่มธุรกิจ={got_s}  {text}")
    print(f"กติกาแยกคำถาม ผ่าน {ok}/{len(RULE_CASES)}\n")


def check_resolve():
    ok = 0
    for modes, known, want in RESOLVE_CASES:
        got = resolve(modes, known)
        ok += got == want
        mark = "ผ่าน " if got == want else "ไม่ผ่าน"
        print(f"[{mark}] resolve({modes}, รู้ธุรกิจ={known}) -> {got}" + ("" if got == want else f"  ควรเป็น {want}"))
    print(f"กติกา resolve ผ่าน {ok}/{len(RESOLVE_CASES)}\n")


def main():
    check_rules()
    check_resolve()
    check_business()
    check_owned()
    total = passed = 0
    failed = []
    confusion = defaultdict(Counter)  # confusion[ควรเป็น][ได้] = จำนวนครั้ง

    for case_id, text, want in CASES:
        results = []
        for _ in range(RUNS):
            try:
                modes = detect_modes(text)
                got = modes[0] if len(modes) == 1 else "mixed"
                if got == "mixed" and want != "mixed":
                    got = "mixed" + str(modes)   # โชว์ว่าเติมเรื่องอะไรมา
            except Exception as e:
                got = f"ERROR({type(e).__name__})"
            results.append(got)
            confusion[want][got.split('[')[0]] += 1
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
