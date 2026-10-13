"""ตั้งค่าและตัวช่วยคุยกับฐานข้อมูล MySQL

ไฟล์นี้เป็นที่เดียวที่ต้องแก้เวลาเปลี่ยนรหัสผ่านหรือชื่อฐานข้อมูล
"""

import os

import pymysql
import pymysql.cursors

# ---------- ตั้งค่า ----------
# รหัสผ่านอ่านจากตัวแปร DB_PASSWORD ถ้าไม่ได้ตั้งไว้จะใช้ค่าว่าง (ค่าเริ่มต้นของ XAMPP)
# ตั้งใน PowerShell ได้ด้วย:  $env:DB_PASSWORD = "รหัสผ่านของคุณ"
DB_CONFIG = {
    "host": os.getenv("DB_HOST", "localhost"),
    "port": int(os.getenv("DB_PORT", "3306")),
    "user": os.getenv("DB_USER", "root"),
    "password": os.getenv("DB_PASSWORD", ""),
    "database": os.getenv("DB_NAME", "shop_ai"),
    "charset": "utf8mb4",
}

# ใครกำลังใช้งาน และร้านไหน
# ตอนทำแอปจริง สองค่านี้ต้องมาจากระบบล็อกอิน ห้ามให้ AI เป็นคนกำหนด
ID_USER = 1
ID_BUSINESS = 1

_conn = None


def connect():
    """คืนการเชื่อมต่อฐานข้อมูล (เปิดครั้งเดียวแล้วใช้ต่อ)"""
    global _conn
    if _conn is None:
        _conn = pymysql.connect(
            cursorclass=pymysql.cursors.DictCursor,  # ให้แต่ละแถวออกมาเป็น dict
            autocommit=False,                        # เราสั่ง commit เอง
            **DB_CONFIG,
        )
    return _conn


def fetch_one(sql, params=()):
    """อ่านแถวเดียว คืน dict หรือ None"""
    with connect().cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchone()


def fetch_all(sql, params=()):
    """อ่านหลายแถว คืน list ของ dict"""
    with connect().cursor() as cur:
        cur.execute(sql, params)
        return list(cur.fetchall())


def insert(sql, params=()):
    """เพิ่มแถวใหม่ คืน id ของแถวที่เพิ่ม (ยังไม่ commit)"""
    with connect().cursor() as cur:
        cur.execute(sql, params)
        return cur.lastrowid


def execute(sql, params=()):
    """แก้ไขข้อมูล คืนจำนวนแถวที่ถูกแก้ (ยังไม่ commit)"""
    with connect().cursor() as cur:
        cur.execute(sql, params)
        return cur.rowcount


def commit():
    connect().commit()


def rollback():
    connect().rollback()
