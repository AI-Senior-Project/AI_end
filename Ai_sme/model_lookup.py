"""
จับคู่ข้อความที่ผู้ใช้พิมพ์อิสระ (question_model) กับธุรกิจในคลัง data_basic_model

  1) ตรงตัว   : ชื่อที่ผู้ใช้พิมพ์มีอยู่ในคลังพอดี            → ใช้เลย
  2) คล้ายกัน : AI เลือกชื่อที่ใกล้ที่สุดจากคลัง              → ถามผู้ใช้ยืนยันก่อน ไม่ใช้เองอัตโนมัติ
  3) ไม่มี    : ธุรกิจใหม่                                   → เพิ่มลงคลัง (ค้นรายละเอียดจากเน็ตทีหลัง)

ทำไมข้อ 2 ต้องถาม: เคยเจอ "ร้านข้าวมันไก่" ถูกจับเป็น "ร้านอาหารตามสั่ง" มาแล้ว
ถ้าจับคู่ผิด อุปกรณ์ งบ และแผนที่ตามมาจะผิดทั้งหมด
"""

import json
import re

import ollama

from mode_router import extract_business

MODEL = "sme-thai"
MAX_CANDIDATES = 30

SIMILAR_PROMPT = """ผู้ใช้อยากทำธุรกิจ: "__WANT__"
รายชื่อธุรกิจที่มีในระบบ:
__LIST__

ถ้ามีชื่อในรายการที่เป็นธุรกิจเดียวกันจริง ๆ (ขายของแบบเดียวกัน ใช้อุปกรณ์แบบเดียวกัน) ให้ตอบชื่อนั้น
ถ้าแค่คล้าย ๆ แต่ขายของต่างกัน เช่น ไก่ย่าง กับ ไก่ทอด หรือ ข้าวมันไก่ กับ อาหารตามสั่ง ให้ตอบ null
ตอบเป็น JSON เท่านั้น เช่น {"match": "ร้านกาแฟ"} หรือ {"match": null}"""


def _squash(s: str) -> str:
    return re.sub(r"\s+", "", s or "").lower()


def _core(name: str) -> str:
    """ร้านขายยำ / ร้านยำ / ขายยำ → ยำ"""
    core = re.sub(r"^(ร้าน|ธุรกิจ|กิจการ)", "", _squash(name))
    stripped = re.sub(r"^ขาย", "", core)
    return stripped or core


# ---------- ฐานข้อมูล ----------

class ModelRepo:
    def __init__(self, conn, ai_model_id=None):
        self.conn = conn
        self.ai_model_id = ai_model_id

    def _run(self, sql, params=(), fetch=False):
        self.conn.ping(reconnect=True)
        with self.conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchall() if fetch else cur.lastrowid

    def all_names(self) -> list:
        return [r[0] for r in self._run(
            "SELECT DISTINCT name_model FROM data_basic_model WHERE name_model IS NOT NULL", fetch=True)]

    def get(self, name: str):
        rows = self._run(
            "SELECT id_data_sme, name_model FROM data_basic_model WHERE name_model=%s LIMIT 1",
            (name,), fetch=True)
        return {"id": rows[0][0], "name": rows[0][1]} if rows else None

    def add(self, name: str, question_text: str = None, question_model_id=None) -> int:
        """data_basic_model.question_model_id ห้ามว่าง → ต้องมีแถวคำถามของผู้ใช้ก่อน
        ตอนต่อกับแอปจริง แอปจะส่ง question_model_id มาเอง ตัวทดลองนี้เลยสร้างแถวให้"""
        if question_model_id is None:
            question_model_id = self._run(
                "INSERT INTO question_model (ai_model_id, question_model) VALUES (%s,%s)",
                (self.ai_model_id, question_text or name))
        return self._run(
            "INSERT INTO data_basic_model (name_model, question_model_id) VALUES (%s,%s)",
            (name, question_model_id))


class MemoryModelRepo:
    def __init__(self, names=()):
        self.rows = [{"id": i + 1, "name": n} for i, n in enumerate(names)]

    def all_names(self):
        return [r["name"] for r in self.rows]

    def get(self, name):
        return next((dict(r) for r in self.rows if r["name"] == name), None)

    def add(self, name, question_text=None, question_model_id=None):
        self.rows.append({"id": len(self.rows) + 1, "name": name})
        return len(self.rows)


# ---------- จับคู่ ----------

def _exact(want: str, names: list):
    """ตรงตัว ไม่สนเว้นวรรค และไม่สนคำว่า "ร้าน" นำหน้า: "ไก่ย่าง" = "ร้านไก่ย่าง" """
    w = _core(want)
    return next((n for n in names if _core(n) == w), None)


def _candidates(want: str, names: list) -> list:
    """คัดชื่อที่มีตัวอักษรร่วมกันมากที่สุดก่อนส่งให้ AI (7B อ่านรายการยาวไม่ไหว)"""
    w = set(_core(want))
    scored = sorted(names, key=lambda n: -len(w & set(_core(n))))
    return scored[:MAX_CANDIDATES]


def _ask_similar(want: str, candidates: list):
    r = ollama.chat(
        model=MODEL, format="json", options={"temperature": 0},
        messages=[{"role": "user", "content": SIMILAR_PROMPT
                   .replace("__WANT__", want)
                   .replace("__LIST__", "\n".join(f"- {c}" for c in candidates))}],
    )
    try:
        m = json.loads(r["message"]["content"]).get("match")
    except (json.JSONDecodeError, AttributeError):
        return None
    return m if m in candidates else None      # ต้องเป็นชื่อที่มีในรายการจริง ห้ามแต่งชื่อใหม่


def find_model(question_text: str, repo) -> dict:
    """
    คืน {"status": ..., "want": ชื่อที่ผู้ใช้พิมพ์, "match": ชื่อในคลัง}
      found   = ตรงตัว ใช้ได้เลย
      similar = AI เห็นว่าเป็นธุรกิจเดียวกัน → ต้องถามผู้ใช้ก่อน
      new     = ไม่มีในคลัง
      unknown = อ่านไม่ออกว่าธุรกิจอะไร → ต้องถามผู้ใช้
    """
    want = extract_business(question_text)
    if not want:
        return {"status": "unknown", "want": None, "match": None}

    names = repo.all_names()
    hit = _exact(want, names)
    if hit:
        return {"status": "found", "want": want, "match": hit}

    if names:
        sim = _ask_similar(want, _candidates(want, names))
        if sim:
            return {"status": "similar", "want": want, "match": sim}

    return {"status": "new", "want": want, "match": None}


def confirm_text(result: dict) -> str:
    return (f"ในระบบมีข้อมูล \"{result['match']}\" อยู่ครับ "
            f"ธุรกิจที่คุณอยากทำ (\"{result['want']}\") คือแบบเดียวกันไหมครับ (y/n)")
