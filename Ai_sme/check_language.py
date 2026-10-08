import re

CJK = re.compile(r'[\u4e00-\u9fff]')

FALLBACK_REPLY = "ขอโทษครับ ระบบตอบไม่สำเร็จ ช่วยพิมพ์คำถามอีกครั้งได้ไหมครับ"


def has_chinese(text: str) -> bool:
    return bool(CJK.search(text))


def normalize_particle(text: str) -> str:
    text = text.replace("ค่ะ", "ครับ")
    text = re.sub(r"คะ(?=\s*[?\s]|$)", "ครับ", text)
    text = re.sub(r"(ครับ[\s?]*){2,}", "ครับ ", text)
    return text.strip()


def get_clean_reply(generate, max_retries: int = 2) -> str:
    """
    generate = ฟังก์ชันที่เรียกโมเดลแล้วคืนข้อความกลับมา
    ถ้ามีภาษาจีนจะลองใหม่ ครบจำนวนแล้วยังไม่ผ่านก็ใช้ข้อความสำรอง
    """
    for _ in range(max_retries + 1):
        reply = generate()
        if not has_chinese(reply):
            return normalize_particle(reply)
    return FALLBACK_REPLY