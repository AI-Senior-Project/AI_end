"""ตัวแชทผู้ช่วยร้านค้า: ต่อ qwen2.5:7b (Ollama) เข้ากับฐานข้อมูล MySQL

วิธีรัน:  python assistant.py
พิมพ์ exit หรือ ออก เพื่อเลิก

ขั้นตอนของแต่ละคำสั่ง:
1. บันทึกข้อความผู้ใช้ลง Message_Box แล้วส่งให้โมเดลพร้อมรายการเครื่องมือ
2. ถ้าโมเดลขอเรียกเครื่องมือ โค้ดจะตรวจค่าก่อน
   - เครื่องมือแบบอ่าน   ทำทันที
   - เครื่องมือแบบแก้ไข  บันทึกลง Ai_action_log เป็น pending แล้วถามผู้ใช้ก่อน
     ยืนยัน -> ทำจริง แล้วเปลี่ยนเป็น confirmed / ไม่ยืนยัน -> rejected / พัง -> failed
3. ส่งผลลัพธ์กลับให้โมเดลสรุปเป็นคำตอบ แล้วบันทึกคำตอบลง Message_Box
"""

import calendar
import datetime
import json
import re
from types import SimpleNamespace

import ollama

import db
import tools

MAX_ROUNDS = 5     # กันโมเดลเรียกเครื่องมือวนไม่จบ
KEEP_TURNS = 6     # ส่งประวัติให้โมเดลแค่กี่คำสั่งล่าสุด (กันข้อความยาวเกินที่โมเดลรับได้)
# ค่าชุดเดียวกับใน Modelfile ค่าที่ส่งจากตรงนี้จะทับค่าใน Modelfile เสมอ
OPTIONS = {"temperature": 0.3, "top_p": 0.8, "repeat_penalty": 1.0, "num_ctx": 8192}

YES_WORDS = {"y", "yes", "ใช่", "ตกลง", "ยืนยัน"}
EXIT_WORDS = {"exit", "quit", "ออก"}
THAI_WEEKDAYS = ["จันทร์", "อังคาร", "พุธ", "พฤหัสบดี", "ศุกร์", "เสาร์", "อาทิตย์"]


def to_json(data):
    # default=str ไว้แปลงค่า Decimal กับวันที่ที่ MySQL ส่งมา
    return json.dumps(data, ensure_ascii=False, default=str)


# =====================================================================
# บันทึกลงฐานข้อมูล
# =====================================================================

def save_message(role, content):
    id_message = db.insert(
        "INSERT INTO Message_Box (id_business, id_user, role, content) VALUES (%s, %s, %s, %s)",
        (db.ID_BUSINESS, db.ID_USER, role, content),
    )
    db.commit()
    return id_message


def log_action(id_message, id_ai_model, tool_name, arguments):
    """จดไว้ก่อนว่า AI ขอทำอะไร สถานะเริ่มต้นคือ pending"""
    id_action = db.insert(
        "INSERT INTO Ai_action_log (id_message, id_user, id_ai_model, tool_name, arguments) "
        "VALUES (%s, %s, %s, %s, %s)",
        (id_message, db.ID_USER, id_ai_model, tool_name, to_json(arguments)),
    )
    db.commit()
    return id_action


def set_action_status(id_action, status):
    db.execute("UPDATE Ai_action_log SET status = %s WHERE id_action = %s", (status, id_action))


# =====================================================================
# เรียกเครื่องมือ
# =====================================================================

def ask_confirm(summary):
    print("\n--- ผู้ช่วยขอทำรายการนี้ ---")
    print(summary)
    try:
        answer = input("ยืนยันไหม? (y = ยืนยัน / n = ยกเลิก): ")
    except EOFError:
        return False
    return answer.strip().lower() in YES_WORDS


def run_tool(name, arguments, id_message, id_ai_model, user_texts=()):
    """ทำตามที่โมเดลขอ แล้วคืนผลลัพธ์เป็น dict เสมอ (ไม่ว่าจะสำเร็จหรือไม่)

    user_texts คือข้อความล่าสุดของผู้ใช้ ใช้เช็กว่าราคา ส่วนลด วันที่ มาจากผู้ใช้จริง
    """

    # ----- แบบอ่าน: ทำได้เลย -----
    if name in tools.READ_TOOLS:
        function = tools.READ_TOOLS[name]
        try:
            tools.check_arguments(function, arguments)
            return function(db.ID_BUSINESS, **arguments)
        except tools.ToolError as error:
            return {"ok": False, "error": str(error)}

    if name not in tools.WRITE_TOOLS:
        return {"ok": False, "error": f"ไม่มีเครื่องมือชื่อ '{name}'"}

    # ----- แบบแก้ไข: จด log -> ตรวจค่า -> ถามผู้ใช้ -> ทำจริง -----
    function = tools.WRITE_TOOLS[name]
    id_action = log_action(id_message, id_ai_model, name, arguments)

    try:
        tools.check_arguments(function, arguments)
        summary, do = function(db.ID_BUSINESS, **arguments)
        tools.check_user_said(name, arguments, user_texts)   # กันโมเดลแต่งราคา/ส่วนลด/วันที่เอง
    except tools.ToolError as error:
        set_action_status(id_action, "failed")
        db.commit()
        return {"ok": False, "error": str(error)}

    if not ask_confirm(summary):
        set_action_status(id_action, "rejected")
        db.commit()
        print("ยกเลิกแล้ว ไม่ได้แก้ข้อมูล")
        return {"ok": False, "cancelled": True,
                "error": "ผู้ใช้ไม่ยืนยัน จึงยังไม่ได้ทำรายการนี้"}

    try:
        result = do()
        set_action_status(id_action, "confirmed")
        db.commit()            # แก้ข้อมูลกับเปลี่ยนสถานะ log สำเร็จพร้อมกัน หรือไม่สำเร็จทั้งคู่
    except Exception as error:
        db.rollback()
        set_action_status(id_action, "failed")
        db.commit()
        if isinstance(error, tools.ToolError):
            reason = str(error)
        else:
            reason = "บันทึกลงฐานข้อมูลไม่สำเร็จ"
            print(f"[ข้อผิดพลาดจากฐานข้อมูล] {error}")
        print("ทำรายการไม่สำเร็จ ไม่ได้แก้ข้อมูล")
        return {"ok": False, "error": reason}

    print("บันทึกแล้ว")
    # ใส่ข้อความสรุปที่โค้ดเขียนเองไว้บนสุด โมเดลจะได้เล่าตามนี้ ไม่ต้องตีความตัวเลขเอง
    return {"ok": True, "message": "บันทึกเรียบร้อยแล้ว: " + summary,
            **{key: value for key, value in result.items() if key != "ok"}}


# =====================================================================
# คุยกับโมเดล
# =====================================================================

def build_system_prompt(ai, business):
    today = datetime.date.today()
    tomorrow = today + datetime.timedelta(days=1)
    month_end = today.replace(day=calendar.monthrange(today.year, today.month)[1])
    # คำนวณวันที่ให้โมเดลไว้เลย เพราะโมเดลตัวเล็กนับวันพลาดบ่อย
    return (
        f"{ai['prompt'] or ''}\n\n"
        f"ร้านที่ดูแลอยู่: {business['name_brand']}\n"
        f"วันนี้คือวัน{THAI_WEEKDAYS[today.weekday()]}ที่ {today:%Y-%m-%d} "
        f"พรุ่งนี้คือ {tomorrow:%Y-%m-%d} สิ้นเดือนนี้คือ {month_end:%Y-%m-%d}\n"
        f"เวลาใส่วันที่ให้เครื่องมือ ใช้รูปแบบ YYYY-MM-DD และใช้ปี ค.ศ. เสมอ"
    )


# ---------- แปลงตัวเลขที่เขียนเป็นคำไทยให้เป็นตัวเลข ----------
# โมเดลตัวเล็กอ่านเลขคำไทยพลาดบ่อย เช่น อ่าน "ยี่สิบสี่" เป็น 12 เลยแปลงให้ก่อนส่ง
# แปลงเฉพาะคำที่ตามด้วยหน่วยนับ กันไปแปลงคำอื่นที่หน้าตาคล้ายตัวเลข เช่น "สามารถ" "ห้าง" "เรียบร้อย"
THAI_DIGITS = {"ศูนย์": 0, "หนึ่ง": 1, "เอ็ด": 1, "สอง": 2, "ยี่": 2, "สาม": 3, "สี่": 4,
               "ห้า": 5, "หก": 6, "เจ็ด": 7, "แปด": 8, "เก้า": 9}
THAI_MULTIPLIERS = {"สิบ": 10, "ร้อย": 100, "พัน": 1000, "หมื่น": 10000, "แสน": 100000}
COUNT_UNITS = ["ขวด", "ชิ้น", "ซอง", "ห่อ", "กล่อง", "กระป๋อง", "แพ็ค", "แพ็ก", "โหล", "ลัง",
               "ถุง", "แผ่น", "อัน", "บาท", "เปอร์เซ็นต์", "วัน", "แก้ว", "ชุด", "ก้อน", "ลูก",
               "ตัว", "ใบ", "หน่วย", "กิโล", "ขีด", "คู่", "เม็ด", "ถ้วย"]
_NUMBER_WORDS = sorted(list(THAI_DIGITS) + list(THAI_MULTIPLIERS), key=len, reverse=True)
_THAI_NUMBER = re.compile(
    "((?:" + "|".join(_NUMBER_WORDS) + ")+)(?=\\s*(?:" + "|".join(COUNT_UNITS) + "))"
)
_NUMBER_TOKEN = re.compile("|".join(_NUMBER_WORDS))


def _thai_words_to_int(words):
    total, current, last_was_digit = 0, None, False
    for token in _NUMBER_TOKEN.findall(words):
        if token in THAI_DIGITS:
            if last_was_digit:
                return None          # เช่น "สามสี่" แปลว่าประมาณ 3-4 ไม่ใช่ตัวเลขเดียว ไม่แปลง
            current, last_was_digit = THAI_DIGITS[token], True
        else:
            total += (1 if current is None else current) * THAI_MULTIPLIERS[token]
            current, last_was_digit = None, False
    return total + (current or 0)


def normalize_numbers(text):
    def replace(match):
        value = _thai_words_to_int(match.group(1))
        return match.group(1) if value is None else f" {value} "
    return re.sub(r" {2,}", " ", _THAI_NUMBER.sub(replace, text)).strip()


def recent(history):
    """ตัดประวัติให้เหลือแค่คำสั่งล่าสุด โดยตัดที่ต้นคำสั่งของผู้ใช้เสมอ"""
    starts = [i for i, message in enumerate(history) if message["role"] == "user"]
    if len(starts) <= KEEP_TURNS:
        return history
    return history[starts[-KEEP_TURNS]:]


def extract_text_tool_calls(content):
    """หาคำสั่งเรียกเครื่องมือที่โมเดลพิมพ์ออกมาเป็นข้อความ เช่น
    {"name": "update_stock", "arguments": {...}} แล้วแปลงเป็นการเรียกจริง

    คืน (ข้อความที่เหลือ, รายการคำสั่ง) ถ้าไม่เจอจะคืนข้อความเดิมกับรายการว่าง
    """
    known = set(tools.READ_TOOLS) | set(tools.WRITE_TOOLS)
    decoder = json.JSONDecoder()
    calls, pieces, position = [], [], 0
    for match in re.finditer(r"\{\s*\"name\"", content):
        if match.start() < position:
            continue
        try:
            data, end = decoder.raw_decode(content, match.start())
        except ValueError:
            continue
        name = data.get("name") if isinstance(data, dict) else None
        arguments = data.get("arguments", {}) if isinstance(data, dict) else None
        if name in known and isinstance(arguments, dict):
            calls.append(SimpleNamespace(function=SimpleNamespace(name=name, arguments=arguments)))
            pieces.append(content[position:match.start()])
            position = end
    if not calls:
        return content, []
    pieces.append(content[position:])
    rest = re.sub(r"</?tool_call>|```(?:json)?", "", "".join(pieces))
    return rest.strip(), calls


# ตัวอักษรจีน ญี่ปุ่น เกาหลี และเครื่องหมายแบบเต็มความกว้าง เช่น ，：
FOREIGN_SCRIPT = re.compile(r"[　-ヿ㐀-鿿가-힯＀-￯]+")


def ask_again_in_thai(ai, system_prompt, history):
    """คำตอบมีภาษาอื่นปน: ให้โมเดลตอบใหม่หนึ่งครั้ง ถ้ายังปนอยู่ก็ตัดตัวอักษรนั้นทิ้ง"""
    response = ollama.chat(
        model=ai["model_name"],
        messages=[{"role": "system", "content": system_prompt}] + recent(history) + [
            {"role": "user",
             "content": "คำตอบล่าสุดมีภาษาอื่นปน ช่วยตอบข้อความเดิมใหม่เป็นภาษาไทยล้วน "
                        "ห้ามมีตัวอักษรจีนหรือญี่ปุ่นแม้แต่ตัวเดียว"},
        ],
        options=OPTIONS,
    )
    reply = (response.message.content or "").strip()
    reply = FOREIGN_SCRIPT.sub("", reply)
    return re.sub(r"[ \t]{2,}", " ", reply).strip()


def chat_turn(history, user_text, ai, system_prompt):
    """รับหนึ่งคำสั่งจากผู้ใช้ คืนคำตอบของผู้ช่วย"""
    db.commit()   # เริ่มรอบใหม่ จะได้เห็นข้อมูลล่าสุดที่ส่วนอื่นของแอปแก้ไว้
    id_message = save_message("user", user_text)          # เก็บข้อความตามที่ผู้ใช้พิมพ์จริง
    history.append({"role": "user", "content": normalize_numbers(user_text)})

    for _ in range(MAX_ROUNDS):
        response = ollama.chat(
            model=ai["model_name"],
            messages=[{"role": "system", "content": system_prompt}] + recent(history),
            tools=tools.TOOL_SCHEMAS,
            options=OPTIONS,
        )
        message = response.message
        calls = list(message.tool_calls or [])
        content = message.content or ""
        if not calls:
            # qwen บางครั้งพิมพ์คำสั่งเรียกเครื่องมือออกมาเป็นข้อความแทนที่จะเรียกจริง
            content, calls = extract_text_tool_calls(content)

        entry = {"role": "assistant", "content": content}
        if calls:
            entry["tool_calls"] = [
                {"function": {"name": call.function.name,
                              "arguments": dict(call.function.arguments or {})}}
                for call in calls
            ]
        history.append(entry)

        if not calls:
            reply = content.strip()
            if FOREIGN_SCRIPT.search(reply):
                reply = ask_again_in_thai(ai, system_prompt, history)
                entry["content"] = reply   # ไม่เก็บคำตอบที่มีภาษาอื่นไว้ในประวัติ
            reply = reply or "ขอโทษ ยังตอบไม่ได้ ลองพิมพ์ใหม่อีกครั้ง"
            save_message("assistant", reply)
            return reply

        user_texts = [m["content"] for m in recent(history) if m["role"] == "user"]
        for call in entry["tool_calls"]:
            name = call["function"]["name"]
            result = run_tool(name, call["function"]["arguments"], id_message, ai["id_ai_model"],
                              user_texts=user_texts)
            content = to_json(result)
            history.append({"role": "tool", "tool_name": name, "content": content})
            save_message("tool", f"{name}: {content}")

    reply = "ทำหลายขั้นแล้วยังไม่จบ ลองสั่งทีละอย่างดู"
    save_message("assistant", reply)
    return reply


def main():
    try:
        ai = db.fetch_one(
            "SELECT id_ai_model, model_name, prompt FROM AI ORDER BY id_ai_model DESC LIMIT 1"
        )
        business = db.fetch_one(
            "SELECT name_brand FROM Business_Model WHERE id_business = %s AND id_user = %s",
            (db.ID_BUSINESS, db.ID_USER),
        )
    except Exception as error:
        print(f"ต่อฐานข้อมูลไม่ได้: {error}")
        print("เช็กว่า MySQL เปิดอยู่ และตั้งรหัสผ่านใน DB_PASSWORD แล้ว")
        return
    if ai is None or business is None:
        print("ยังไม่มีข้อมูลตั้งต้น ให้รัน seed.sql ก่อน")
        return

    system_prompt = build_system_prompt(ai, business)
    history = []
    print(f"ผู้ช่วยร้าน {business['name_brand']} ({ai['model_name']}) พร้อมแล้ว พิมพ์ exit เพื่อออก")

    while True:
        try:
            user_text = input("\nคุณ: ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not user_text:
            continue
        if user_text.lower() in EXIT_WORDS:
            break

        mark = len(history)
        try:
            reply = chat_turn(history, user_text, ai, system_prompt)
        except Exception as error:
            del history[mark:]      # ทิ้งรอบที่พัง ไม่ให้ค้างในประวัติ
            try:
                db.rollback()
            except Exception:
                pass
            print(f"เกิดข้อผิดพลาด: {error}")
            print("เช็กว่า Ollama กับ MySQL เปิดอยู่ แล้วลองใหม่")
            continue
        print(f"\nผู้ช่วย: {reply}")


if __name__ == "__main__":
    main()
