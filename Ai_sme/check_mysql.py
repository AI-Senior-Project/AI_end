"""
เช็คว่า MySQL ของฝั่ง AI ใช้งานได้ไหม  รัน:  py check_mysql.py
ต้องติดตั้งก่อน:  py -m pip install pymysql

สคริปต์นี้ไม่แก้ข้อมูลจริง: ทดสอบเขียน/อ่านในตารางชั่วคราว (TEMPORARY) ซึ่งหายเองเมื่อปิดการเชื่อมต่อ
รหัสผ่านพิมพ์ตอนรัน ไม่ถูกบันทึกไว้ที่ไหน
"""

import getpass
import sys

try:
    import pymysql
except ImportError:
    print("ยังไม่ได้ติดตั้ง pymysql  ให้รัน:  py -m pip install pymysql")
    sys.exit(1)


def ask(label, default):
    v = input(f"{label} [{default}]: ").strip()
    return v or default


def step(ok, text):
    print(f"[{'ผ่าน' if ok else 'ไม่ผ่าน'}] {text}")
    return ok


def main():
    host = ask("host", "localhost")
    port = int(ask("port", "3306"))
    user = ask("user", "root")
    password = getpass.getpass("password (พิมพ์แล้วจะไม่ขึ้นบนจอ): ")
    database = ask("ชื่อ database", "")
    print()

    # 1) เชื่อมต่อ
    try:
        conn = pymysql.connect(host=host, port=port, user=user, password=password,
                               database=database or None, charset="utf8mb4")
    except pymysql.err.OperationalError as e:
        step(False, f"เชื่อมต่อไม่ได้: {e}")
        print("\nเช็ค: MySQL เปิดอยู่ไหม, host/port ถูกไหม, user/รหัสผ่านถูกไหม")
        return
    step(True, "เชื่อมต่อได้")

    with conn.cursor() as cur:
        cur.execute("SELECT VERSION()")
        print(f"       MySQL เวอร์ชัน {cur.fetchone()[0]}")

        if not database:
            cur.execute("SHOW DATABASES")
            names = [r[0] for r in cur.fetchall()
                     if r[0] not in ("information_schema", "mysql", "performance_schema", "sys")]
            print("\nยังไม่ได้เลือก database  ที่มีอยู่:", ", ".join(names) or "(ไม่มี)")
            print("รันใหม่แล้วใส่ชื่อ database ของฝั่ง AI ครับ")
            conn.close()
            return

        # 2) charset ของ database (ต้องเป็น utf8mb4 ถึงเก็บภาษาไทย/อีโมจิได้ครบ)
        cur.execute("SELECT @@character_set_database, @@collation_database")
        cs, coll = cur.fetchone()
        step(cs == "utf8mb4", f"charset ของ database = {cs} ({coll})"
             + ("" if cs == "utf8mb4" else "  ← ควรเป็น utf8mb4"))

        # 3) ตารางที่มีอยู่
        cur.execute("SHOW TABLES")
        tables = [r[0] for r in cur.fetchall()]
        print(f"\nตารางที่มี ({len(tables)}):")
        for t in tables:
            cur.execute(f"SHOW FULL COLUMNS FROM `{t}`")
            cols = cur.fetchall()
            print(f"  {t}")
            for c in cols:
                name, ctype, coll_c = c[0], c[1], c[2]
                warn = ""
                if coll_c and not coll_c.startswith("utf8mb4"):
                    warn = "  ← ภาษาไทยอาจเพี้ยน ควรเป็น utf8mb4"
                print(f"      - {name}: {ctype}" + (f" ({coll_c})" if coll_c else "") + warn)
        if not tables:
            print("  (ยังไม่มีตาราง)")

        # 4) ลองเขียนแล้วอ่านภาษาไทยกลับมา ในตารางชั่วคราว
        print()
        thai = "อยากเปิดร้านข้าวมันไก่ งบ 50000 ต้องขายวันละกี่จานถึงคุ้มทุน"
        try:
            cur.execute("CREATE TEMPORARY TABLE _ai_check (msg TEXT) CHARACTER SET utf8mb4")
            cur.execute("INSERT INTO _ai_check (msg) VALUES (%s)", (thai,))
            cur.execute("SELECT msg FROM _ai_check")
            back = cur.fetchone()[0]
            step(back == thai, "เขียนแล้วอ่านภาษาไทยกลับมาได้ตรงกัน"
                 + ("" if back == thai else f"\n       ได้กลับมาเป็น: {back}"))
        except pymysql.err.MySQLError as e:
            step(False, f"ลองเขียนข้อมูลไม่ได้: {e}")
            print("       user นี้อาจไม่มีสิทธิ์ INSERT / CREATE TEMPORARY TABLES")

    conn.close()
    print("\nเสร็จแล้ว แคปผลนี้มาได้เลยครับ")


if __name__ == "__main__":
    main()
