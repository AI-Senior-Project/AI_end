"""
ค้นเว็บ + โหลดเนื้อหาหน้าเว็บ (Python เป็นคนค้น AI ไม่ได้ท่องเน็ตเอง)

ติดตั้ง:  py -m pip install ddgs requests beautifulsoup4
"""

import re

import requests
from bs4 import BeautifulSoup

try:
    from ddgs import DDGS
except ImportError:
    DDGS = None

HEADERS = {"User-Agent": "Mozilla/5.0 (SME-Assistant research)"}


def search(query: str, n: int = 5) -> list:
    """คืน [{title, url, snippet}] ถ้าค้นไม่ได้คืน []"""
    if DDGS is None:
        print("(ค้นเว็บไม่ได้: ยังไม่ได้ติดตั้ง ddgs  ให้รัน py -m pip install ddgs)")
        return []
    try:
        results = DDGS().text(query, region="th-th", max_results=n)
    except Exception as e:  # เน็ตหลุด / โดนจำกัดจำนวนครั้ง
        print(f"(ค้นเว็บไม่สำเร็จ: {e})")
        return []
    return [{"title": r.get("title", ""), "url": r.get("href", ""), "snippet": r.get("body", "")}
            for r in results if r.get("href")]


def fetch_text(url: str, max_chars: int = 80000) -> str:
    """โหลดหน้าเว็บ ตัดเมนู/สคริปต์ทิ้ง เหลือแต่ข้อความ (ทั้งบทความ ส่วนที่จะส่งให้ AI เลือกทีหลัง)"""
    try:
        r = requests.get(url, headers=HEADERS, timeout=10)
        r.raise_for_status()
    except requests.RequestException:
        return ""
    r.encoding = r.apparent_encoding or r.encoding
    soup = BeautifulSoup(r.text, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header", "noscript", "form"]):
        tag.decompose()
    text = re.sub(r"\s+", " ", soup.get_text(" ")).strip()
    return text[:max_chars]
