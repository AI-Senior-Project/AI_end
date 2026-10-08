"""
ตัวทดลอง flow เต็ม:  py app.py
รับคำถาม → แปลงเลขไทย → จำธุรกิจ → หาเรื่องที่ถาม → ตัดสินโหมด/ถามกลับ → ทำงานตามโหมด

ต้องมีไฟล์ในโฟลเดอร์เดียวกัน: main.py, mode_router.py, thai_numbers.py, guards.py, db_log.py
ทุกข้อความจะถูกบันทึกลงตาราง ai_log (ดูวิธีตั้งค่าใน db_log.py)
"""

from thai_numbers import normalize_thai_numbers
from mode_router import detect_modes, extract_business, extract_owned, resolve, ask_back_text, MODE_LABELS, START_RE
from main import extract_bep, calc_bep, to_number, LABELS
from db_log import AILogger
from equipment_lookup import get_equipment, format_equipment, budget_text, EquipmentRepo, MemoryRepo
from guards import budget_amounts
from model_lookup import find_model, confirm_text, ModelRepo, MemoryModelRepo

YES = ("y", "yes", "ั", "ใช่", "ช")
import re
REDO_RE = re.compile(r"ไม่ถูก|ผิด|ค้นใหม่|หาใหม่|ไม่ใช่")   # ผู้ใช้บอกว่ารายการอุปกรณ์ผิด
REDO_CMD_RE = re.compile(r"ค้นใหม่|ค้นหาใหม่|หาใหม่|ค้นอีก")   # คำสั่งค้นใหม่แบบชัดเจน


class Session:
    """สิ่งที่ระบบจำไว้ในบทสนทนานี้ (Python เป็นคนเก็บ ไม่ให้ AI จำเอง)"""
    def __init__(self):
        self.business = None       # ประเภทธุรกิจที่รู้แล้ว
        self.pending_modes = None  # ตัวเลือกที่รอผู้ใช้ตอบตอนถามกลับ
        self.pending_msg = None    # ข้อความเดิมที่ถามกลับไป
        self.repo = None           # ที่อ่าน/เก็บประวัติการค้นอุปกรณ์
        self.owned = []            # อุปกรณ์ที่ผู้ใช้บอกว่ามีแล้ว (สะสมทั้งบทสนทนา)
        self.model_repo = None     # คลังธุรกิจ data_basic_model
        self.model_confirmed = False   # จับคู่ธุรกิจกับคลังแล้วหรือยัง
        self.pending_model = None  # รอผู้ใช้ยืนยันว่าเป็นธุรกิจเดียวกับในคลังไหม
        self.pending_plan_msg = None
        self.budget = None         # งบของผู้ใช้ (ตอนต่อกับแอปจริง แอปเป็นคนส่งมา)


# ---------- ตัวจัดการแต่ละโหมด ----------

def run_bep(msg: str, s: Session, rec: dict):
    data = extract_bep(msg)
    rec["extracted"] = dict(data)          # สิ่งที่ AI ดึงได้ (ก่อนผู้ใช้เติม)
    asked = []
    for k, label in LABELS.items():
        while data[k] is None:
            data[k] = to_number(input(f"ยังไม่ทราบ{label} กรุณาระบุ (บาท): "))
            asked.append(k)
    if asked:
        rec["note"] = "ถามเพิ่ม: " + ", ".join(asked)

    print(f"\nสรุปข้อมูลที่ระบบเข้าใจ" + (f" ({s.business})" if s.business else "") + ":")
    for k, label in LABELS.items():
        print(f"  {label}: {data[k]:,.0f} บาท")

    if input("ถูกต้องไหม (y/n): ").strip().lower() not in YES:
        rec["user_corrected"] = True       # ผู้ใช้ปฏิเสธ = ระบบเข้าใจผิด ต้องตรวจเคสนี้
        print("ยกเลิก ลองพิมพ์ข้อมูลใหม่อีกครั้งนะครับ")
        return
    rec["user_corrected"] = False
    rec["confirmed"] = dict(data)
    bep = calc_bep(data)
    if bep is None:
        print("ราคาขายต้องสูงกว่าต้นทุนต่อชิ้นถึงจะคำนวณจุดคุ้มทุนได้ครับ")
    else:
        print(f"ต้องขายเดือนละ {bep:,.0f} ชิ้นถึงจะคุ้มทุนครับ")


def run_startup_plan(msg: str, s: Session, rec: dict):
    if not s.business:
        print("อยากเปิดธุรกิจแนวไหนครับ เช่น ร้านกาแฟ ร้านอาหารตามสั่ง ร้านซักผ้า")
        return
    if not s.model_confirmed:
        try:
            m = find_model(msg if START_RE.search(msg) else s.business, s.model_repo)
        except Exception as e:
            print(f"(อ่านคลังธุรกิจไม่ได้: {e})")
            m = {"status": "new", "want": s.business, "match": None}
        rec["note"] = f"คลังธุรกิจ: {m['status']} ({m['want']} → {m['match']})"
        if m["status"] == "similar":
            s.pending_model, s.pending_plan_msg = m, msg
            print(confirm_text(m))
            return
        if m["status"] == "found":
            s.business = m["match"]
        elif m["status"] == "new" and m["want"]:
            try:
                s.model_repo.add(m["want"], msg)
                print(f"(ยังไม่มี \"{m['want']}\" ในคลังธุรกิจ เพิ่มให้แล้วครับ)")
            except Exception as e:
                print(f"(เพิ่มลงคลังธุรกิจไม่ได้: {e})")
        s.model_confirmed = True
    if REDO_RE.search(msg):
        try:
            s.repo.reset_list(s.business)
            print(f"(ล้างรายการอุปกรณ์{s.business}เดิมแล้ว ค้นใหม่ให้นะครับ)")
            rec["user_corrected"] = True
        except Exception as e:
            print(f"(ล้างรายการเดิมไม่ได้: {e})")
    found_budget = budget_amounts(msg)
    if found_budget:
        s.budget = max(found_budget)
    for o in extract_owned(msg):
        if o not in s.owned:
            s.owned.append(o)
    try:
        result = get_equipment(s.business, s.repo, s.owned)
    except Exception as e:                      # ฐานข้อมูลพัง → ไม่ปิดโปรแกรม ใช้ที่เก็บชั่วคราวแทน
        print(f"(ใช้ประวัติในฐานข้อมูลไม่ได้: {e}\n ขอค้นแบบไม่บันทึกไปก่อนนะครับ)")
        s.repo = MemoryRepo()
        result = get_equipment(s.business, s.repo, s.owned)
    rec["note"] = (f"อุปกรณ์: {len(result['items'])} รายการ, รายการจาก {result['list_source']}, "
                   f"มีแล้ว: {', '.join(s.owned) or '-'}")
    print(format_equipment(s.business, result))
    bt = budget_text(s.budget, result)
    if bt:
        print("\n" + bt)


def run_placeholder(mode: str):
    def _run(msg, s, rec):
        print(f"[{mode}] {MODE_LABELS.get(mode, mode)}  (ยังไม่ได้ต่อโหมดนี้)")
    return _run


def run_unclear(msg, s, rec):
    print("อยากให้ช่วยเรื่องไหนครับ เช่น วางแผนเปิดร้าน หาจุดคุ้มทุน คำนวณกำไร ดูเงินสด หรือเรื่องใบอนุญาต")


HANDLERS = {
    "bep": run_bep,
    "startup_plan": run_startup_plan,
    "profit": run_placeholder("profit"),
    "cashflow": run_placeholder("cashflow"),
    "policy": run_placeholder("policy"),
    "unclear": run_unclear,
}


# ---------- วงหลัก ----------

def handle(raw_msg: str, s: Session, log: AILogger):
    msg = normalize_thai_numbers(raw_msg)
    rec = {"user_message": msg}
    try:
        _handle(msg, s, rec)
    finally:
        rec.setdefault("business", s.business)
        log.write(rec)                     # บันทึกทุกข้อความ แม้กลางทางจะพัง


def _handle(msg: str, s: Session, rec: dict):
    # ผู้ใช้กำลังตอบว่าธุรกิจตรงกับในคลังไหม
    if s.pending_model:
        m, original = s.pending_model, s.pending_plan_msg
        s.pending_model = s.pending_plan_msg = None
        ans = msg.strip().lower()
        if ans in YES:
            s.business = m["match"]
            rec["note"] = f"ยืนยันธุรกิจ: {m['want']} = {m['match']}"
        else:
            s.business = m["want"]
            try:
                s.model_repo.add(m["want"], original)
            except Exception as e:
                print(f"(เพิ่มลงคลังธุรกิจไม่ได้: {e})")
            rec["note"] = f"ปฏิเสธ: {m['want']} ≠ {m['match']} → เพิ่มธุรกิจใหม่"
            rec["user_corrected"] = True
        s.model_confirmed = True
        rec.update(action="confirm", final_mode="startup_plan", business=s.business)
        run_startup_plan(original, s, rec)
        return

    # ผู้ใช้กำลังตอบเลขตัวเลือกจากการถามกลับ
    if s.pending_modes:
        choice = msg.strip()
        if choice.isdigit() and 1 <= int(choice) <= len(s.pending_modes):
            mode = s.pending_modes[int(choice) - 1]
            original = s.pending_msg
            s.pending_modes = s.pending_msg = None
            rec.update(action="choice", final_mode=mode, note=f"เลือกข้อ {choice} ของ: {original}")
            HANDLERS[mode](original, s, rec)
            return
        s.pending_modes = s.pending_msg = None  # พิมพ์อย่างอื่นมา ถือว่าเป็นคำถามใหม่

    # สั่ง "ค้นใหม่" ตรง ๆ → ไม่ต้องให้ AI เดาโหมด ล้างรายการของธุรกิจที่คุยอยู่แล้วค้นใหม่เลย
    if s.business and REDO_CMD_RE.search(msg) and not START_RE.search(msg):
        rec.update(action="redo", final_mode="startup_plan", business=s.business)
        run_startup_plan(msg, s, rec)
        return

    # นับว่า "รู้ธุรกิจ" เฉพาะที่คุยกันมาก่อนข้อความนี้เท่านั้น
    known_before = s.business is not None
    # ดึงชื่อธุรกิจถ้ายังไม่รู้ หรือผู้ใช้พูดถึงการเปิดร้านใหม่ (อาจเปลี่ยนใจ)
    if not s.business or START_RE.search(msg):
        new_business = extract_business(msg)
        if new_business:
            if new_business != s.business:
                s.model_confirmed = False
            s.business = new_business

    modes = detect_modes(msg)
    action, value = resolve(modes, business_known=known_before)
    rec.update(modes=modes, action=action, business=s.business)

    if action == "ask":
        s.pending_modes, s.pending_msg = value, msg
        print(ask_back_text(value))
    else:
        rec["final_mode"] = value
        HANDLERS[value](msg, s, rec)


def main():
    s = Session()
    log = AILogger()
    if log.conn and log.ai_model_id:
        s.repo = EquipmentRepo(log.conn, log.ai_model_id)
    else:
        if log.conn:
            print("(ยังไม่ได้ตั้ง SME_AI_MODEL_ID: ผลค้นอุปกรณ์จะไม่ถูกบันทึกลงฐานข้อมูล)")
        s.repo = MemoryRepo()
    s.model_repo = ModelRepo(log.conn, log.ai_model_id) if log.conn else MemoryModelRepo()
    print("พิมพ์คำถามได้เลยครับ (พิมพ์ q เพื่อออก)")
    try:
        while True:
            raw = input("\nคุณ: ").strip()
            if raw.lower() == "q":
                break
            if raw:
                handle(raw, s, log)
    finally:
        log.close()


if __name__ == "__main__":
    main()
