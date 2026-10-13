"""ทดสอบภาษาและ prompt ของโมเดล โดยไม่แตะ MySQL จริง

สคริปต์นี้ใช้โค้ดตัวจริงจาก assistant.py กับ tools.py แต่สลับฐานข้อมูลเป็นตัวจำลอง
ในหน่วยความจำ (สินค้า 5 ตัวเหมือนใน seed.sql) และตอบ y/n แทนคนให้อัตโนมัติ
ทุกข้อเริ่มจากข้อมูลชุดเดิมเสมอ รันกี่รอบก็ได้ ไม่มีอะไรพัง

prompt ที่ใช้ทดสอบอ่านจากไฟล์ prompt.txt แก้ไฟล์นั้นแล้วรันใหม่เพื่อเทียบผลได้เลย

วิธีรัน:
    python test_prompt.py                    ทดสอบทุกข้อ 1 รอบ
    python test_prompt.py --runs 3           ข้อละ 3 รอบ (โมเดลตอบไม่เหมือนกันทุกครั้ง)
    python test_prompt.py --case S1 N4       เฉพาะบางข้อ
    python test_prompt.py --model qwen2.5:14b

ผลแบบละเอียดจะถูกเขียนลงไฟล์ prompt_test_result.txt
"""

import argparse
import builtins
import contextlib
import datetime
import io
import json
import re
import sqlite3
import sys
import time
import types
from pathlib import Path

HERE = Path(__file__).resolve().parent
RESULT_FILE = HERE / "prompt_test_result.txt"

# =====================================================================
# ฐานข้อมูลจำลอง: ใช้แทน db.py ระหว่างทดสอบ
# =====================================================================

SEED_PRODUCTS = [
    # (id_product, name, quantity, price, type)
    (1, "โค้ก 325 มล.", 36, 15.0, "เครื่องดื่ม"),
    (2, "น้ำดื่ม 600 มล.", 48, 10.0, "เครื่องดื่ม"),
    (3, "น้ำส้ม 250 มล.", 8, 20.0, "เครื่องดื่ม"),
    (4, "บะหมี่กึ่งสำเร็จรูป", 60, 7.0, "อาหารแห้ง"),
    (5, "ขนมปังแผ่น", 12, 35.0, "เบเกอรี่"),
]

MEMORY_SCHEMA = """
CREATE TABLE Product (
    id_product INTEGER PRIMARY KEY AUTOINCREMENT, id_business INTEGER NOT NULL,
    name TEXT NOT NULL, image TEXT, quantity INTEGER NOT NULL DEFAULT 0 CHECK (quantity >= 0),
    price REAL NOT NULL CHECK (price >= 0), type TEXT,
    input_date TEXT DEFAULT CURRENT_TIMESTAMP, UNIQUE (id_business, name));
CREATE TABLE Promotions (
    id_promotions INTEGER PRIMARY KEY AUTOINCREMENT, id_business INTEGER NOT NULL,
    id_product INTEGER NOT NULL, name TEXT NOT NULL, discount_type TEXT NOT NULL,
    discount_value REAL NOT NULL, start_date TEXT NOT NULL, end_date TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'draft');
CREATE TABLE Message_Box (
    id_message INTEGER PRIMARY KEY AUTOINCREMENT, id_business INTEGER, id_user INTEGER,
    role TEXT, content TEXT, send_date TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE Ai_action_log (
    id_action INTEGER PRIMARY KEY AUTOINCREMENT, id_message INTEGER, id_user INTEGER,
    id_ai_model INTEGER, tool_name TEXT, arguments TEXT, status TEXT DEFAULT 'pending',
    created_date TEXT DEFAULT CURRENT_TIMESTAMP);
"""

memory_db = types.ModuleType("db")
memory_db.ID_USER = 1
memory_db.ID_BUSINESS = 1
memory_db._conn = None


def _reset():
    """ล้างแล้วสร้างข้อมูลชุดเริ่มต้นใหม่"""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(MEMORY_SCHEMA)
    conn.executemany(
        "INSERT INTO Product (id_product, id_business, name, quantity, price, type) "
        "VALUES (?, 1, ?, ?, ?, ?)",
        SEED_PRODUCTS,
    )
    conn.commit()
    memory_db._conn = conn


def _run(sql, params=()):
    return memory_db._conn.execute(sql.replace("%s", "?"), tuple(params))


def _fetch_one(sql, params=()):
    row = _run(sql, params).fetchone()
    return dict(row) if row else None


memory_db.reset = _reset
memory_db.fetch_one = _fetch_one
memory_db.fetch_all = lambda sql, params=(): [dict(r) for r in _run(sql, params).fetchall()]
memory_db.insert = lambda sql, params=(): _run(sql, params).lastrowid
memory_db.execute = lambda sql, params=(): _run(sql, params).rowcount
memory_db.commit = lambda: memory_db._conn.commit()
memory_db.rollback = lambda: memory_db._conn.rollback()

# ต้องสลับก่อน import tools กับ assistant เพื่อให้สองไฟล์นั้นใช้ตัวจำลอง
sys.modules["db"] = memory_db
db = memory_db

try:
    import assistant
    import tools
except ImportError as error:
    print(f"import ไม่ได้: {error}")
    print("เช็กว่าไฟล์นี้อยู่โฟลเดอร์เดียวกับ assistant.py และ tools.py และลง ollama แล้ว (pip install ollama)")
    sys.exit(1)

# จดไว้ว่าแต่ละรอบโมเดลเรียกเครื่องมืออะไรบ้าง
_calls = []
_real_run_tool = assistant.run_tool


def _recording_run_tool(name, arguments, *args, **kwargs):
    result = _real_run_tool(name, arguments, *args, **kwargs)
    _calls.append({"tool": name, "arguments": arguments, "result": result})
    return result


assistant.run_tool = _recording_run_tool

# =====================================================================
# ชุดทดสอบ
# =====================================================================

TODAY = datetime.date.today()
TOMORROW = TODAY + datetime.timedelta(days=1)
D1 = TODAY + datetime.timedelta(days=3)
D2 = TODAY + datetime.timedelta(days=14)

GROUPS = {
    "S": "ปรับสต็อก",
    "Q": "ถามข้อมูล",
    "E": "เพิ่มและแก้ไขสินค้า",
    "P": "โปรโมชั่น",
    "N": "ไม่ทำเกินคำสั่ง",
    "L": "ภาษา",
}

# แต่ละข้อมีหนึ่งรอบสนทนาขึ้นไป แต่ละรอบระบุได้ว่า:
#   say         ข้อความที่ผู้ใช้พิมพ์
#   confirm     คำตอบตอนโปรแกรมถามยืนยัน (ค่าเริ่มต้น y)
#   products    สินค้าเดิมที่ควรเปลี่ยน {id_product: {คอลัมน์: ค่าใหม่}} ที่เหลือต้องเหมือนเดิม
#   new_product สินค้าใหม่ที่ควรถูกเพิ่ม ถ้าไม่ใส่คือห้ามมีสินค้าใหม่
#   promo       โปรโมชั่นที่ควรถูกสร้าง ถ้าไม่ใส่คือห้ามมีโปรโมชั่น
#   need_read   ต้องเรียกเครื่องมือดูข้อมูลก่อนตอบ
#   reply_all   คำที่ต้องมีครบในคำตอบ
#   reply_any   คำที่ต้องมีอย่างน้อยหนึ่งคำในคำตอบ
#   reply_none  คำที่ห้ามมีในคำตอบ
NOT_DONE = ["ไม่", "ยกเลิก"]   # คำที่ควรมีเมื่อรายการไม่ได้ถูกทำ

CASES = [
    # ---------- ปรับสต็อก ----------
    {"id": "S1", "title": "ของเข้า",
     "turns": [{"say": "โค้กเข้ามาเพิ่ม 24 ขวด", "products": {1: {"quantity": 60}}}]},
    {"id": "S2", "title": "ขายออก",
     "turns": [{"say": "ขายน้ำดื่มไป 5 ขวด", "products": {2: {"quantity": 43}}}]},
    {"id": "S3", "title": "ของเสีย",
     "turns": [{"say": "ขนมปังเสีย 2 ห่อ ตัดออกจากสต็อกให้หน่อย", "products": {5: {"quantity": 10}}}]},
    {"id": "S4", "title": "ภาษาพูด",
     "turns": [{"say": "เอาบะหมี่ออก 6 ซองนะ", "products": {4: {"quantity": 54}}}]},
    {"id": "S5", "title": "ตัวเลขเป็นคำไทย",
     "turns": [{"say": "โค้กเข้ามายี่สิบสี่ขวด", "products": {1: {"quantity": 60}}}]},
    {"id": "S6", "title": "หน่วยโหล",
     "turns": [{"say": "น้ำดื่มเข้ามาเพิ่ม 1 โหล", "products": {2: {"quantity": 60}}}]},

    # ---------- ถามข้อมูล ----------
    {"id": "Q1", "title": "ถามจำนวนคงเหลือ",
     "turns": [{"say": "ตอนนี้บะหมี่เหลือกี่ซอง", "need_read": True, "reply_all": ["60"]}]},
    {"id": "Q2", "title": "ของใกล้หมด",
     "turns": [{"say": "มีอะไรเหลือน้อยกว่า 10 ชิ้นบ้าง", "need_read": True,
                "reply_all": ["น้ำส้ม"], "reply_none": ["โค้ก", "บะหมี่"]}]},
    {"id": "Q3", "title": "ดูสินค้าทั้งหมด",
     "turns": [{"say": "ขอดูสินค้าทั้งหมดในร้านหน่อย", "need_read": True,
                "reply_all": ["โค้ก", "น้ำดื่ม", "น้ำส้ม", "บะหมี่", "ขนมปัง"]}]},
    {"id": "Q4", "title": "ไทยปนอังกฤษ",
     "turns": [{"say": "stock โค้กเหลือเท่าไหร่", "need_read": True, "reply_all": ["36"]}]},

    # ---------- เพิ่มและแก้ไขสินค้า ----------
    {"id": "E1", "title": "เพิ่มสินค้าใหม่",
     "turns": [{"say": "เพิ่มสินค้าใหม่ ชาเขียว ราคา 25 บาท มี 10 ขวด",
                "new_product": {"name_has": "ชาเขียว", "price": 25, "quantity": 10}}]},
    {"id": "E2", "title": "แก้ราคา",
     "turns": [{"say": "ขึ้นราคาโค้กเป็น 17 บาท", "products": {1: {"price": 17.0}}}]},
    {"id": "E3", "title": "เปลี่ยนชื่อ",
     "turns": [{"say": "เปลี่ยนชื่อขนมปังแผ่นเป็น ขนมปังโฮลวีต",
                "products": {5: {"name": "ขนมปังโฮลวีต"}}}]},

    # ---------- โปรโมชั่น ----------
    {"id": "P1", "title": "ลดเป็นเปอร์เซ็นต์ ระบุวันที่ชัด",
     "turns": [{"say": f"ทำโปรลดขนมปัง 10% ชื่อโปร ขนมปังลดพิเศษ ตั้งแต่วันที่ {D1} ถึง {D2}",
                "promo": {"id_product": 5, "discount_type": "percent", "discount_value": 10,
                          "start": str(D1), "end": str(D2)}}]},
    {"id": "P2", "title": "ลดเป็นบาท ใช้คำว่าพรุ่งนี้",
     "turns": [{"say": f"ลดราคาโค้ก 3 บาท ชื่อโปร โค้กสุดคุ้ม เริ่มพรุ่งนี้ ถึงวันที่ {D2}",
                "promo": {"id_product": 1, "discount_type": "amount", "discount_value": 3,
                          "start": str(TOMORROW), "end": str(D2)}}]},

    # ---------- ไม่ทำเกินคำสั่ง ----------
    {"id": "N1", "title": "ไม่รู้ราคาต้องถามก่อน แล้วจำบริบทได้",
     "turns": [{"say": "เพิ่มสินค้าใหม่ชื่อ นมสด"},
               {"say": "ราคา 30 บาท มี 5 กล่อง",
                "new_product": {"name_has": "นมสด", "price": 30, "quantity": 5}}]},
    {"id": "N2", "title": "โปรไม่มีรายละเอียดต้องถามก่อน",
     "turns": [{"say": "ทำโปรให้โค้กหน่อย"}]},
    {"id": "N3", "title": "สั่งลบสินค้า (ไม่มีเครื่องมือนี้)",
     "turns": [{"say": "ลบโค้กออกจากร้านเลย", "reply_any": NOT_DONE}]},
    {"id": "N4", "title": "ขายเกินจำนวนที่มี",
     "turns": [{"say": "ขายน้ำส้มไป 20 ขวด", "reply_any": NOT_DONE}]},
    {"id": "N5", "title": "ผู้ใช้กดยกเลิก",
     "turns": [{"say": "โค้กเข้ามาเพิ่ม 24 ขวด", "confirm": "n", "reply_any": NOT_DONE}]},
    {"id": "N6", "title": "สินค้าที่ไม่มีในร้าน",
     "turns": [{"say": "เป๊ปซี่เข้ามา 12 กระป๋อง", "reply_any": NOT_DONE}]},

    # ---------- ภาษา ----------
    {"id": "L1", "title": "ทักทาย",
     "turns": [{"say": "สวัสดี ทำอะไรได้บ้าง"}]},
    {"id": "L2", "title": "ผู้ใช้พิมพ์อังกฤษ ต้องตอบไทย",
     "turns": [{"say": "How many products do we have in the shop?"}]},
    {"id": "L3", "title": "ขอบคุณ",
     "turns": [{"say": "ขอบคุณมาก"}]},
]

# =====================================================================
# ตัวตรวจ
# =====================================================================

FOREIGN_SCRIPT = re.compile(r"[一-鿿぀-ヿ가-힯]+")
THAI_LETTER = re.compile(r"[ก-ฮ]")
LATIN_LETTER = re.compile(r"[A-Za-z]")
NUMBER = re.compile(r"\d+(?:,\d{3})*(?:\.\d+)?")
TOOL_NAMES = list(tools.READ_TOOLS) + list(tools.WRITE_TOOLS)
TOOL_CALL_AS_TEXT = re.compile(
    r"<tool_call>|\"name\"\s*:\s*\"(?:" + "|".join(TOOL_NAMES) + r")\""
)


def _numbers(text):
    return {float(n.replace(",", "")) for n in NUMBER.findall(text)}


def language_problems(reply):
    problems = []
    foreign = FOREIGN_SCRIPT.findall(reply)
    if foreign:
        problems.append(f"มีตัวอักษรจีน/ญี่ปุ่น/เกาหลีปนมา: {' '.join(foreign[:3])}")
    thai = len(THAI_LETTER.findall(reply))
    latin = len(LATIN_LETTER.findall(reply))
    if thai == 0:
        problems.append("ไม่ได้ตอบเป็นภาษาไทย")
    elif thai < latin:
        problems.append("ตอบเป็นภาษาอังกฤษเป็นส่วนใหญ่")
    if TOOL_CALL_AS_TEXT.search(reply):
        problems.append("พิมพ์คำสั่งเรียกเครื่องมือออกมาเป็นข้อความ แทนที่จะเรียกจริง")
    return problems


def reply_notes(reply, said_so_far, calls):
    """ข้อสังเกตที่ไม่ถึงกับตก แต่ควรอ่านเอง"""
    notes = []
    leaked = [name for name in TOOL_NAMES if name in reply]
    if leaked:
        notes.append(f"มีชื่อฟังก์ชันหลุดมาในคำตอบ: {', '.join(leaked)}")

    # ตัวเลขในคำตอบควรมาจากที่ผู้ใช้พิมพ์ หรือจากผลลัพธ์ของเครื่องมือเท่านั้น
    known = _numbers(" ".join(said_so_far))
    known |= _numbers(json.dumps([c["result"] for c in calls], ensure_ascii=False, default=str))
    known |= _numbers(f"{TODAY} {TOMORROW}")
    body = re.sub(r"(?m)^\s*\d+[.)]\s+", "", reply)        # ไม่นับเลขหัวข้อ 1. 2. 3.
    unknown = sorted(n for n in _numbers(body) if n not in known)
    if unknown:
        shown = ", ".join(f"{n:g}" for n in unknown[:5])
        notes.append(f"ตัวเลขในคำตอบที่ไม่ได้มาจากผู้ใช้หรือเครื่องมือ: {shown}")
    return notes


def data_problems(expect_products, expect_new, expect_promo):
    problems = []
    rows = db.fetch_all("SELECT id_product, name, quantity, price, type FROM Product ORDER BY id_product")
    by_id = {row["id_product"]: row for row in rows}

    # สินค้าเดิม 5 ตัว: ต้องเปลี่ยนเฉพาะที่คาดไว้
    for id_product, name, quantity, price, product_type in SEED_PRODUCTS:
        want = {"name": name, "quantity": quantity, "price": price, "type": product_type}
        want.update(expect_products.get(id_product, {}))
        got = by_id.get(id_product)
        if got is None:
            problems.append(f"สินค้า '{name}' หายไป")
            continue
        for column, value in want.items():
            if got[column] != value:
                problems.append(f"'{name}' {column} ควรเป็น {value} แต่เป็น {got[column]}")

    # สินค้าใหม่
    added = [row for row in rows if row["id_product"] > len(SEED_PRODUCTS)]
    if expect_new is None:
        for row in added:
            problems.append(f"มีสินค้าใหม่ที่ไม่ควรถูกเพิ่ม: '{row['name']}' ราคา {row['price']:g}")
    elif len(added) != 1:
        problems.append(f"ควรมีสินค้าใหม่ 1 ตัว แต่มี {len(added)} ตัว")
    else:
        row = added[0]
        if expect_new["name_has"] not in row["name"]:
            problems.append(f"ชื่อสินค้าใหม่ควรมีคำว่า {expect_new['name_has']} แต่เป็น '{row['name']}'")
        for column in ("price", "quantity"):
            if row[column] != expect_new[column]:
                problems.append(f"สินค้าใหม่ {column} ควรเป็น {expect_new[column]} แต่เป็น {row[column]:g}")

    # โปรโมชั่น
    promos = db.fetch_all("SELECT * FROM Promotions ORDER BY id_promotions")
    if expect_promo is None:
        for row in promos:
            problems.append(f"มีโปรโมชั่นที่ไม่ควรถูกสร้าง: '{row['name']}'")
    elif len(promos) != 1:
        problems.append(f"ควรมีโปรโมชั่น 1 รายการ แต่มี {len(promos)} รายการ")
    else:
        row = promos[0]
        checks = [
            ("สินค้า (id_product)", row["id_product"], expect_promo["id_product"]),
            ("discount_type", row["discount_type"], expect_promo["discount_type"]),
            ("discount_value", row["discount_value"], expect_promo["discount_value"]),
            ("วันเริ่ม", row["start_date"][:10], expect_promo["start"]),
            ("วันสิ้นสุด", row["end_date"][:10], expect_promo["end"]),
            ("status", row["status"], "draft"),
        ]
        for label, got, want in checks:
            if got != want:
                problems.append(f"โปรโมชั่น {label} ควรเป็น {want} แต่เป็น {got}")
    return problems


def check_turn(spec, outcome, said_so_far, state):
    reply = outcome["reply"]
    problems = data_problems(state["products"], state["new_product"], state["promo"])
    if spec.get("need_read") and not any(c["tool"] in tools.READ_TOOLS for c in outcome["calls"]):
        problems.append("ตอบโดยไม่ได้เรียกเครื่องมือดูข้อมูล (เดาเอง)")
    for word in spec.get("reply_all", []):
        if word not in reply:
            problems.append(f"คำตอบควรมี '{word}'")
    if spec.get("reply_any") and not any(word in reply for word in spec["reply_any"]):
        problems.append("คำตอบควรบอกว่ารายการไม่ได้ถูกทำ (ไม่มีคำว่า " + " หรือ ".join(spec["reply_any"]) + ")")
    for word in spec.get("reply_none", []):
        if word in reply:
            problems.append(f"คำตอบไม่ควรมี '{word}'")
    problems += language_problems(reply)
    return problems, reply_notes(reply, said_so_far, outcome["calls"])


# =====================================================================
# ตัวรัน
# =====================================================================

def run_turn(history, text, answer, ai, system_prompt):
    """ส่งหนึ่งข้อความเข้า chat_turn ตัวจริง และตอบคำถามยืนยันแทนคน"""
    _calls.clear()
    confirms = []

    def auto_answer(prompt=""):
        confirms.append(answer)
        return answer

    real_input = builtins.input
    builtins.input = auto_answer
    screen = io.StringIO()
    started = time.time()
    try:
        with contextlib.redirect_stdout(screen):
            reply = assistant.chat_turn(history, text, ai, system_prompt)
    finally:
        builtins.input = real_input
    return {"reply": reply, "calls": list(_calls), "confirms": len(confirms),
            "seconds": time.time() - started}


def run_case(case, ai, system_prompt):
    db.reset()
    history, said = [], []
    state = {"products": {}, "new_product": None, "promo": None}
    record = {"id": case["id"], "title": case["title"], "turns": [], "passed": True, "seconds": 0.0}
    for spec in case["turns"]:
        # สิ่งที่คาดไว้สะสมไปเรื่อยๆ ตลอดบทสนทนาของข้อนั้น
        state["products"].update(spec.get("products", {}))
        state["new_product"] = spec.get("new_product", state["new_product"])
        state["promo"] = spec.get("promo", state["promo"])
        said.append(spec["say"])
        outcome = run_turn(history, spec["say"], spec.get("confirm", "y"), ai, system_prompt)
        problems, notes = check_turn(spec, outcome, said, state)
        record["turns"].append({"say": spec["say"], "confirm": spec.get("confirm", "y"),
                                "problems": problems, "notes": notes, **outcome})
        record["seconds"] += outcome["seconds"]
        if problems:
            record["passed"] = False
    return record


def describe(record):
    """ข้อความละเอียดของหนึ่งข้อ สำหรับเขียนลงไฟล์ผล"""
    status = "ผ่าน" if record["passed"] else "ไม่ผ่าน"
    lines = [f"[{record['id']}] {record['title']} : {status} ({record['seconds']:.1f} วินาที)"]
    for turn in record["turns"]:
        lines.append(f"  ผู้ใช้: {turn['say']}")
        for call in turn["calls"]:
            arguments = json.dumps(call["arguments"], ensure_ascii=False, default=str)
            result = json.dumps(call["result"], ensure_ascii=False, default=str)
            if len(result) > 300:
                result = result[:300] + "..."
            lines.append(f"    เรียก {call['tool']} {arguments}")
            lines.append(f"      ได้ {result}")
        if turn["confirms"]:
            lines.append(f"    โปรแกรมถามยืนยัน {turn['confirms']} ครั้ง ตอบ {turn['confirm']}")
        lines.append("  ผู้ช่วย: " + turn["reply"].replace("\n", "\n          "))
        for problem in turn["problems"]:
            lines.append(f"    ไม่ผ่าน: {problem}")
        for note in turn["notes"]:
            lines.append(f"    ข้อสังเกต: {note}")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="ทดสอบภาษาและ prompt ของโมเดล")
    parser.add_argument("--model", default="qwen2.5:7b")
    parser.add_argument("--runs", type=int, default=1, help="ทดสอบข้อละกี่รอบ")
    parser.add_argument("--case", nargs="*", default=[], help="รหัสข้อที่จะทดสอบ เช่น S1 N4")
    parser.add_argument("--prompt", default=str(HERE / "prompt.txt"))
    args = parser.parse_args()

    # กันโปรแกรมล้มตอนพิมพ์ภาษาไทย ถ้าหน้าจอแสดงตัวอักษรบางตัวไม่ได้
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass

    try:
        prompt_text = Path(args.prompt).read_text(encoding="utf-8-sig").strip()
    except OSError as error:
        print(f"อ่านไฟล์ prompt ไม่ได้: {error}")
        return
    wanted = {c.upper() for c in args.case}
    cases = [c for c in CASES if not wanted or c["id"] in wanted]
    if not cases:
        print("ไม่มีข้อที่ตรงกับ --case ที่ใส่มา")
        return

    ai = {"id_ai_model": 1, "model_name": args.model, "prompt": prompt_text}
    system_prompt = assistant.build_system_prompt(ai, {"name_brand": "ร้านตัวอย่าง"})

    print(f"โมเดล {args.model} | {len(cases)} ข้อ x {args.runs} รอบ | กำลังโหลดโมเดล...")
    try:
        # เรียกหนึ่งครั้งให้โมเดลโหลดเข้าหน่วยความจำก่อน เวลาของข้อแรกจะได้ไม่เพี้ยน
        assistant.ollama.chat(model=args.model, messages=[{"role": "user", "content": "สวัสดี"}],
                              options=assistant.OPTIONS)
    except Exception as error:
        print(f"เรียกโมเดลไม่ได้: {error}")
        print(f"เช็กว่า Ollama เปิดอยู่ และมีโมเดลนี้แล้ว (ollama pull {args.model})")
        return

    records = {case["id"]: [] for case in cases}
    details = []
    started = time.time()
    for round_number in range(1, args.runs + 1):
        for case in cases:
            try:
                record = run_case(case, ai, system_prompt)
            except Exception as error:
                print(f"\nหยุดที่ข้อ {case['id']} เพราะเกิดข้อผิดพลาด: {error}")
                return
            records[case["id"]].append(record)
            details.append(describe(record))
            status = "ผ่าน   " if record["passed"] else "ไม่ผ่าน"
            suffix = f" (รอบ {round_number})" if args.runs > 1 else ""
            print(f"{status} [{case['id']}] {case['title']}{suffix} {record['seconds']:.1f} วิ")
            if not record["passed"]:
                for turn in record["turns"]:
                    for problem in turn["problems"]:
                        print(f"          - {problem}")

    # ---------- สรุป ----------
    total = sum(len(runs) for runs in records.values())
    passed = sum(r["passed"] for runs in records.values() for r in runs)
    turn_count = sum(len(r["turns"]) for runs in records.values() for r in runs)
    model_seconds = sum(r["seconds"] for runs in records.values() for r in runs)
    summary = ["", "===== สรุป =====",
               f"โมเดล: {args.model}",
               f"วันที่ทดสอบ: {datetime.datetime.now():%Y-%m-%d %H:%M}",
               f"ผ่าน {passed} จาก {total} ({passed * 100 // total}%)",
               f"เวลาเฉลี่ยต่อหนึ่งคำสั่ง: {model_seconds / turn_count:.1f} วินาที "
               f"(รวมทั้งหมด {time.time() - started:.0f} วินาที)", ""]
    for letter, group_name in GROUPS.items():
        runs = [r for case_id, rs in records.items() if case_id.startswith(letter) for r in rs]
        if runs:
            summary.append(f"  {group_name}: ผ่าน {sum(r['passed'] for r in runs)} จาก {len(runs)}")
    failed = [case_id for case_id, runs in records.items() if not all(r["passed"] for r in runs)]
    if failed:
        summary.append("")
        summary.append("ข้อที่ไม่ผ่าน: " + ", ".join(
            f"{case_id} ({sum(r['passed'] for r in records[case_id])}/{len(records[case_id])})"
            for case_id in failed))
    noted = sum(bool(t["notes"]) for runs in records.values() for r in runs for t in r["turns"])
    if noted:
        summary.append(f"มีข้อสังเกตให้อ่านเอง {noted} จุด ดูในไฟล์ผล")
    print("\n".join(summary))

    RESULT_FILE.write_text(
        "prompt ที่ใช้:\n" + system_prompt + "\n" + "\n".join(summary)
        + "\n\n===== รายละเอียด =====\n\n" + "\n\n".join(details) + "\n",
        encoding="utf-8",
    )
    print(f"\nรายละเอียดทุกข้ออยู่ในไฟล์ {RESULT_FILE.name}")


if __name__ == "__main__":
    main()
