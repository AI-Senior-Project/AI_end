"""
บันทึกการทำงานของ AI ลงตาราง ai_log

ตั้งค่าการเชื่อมต่อผ่านตัวแปรแวดล้อม (ไม่ต้องใส่รหัสผ่านในโค้ด):
  SME_DB_HOST      ค่าเริ่มต้น 127.0.0.1
  SME_DB_PORT      ค่าเริ่มต้น 3306
  SME_DB_USER      ค่าเริ่มต้น root
  SME_DB_PASSWORD  ถ้าไม่ได้ตั้ง จะถามตอนเปิดโปรแกรม
  SME_DB_NAME      ค่าเริ่มต้น sme_assistant
  SME_AI_MODEL_ID  id ในตาราง ai_model ของ prompt เวอร์ชันที่ใช้อยู่ (ไม่ใส่ก็ได้)

ถ้าฐานข้อมูลใช้ไม่ได้ โปรแกรมยังทำงานต่อตามปกติ แค่ไม่บันทึก
"""

import getpass
import json
import os
import uuid

try:
    import pymysql
except ImportError:
    pymysql = None


class AILogger:
    def __init__(self):
        self.conn = None
        self.session_id = uuid.uuid4().hex[:16]
        model_id = os.getenv("SME_AI_MODEL_ID")
        self.ai_model_id = int(model_id) if model_id and model_id.isdigit() else None

        if pymysql is None:
            print("(ไม่ได้บันทึก log: ยังไม่ได้ติดตั้ง pymysql)")
            return

        password = os.getenv("SME_DB_PASSWORD")
        if password is None:
            password = getpass.getpass("รหัสผ่าน MySQL สำหรับบันทึก log (Enter เพื่อข้าม): ")
            if password == "":
                print("(ข้ามการบันทึก log)")
                return
        try:
            self.conn = pymysql.connect(
                host=os.getenv("SME_DB_HOST", "127.0.0.1"),
                port=int(os.getenv("SME_DB_PORT", "3306")),
                user=os.getenv("SME_DB_USER", "root"),
                password=password,
                database=os.getenv("SME_DB_NAME", "sme_assistant"),
                charset="utf8mb4",
                autocommit=True,
            )
            print(f"(บันทึก log ลง MySQL แล้ว  session: {self.session_id})")
        except pymysql.err.MySQLError as e:
            print(f"(ไม่ได้บันทึก log: เชื่อมต่อ MySQL ไม่ได้ - {e})")

    def write(self, rec: dict):
        """บันทึก 1 แถว ถ้าพังจะเตือนแล้วไปต่อ ไม่ทำให้โปรแกรมหลักหยุด"""
        if not self.conn:
            return
        j = lambda v: None if v is None else json.dumps(v, ensure_ascii=False)
        try:
            self.conn.ping(reconnect=True)
            with self.conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO ai_log
                       (session_id, ai_model_id, user_message, modes, action, final_mode,
                        business, extracted, confirmed, user_corrected, note)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (
                        self.session_id, self.ai_model_id,
                        rec.get("user_message"),
                        j(rec.get("modes")),
                        rec.get("action"),
                        rec.get("final_mode"),
                        rec.get("business"),
                        j(rec.get("extracted")),
                        j(rec.get("confirmed")),
                        rec.get("user_corrected"),
                        rec.get("note"),
                    ),
                )
        except pymysql.err.MySQLError as e:
            print(f"(บันทึก log ไม่สำเร็จ: {e})")

    def close(self):
        if self.conn:
            self.conn.close()
