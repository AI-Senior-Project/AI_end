"""
เลือกโหมดของคำถาม: cashflow / profit / bep / policy / startup_plan / unclear

แบ่งงาน:
- AI ตอบแค่ "เรื่องหลักเรื่องเดียว" ของข้อความ (งานนี้ 7B ทำได้แม่น)
- Python ตัดสินว่าเป็นคำถามปนกันไหม:
    1) ข้อความที่มี " แล้ว" คั่น → แยกเป็นท่อน ส่ง AI ดูทีละท่อน
    2) ผู้ใช้บอกว่า "อยากเปิด/จะเปิด" แต่ถามเรื่องตัวเลข → เติม startup_plan
- resolve() ตัดสินว่าจะไปโหมดไหน หรือถามกลับ
"""

import json
import re
import ollama

MODEL = "sme-thai"

MODES = ("cashflow", "profit", "bep", "policy", "startup_plan", "unclear")
CALC_MODES = ("bep", "profit", "cashflow")

MODE_LABELS = {
    "cashflow": "ดูเงินสดเข้า-ออก ว่าเงินจะพอไหม",
    "profit": "คำนวณกำไร-ขาดทุน",
    "bep": "หาจุดคุ้มทุน ว่าต้องขายเท่าไหร่ถึงไม่ขาดทุน",
    "policy": "เรื่องใบอนุญาต ภาษี และการจดทะเบียน",
    "startup_plan": "วางแผนเริ่มเปิดธุรกิจ",
}

SYSTEM = """คุณมีหน้าที่เดียว คือจัดประเภทคำถามของผู้ใช้ ตอบเป็น JSON เท่านั้น เช่น {"mode": "bep"}

ให้ดูว่าผู้ใช้ "อยากรู้อะไร" ห้ามตัดสินจากคำที่อยู่ในประโยค
เพราะคำอย่าง ต้นทุนคงที่ ค่าเช่า เปิดกี่วัน ขายวันละ งบ อาจอยู่ในคำถามได้ทุกประเภท
ถ้าผู้ใช้เล่าว่าอยากเปิดร้าน แล้วถามคำถามเฉพาะ เช่น ต้องขายกี่ชิ้นถึงคุ้ม ให้ตอบตามคำถามเฉพาะนั้น

ประเภท:
- bep = อยากรู้ว่าต้องขายกี่ชิ้น/กี่จาน/กี่แก้ว/ยอดเท่าไหร่ ถึงจะคุ้มทุน คืนทุน ไม่ขาดทุน หรือพอจ่ายค่าใช้จ่าย
- profit = มียอดขายและค่าใช้จ่ายของช่วงเวลาหนึ่งแล้ว อยากรู้ว่ากำไรหรือขาดทุนเท่าไหร่ หรือกำไรจะเปลี่ยนไปแค่ไหน
- cashflow = อยากรู้เรื่องเงินสดเข้า-ออกตามเวลา เงินจะพอไหม เงินจะหมดเมื่อไหร่ หมุนเงินทันไหม
- policy = ถามเรื่องใบอนุญาต ภาษี การจดทะเบียน กฎหมาย ข้อบังคับ
- startup_plan = ยังไม่มีร้าน อยากเริ่มธุรกิจ บอกเป้าหมาย งบ หรือของที่มี โดยไม่ได้ถามตัวเลขเฉพาะ หรือถามว่าควรเริ่มยังไง
- unclear = ทักทาย คุยเล่น หรือไม่เกี่ยวกับธุรกิจ หรืออ่านแล้วไม่รู้ว่าอยากรู้อะไร"""

FEW_SHOT = [
    ("ค่าเช่ากับค่าแรงรวมเดือนละ 25000 ร้านเปิด 25 วัน ต้องขายวันละกี่ชามถึงจะไม่ขาดทุน", "bep"),
    ("ค่าเช่ากับค่าแรงรวมเดือนละ 25000 ร้านเปิด 25 วัน ตอนนี้เหลือเงิน 20000 จะอยู่ได้อีกกี่เดือน", "cashflow"),
    ("ร้านเปิด 25 วัน ขายได้วันละ 3500 ค่าใช้จ่ายทั้งเดือน 60000 เดือนนี้ได้กำไรเท่าไหร่", "profit"),
    ("ขายแก้วละ 40 ต้นทุนแก้วละ 18 ต้องขายกี่แก้วถึงจะคืนทุนค่าเครื่อง", "bep"),
    ("ถ้าลดราคาลงแก้วละ 5 บาท กำไรต่อเดือนจะหายไปเท่าไหร่", "profit"),
    ("ลูกค้าร้านส่งโอนเงินปลายเดือน แต่ต้องจ่ายค่าของทุกสัปดาห์ เงินจะขาดมือไหม", "cashflow"),
    ("ขายขนมหน้าบ้านต้องเสียภาษีไหม", "policy"),
    ("อยากเปิดร้านกาแฟเล็ก ๆ มีเงิน 80000 ต้องเริ่มยังไง", "startup_plan"),
    ("อยากเปิดร้านข้าวแกงหน้าตลาด มีงบ 70000 มีหม้อหุงข้าวกับโต๊ะอยู่แล้ว", "startup_plan"),
    ("อยากเปิดร้านก๋วยเตี๋ยว มีเงินแสนนึง ต้องขายวันละกี่ชามถึงจะคืนทุน", "bep"),
    ("ขอบคุณครับ", "unclear"),
]

# ผู้ใช้บอกว่ากำลังจะเริ่มธุรกิจ (ไม่นับ "เปิดร้าน..." เฉย ๆ เพราะคนมีร้านแล้วก็พูดได้)
START_RE = re.compile(r"อยากเปิด|จะเปิด|อยากทำร้าน|อยากทำธุรกิจ|อยากเริ่ม|เริ่มธุรกิจ|อยากมีร้าน")

# คำเชื่อมคำถามข้อที่สอง: " แล้ว" ที่มีเว้นวรรคนำหน้า (กันไม่ให้ตัด "มีตู้เย็นแล้ว")
SPLIT_RE = re.compile(r"\s+แล้ว|\?")

BUSINESS_PROMPT = """คัดลอกชื่อประเภทธุรกิจจากข้อความของผู้ใช้ ตอบเป็น JSON เท่านั้น
ต้องคัดลอกคำตามที่ผู้ใช้พิมพ์มาเป๊ะ ๆ ห้ามเปลี่ยนเป็นคำอื่น ห้ามจัดกลุ่มเอง
ถ้าพูดแค่ "ร้าน" "ธุรกิจ" "กิจการ" โดยไม่บอกว่าขายอะไร หรือไม่ได้พูดถึงเลย ให้ตอบ {"business": null} ห้ามเดา"""

BUSINESS_FEW_SHOT = [
    ("อยากเปิดร้านข้าวมันไก่แถวบ้าน", "ร้านข้าวมันไก่"),
    ("จะเปิดร้านทำเล็บ มีงบสามหมื่น", "ร้านทำเล็บ"),
    ("อยากเปิดร้านงบ 50000", None),
]


def _chat_json(messages):
    r = ollama.chat(model=MODEL, format="json", options={"temperature": 0}, messages=messages)
    try:
        return json.loads(r["message"]["content"])
    except json.JSONDecodeError:
        return {}


def classify_one(text: str, max_retries: int = 1) -> str:
    """AI บอกเรื่องหลักเรื่องเดียว อ่านไม่ออกคืน 'unclear'"""
    msgs = [{"role": "system", "content": SYSTEM}]
    for q, mode in FEW_SHOT:
        msgs.append({"role": "user", "content": q})
        msgs.append({"role": "assistant", "content": json.dumps({"mode": mode})})
    msgs.append({"role": "user", "content": text})

    for _ in range(max_retries + 1):
        mode = str(_chat_json(msgs).get("mode", "")).strip().lower()
        if mode in MODES:
            return mode
    return "unclear"


def split_questions(msg: str) -> list:
    parts = [p.strip() for p in SPLIT_RE.split(msg)]
    return [p for p in parts if len(p) >= 4] or [msg]


def detect_modes(msg: str) -> list:
    """คืนรายการเรื่องที่เจอ เรียงลำดับ ไม่ซ้ำ"""
    modes = []
    for part in split_questions(msg):
        m = classify_one(part)
        if m not in modes:
            modes.append(m)

    if len(modes) > 1 and "unclear" in modes:
        modes.remove("unclear")

    # บอกว่าจะเริ่มธุรกิจ แต่ถามเรื่องตัวเลข → มีเรื่อง startup_plan ปนอยู่ด้วย
    if START_RE.search(msg) and "startup_plan" not in modes and any(m in CALC_MODES for m in modes):
        modes.insert(0, "startup_plan")

    return modes


def choose_mode(user_msg: str) -> str:
    """แบบโหมดเดียว คำถามหลายเรื่องคืน 'mixed'"""
    modes = detect_modes(user_msg)
    return modes[0] if len(modes) == 1 else "mixed"


def extract_business(user_msg: str):
    msgs = [{"role": "system", "content": BUSINESS_PROMPT}]
    for q, b in BUSINESS_FEW_SHOT:
        msgs.append({"role": "user", "content": q})
        msgs.append({"role": "assistant", "content": json.dumps({"business": b}, ensure_ascii=False)})
    msgs.append({"role": "user", "content": user_msg})

    b = _chat_json(msgs).get("business")
    if not b or not isinstance(b, str):
        return None
    b = b.strip()
    if b in ("ร้าน", "ธุรกิจ", "กิจการ", "null"):
        return None
    # ด่านตรวจ: ชื่อที่ได้ต้องมีอยู่จริงในข้อความผู้ใช้ ไม่งั้นถือว่า AI แต่งเอง
    compact = user_msg.replace(" ", "")
    if b.replace(" ", "") not in compact:
        return None
    return b


OWNED_PROMPT = """ดึงรายการอุปกรณ์ที่ผู้ใช้บอกว่า "มีอยู่แล้ว" จากข้อความ ตอบเป็น JSON เท่านั้น
คัดลอกชื่อตามที่ผู้ใช้พิมพ์มา แยกทีละชิ้น ห้ามเปลี่ยนคำ ห้ามเติมชิ้นที่ผู้ใช้ไม่ได้พูด
ไม่นับเงิน งบ หรือทำเล ถ้าไม่มีให้ตอบ {"owned": []}"""

OWNED_FEW_SHOT = [
    ("อยากเปิดร้านไก่ย่าง งบ5000 มีโต๊ะพับและตู้เย็นเล็ก", ["โต๊ะพับ", "ตู้เย็นเล็ก"]),
    ("มีหม้อหุงข้าวกับโต๊ะอยู่แล้ว", ["หม้อหุงข้าว", "โต๊ะ"]),
    ("อยากเปิดร้านกาแฟ มีงบ 80000", []),
]


def extract_owned(user_msg: str) -> list:
    """อุปกรณ์ที่ผู้ใช้บอกว่ามีแล้ว ต้องมีคำนั้นอยู่จริงในข้อความ (กัน AI แต่งเพิ่ม)"""
    msgs = [{"role": "system", "content": OWNED_PROMPT}]
    for q, owned in OWNED_FEW_SHOT:
        msgs.append({"role": "user", "content": q})
        msgs.append({"role": "assistant", "content": json.dumps({"owned": owned}, ensure_ascii=False)})
    msgs.append({"role": "user", "content": user_msg})

    raw = _chat_json(msgs).get("owned")
    compact = user_msg.replace(" ", "")
    out = []
    for name in raw if isinstance(raw, list) else []:
        name = str(name).strip()
        if 2 <= len(name) <= 40 and name.replace(" ", "") in compact and name not in out:
            out.append(name)
    # AI มักดึงไม่ครบเวลามีหลายชิ้นในวลีเดียว ("โต๊ะพับกับถาดวาง" → ได้แค่ถาดวาง)
    # ให้ Python แตกวลี "มี..." ที่มีของที่ AI เจอ ออกเป็นทุกชิ้น
    for part in _owned_phrases(user_msg):
        if any(o in part for o in out):
            for piece in re.split(r"กับ|และ|,|、|\s+", part):
                piece = piece.strip()
                if 2 <= len(piece) <= 40 and not re.search(r"\d", piece) and piece not in out:
                    out.append(piece)
    return out


def _owned_phrases(msg: str) -> list:
    """วลีหลังคำว่า "มี" ตัดที่ "แล้ว/อยู่แล้ว" เช่น "มีโต๊ะพับกับถาดวางแล้ว" → "โต๊ะพับกับถาดวาง" """
    phrases = []
    for seg in msg.split("มี")[1:]:
        seg = re.split(r"อยู่แล้ว|แล้ว", seg)[0].strip()
        if seg and not seg.startswith(("งบ", "เงิน", "ทุน")):
            phrases.append(seg)
    return phrases


def resolve(modes: list, business_known: bool):
    """
    ตัดสินว่าจะไปโหมดไหน (ไม่ใช้ AI)
    คืน ("go", mode) หรือ ("ask", [modes ให้เลือก])
    """
    if len(modes) == 1:
        return ("go", modes[0])

    remaining = list(modes)
    if business_known and "startup_plan" in remaining:
        remaining.remove("startup_plan")

    if len(remaining) == 1:
        return ("go", remaining[0])
    return ("ask", remaining)


def ask_back_text(modes: list) -> str:
    lines = [f"คำถามนี้มี {len(modes)} เรื่องครับ อยากให้ช่วยเรื่องไหนก่อนครับ"]
    for i, m in enumerate(modes, 1):
        lines.append(f"  {i}) {MODE_LABELS.get(m, m)}")
    lines.append("พิมพ์เลขที่ต้องการได้เลยครับ")
    return "\n".join(lines)
