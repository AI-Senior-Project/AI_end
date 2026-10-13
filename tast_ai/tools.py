"""ฟังก์ชันที่ AI เรียกใช้ได้ (tools)

หลักสำคัญ:
- AI แค่บอกว่าอยากเรียกฟังก์ชันไหน ด้วยค่าอะไร โค้ดในไฟล์นี้เป็นคนตรวจและทำจริง
- ทุกฟังก์ชันรับ id_business จากโค้ดเสมอ AI ไม่มีสิทธิ์เลือกร้านเอง
- ตัวเลขทุกตัว (ยอดคงเหลือ ราคาหลังลด) คำนวณในโค้ด ไม่ให้โมเดลคิดเอง

ฟังก์ชันมี 2 แบบ:
- แบบอ่าน (READ_TOOLS)   ทำทันที คืนผลลัพธ์เป็น dict
- แบบแก้ไข (WRITE_TOOLS) ยังไม่ทำทันที แต่คืน (ข้อความสรุป, ฟังก์ชันที่จะทำจริง)
  เพื่อให้ assistant.py เอาข้อความสรุปไปถามผู้ใช้ก่อน พอผู้ใช้ยืนยันค่อยเรียกฟังก์ชันนั้น
"""

import calendar
import datetime
import inspect
import math
import re

import db

MAX_PRICE = 99_999_999.99      # เท่ากับที่ DECIMAL(10,2) เก็บได้
MAX_QUANTITY = 2_000_000_000   # ไม่ให้เกินชนิด INT


class ToolError(Exception):
    """ข้อผิดพลาดที่อธิบายให้โมเดลกับผู้ใช้อ่านได้ เช่น ไม่พบสินค้า"""


# =====================================================================
# ตัวช่วยตรวจค่า
# =====================================================================

def _is_blank(value):
    return value is None or str(value).strip() == ""


def _to_number(value, label):
    """แปลงค่าที่โมเดลส่งมาเป็นตัวเลข (โมเดลตัวเล็กชอบส่งตัวเลขมาเป็นข้อความ)"""
    if isinstance(value, bool) or _is_blank(value):
        raise ToolError(f"{label} ต้องเป็นตัวเลข")
    try:
        number = float(str(value).replace(",", "").strip())
    except ValueError:
        raise ToolError(f"{label} ต้องเป็นตัวเลข แต่ได้รับ '{value}'") from None
    if not math.isfinite(number):
        raise ToolError(f"{label} ต้องเป็นตัวเลข")
    return number


def _to_int(value, label):
    number = _to_number(value, label)
    if number != int(number):
        raise ToolError(f"{label} ต้องเป็นจำนวนเต็ม")
    return int(number)


def _to_price(value, label="ราคา"):
    price = round(_to_number(value, label), 2)
    if price < 0:
        raise ToolError(f"{label} ห้ามติดลบ")
    if price > MAX_PRICE:
        raise ToolError(f"{label} สูงเกินไป")
    return price


def _to_datetime(value, label, end_of_day=False):
    """รับวันที่แบบ YYYY-MM-DD (จะมีเวลาต่อท้ายหรือไม่ก็ได้)"""
    text = "" if value is None else str(value).strip().replace("T", " ")
    result = None
    for pattern in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            result = datetime.datetime.strptime(text, pattern)
            break
        except ValueError:
            pass
    if result is None:
        try:
            result = datetime.datetime.strptime(text, "%Y-%m-%d")
        except ValueError:
            raise ToolError(f"{label} ต้องอยู่ในรูปแบบ YYYY-MM-DD แต่ได้รับ '{value}'") from None
        if end_of_day:
            result = result.replace(hour=23, minute=59, second=59)
    if result.year >= 2400:
        # โมเดลส่งปี พ.ศ. มา แปลงเป็น ค.ศ. ให้
        try:
            result = result.replace(year=result.year - 543)
        except ValueError:
            raise ToolError(f"{label} ไม่ถูกต้อง: '{value}'") from None
    return result


def _money(amount):
    return f"{float(amount):,.2f}"


def _product_view(row):
    """ข้อมูลสินค้าแบบที่ส่งกลับให้โมเดล"""
    return {
        "name": row["name"],
        "quantity": int(row["quantity"]),
        "price": float(row["price"]),
        "type": row["type"],
    }


def _find_product(id_business, product_name):
    """หาสินค้าจากชื่อ ในร้านนี้เท่านั้น

    ลองหาชื่อตรงเป๊ะก่อน ถ้าไม่เจอค่อยหาแบบมีคำนี้อยู่ในชื่อ
    เจอหลายตัวจะไม่เดา แต่ส่งรายชื่อกลับไปให้โมเดลถามผู้ใช้
    """
    if _is_blank(product_name):
        raise ToolError("ต้องระบุชื่อสินค้า")
    name = str(product_name).strip()

    columns = "id_product, name, quantity, price, type"
    row = db.fetch_one(
        f"SELECT {columns} FROM Product WHERE id_business = %s AND name = %s",
        (id_business, name),
    )
    if row:
        return row

    # ใช้ | เป็นตัว escape กันกรณีชื่อมี % หรือ _
    pattern = name.replace("|", "||").replace("%", "|%").replace("_", "|_")
    rows = db.fetch_all(
        f"SELECT {columns} FROM Product "
        "WHERE id_business = %s AND name LIKE %s ESCAPE '|' ORDER BY name LIMIT 6",
        (id_business, f"%{pattern}%"),
    )
    if len(rows) == 1:
        return rows[0]
    if not rows:
        raise ToolError(f"ไม่พบสินค้าชื่อ '{name}' ในร้าน")
    names = ", ".join(r["name"] for r in rows)
    raise ToolError(f"มีสินค้าหลายตัวที่ชื่อคล้าย '{name}': {names} ให้ถามผู้ใช้ว่าหมายถึงตัวไหน")


def _name_taken(id_business, name, except_id=None):
    row = db.fetch_one(
        "SELECT id_product FROM Product WHERE id_business = %s AND name = %s",
        (id_business, name),
    )
    return row is not None and row["id_product"] != except_id


# =====================================================================
# ฟังก์ชันแบบอ่าน
# =====================================================================

def _search_products(id_business, keyword, low_stock_below):
    sql = "SELECT name, quantity, price, type FROM Product WHERE id_business = %s"
    params = [id_business]
    if keyword is not None:
        word = keyword.replace("|", "||").replace("%", "|%").replace("_", "|_")
        sql += " AND name LIKE %s ESCAPE '|'"
        params.append(f"%{word}%")
    if low_stock_below is not None:
        sql += " AND quantity < %s"
        params.append(low_stock_below)
    sql += " ORDER BY name LIMIT 50"
    return db.fetch_all(sql, params)


def list_products(id_business, keyword=None, low_stock_below=None):
    keyword = None if _is_blank(keyword) else str(keyword).strip()
    low = None if _is_blank(low_stock_below) else _to_int(low_stock_below, "low_stock_below")
    rows = _search_products(id_business, keyword, low)
    note = None

    # โมเดลชอบใส่เงื่อนไขเกินมา เช่น ใส่ทั้งประโยคเป็นคำค้น หรือใส่ตัวกรองของใกล้หมดโดยไม่จำเป็น
    # ถ้าใส่สองเงื่อนไขแล้วไม่เจอเลย ลองทีละเงื่อนไข แล้วบอกโมเดลตรง ๆ ว่าเจอแบบไหน
    if not rows and keyword is not None and low is not None:
        by_name = _search_products(id_business, keyword, None)
        if by_name:
            rows = by_name
            note = (f"ไม่มี '{keyword}' ที่เหลือน้อยกว่า {low} ชิ้น "
                    f"รายการนี้คือสินค้าที่ชื่อมีคำว่า '{keyword}' ทั้งหมด")
        else:
            by_low = _search_products(id_business, None, low)
            if by_low:
                rows = by_low
                note = (f"ไม่พบสินค้าที่ชื่อมีคำว่า '{keyword}' "
                        f"รายการนี้คือสินค้าทั้งหมดที่เหลือน้อยกว่า {low} ชิ้น")

    result = {"ok": True, "count": len(rows), "products": [_product_view(r) for r in rows]}
    if note:
        result["note"] = note
    return result


def get_product(id_business, product_name):
    return {"ok": True, "product": _product_view(_find_product(id_business, product_name))}


# =====================================================================
# ฟังก์ชันแบบแก้ไข: คืน (ข้อความสรุป, ฟังก์ชันที่จะทำจริง)
# =====================================================================

def add_product(id_business, name, price, quantity=0, type=None):
    if _is_blank(name):
        raise ToolError("ต้องระบุชื่อสินค้า")
    name = str(name).strip()
    price = _to_price(price)
    quantity = 0 if _is_blank(quantity) else _to_int(quantity, "จำนวน")
    if quantity < 0:
        raise ToolError("จำนวนห้ามติดลบ")
    if quantity > MAX_QUANTITY:
        raise ToolError("จำนวนมากเกินไป")
    product_type = None if _is_blank(type) else str(type).strip()
    if _name_taken(id_business, name):
        raise ToolError(f"มีสินค้าชื่อ '{name}' อยู่แล้ว ถ้าจะเพิ่มจำนวนของเดิม ให้ปรับสต็อกแทน")

    summary = f"เพิ่มสินค้าใหม่ '{name}' ราคา {_money(price)} บาท จำนวน {quantity:,}"
    if product_type:
        summary += f" ประเภท {product_type}"

    def do():
        db.insert(
            "INSERT INTO Product (id_business, name, price, quantity, type) "
            "VALUES (%s, %s, %s, %s, %s)",
            (id_business, name, price, quantity, product_type),
        )
        return {"ok": True, "product": {"name": name, "quantity": quantity,
                                        "price": price, "type": product_type}}

    return summary, do


def edit_product(id_business, product_name, new_name=None, new_price=None, new_type=None):
    product = _find_product(id_business, product_name)
    changes = {}   # ชื่อคอลัมน์ -> ค่าใหม่ (ชื่อคอลัมน์เรากำหนดเอง ไม่ได้มาจากโมเดล)
    lines = []

    if not _is_blank(new_name) and str(new_name).strip() != product["name"]:
        value = str(new_name).strip()
        if _name_taken(id_business, value, except_id=product["id_product"]):
            raise ToolError(f"มีสินค้าชื่อ '{value}' อยู่แล้ว")
        changes["name"] = value
        lines.append(f"ชื่อ: {product['name']} → {value}")

    if not _is_blank(new_price):
        value = _to_price(new_price)
        if value != float(product["price"]):
            changes["price"] = value
            lines.append(f"ราคา: {_money(product['price'])} → {_money(value)} บาท")

    if not _is_blank(new_type) and str(new_type).strip() != (product["type"] or ""):
        value = str(new_type).strip()
        changes["type"] = value
        lines.append(f"ประเภท: {product['type'] or '-'} → {value}")

    if not changes:
        raise ToolError("ไม่มีอะไรให้แก้ ต้องระบุชื่อใหม่ ราคาใหม่ หรือประเภทใหม่ที่ต่างจากเดิม")

    summary = f"แก้ไขสินค้า '{product['name']}'\n  " + "\n  ".join(lines)

    def do():
        assignments = ", ".join(f"{column} = %s" for column in changes)
        db.execute(
            f"UPDATE Product SET {assignments} WHERE id_product = %s AND id_business = %s",
            (*changes.values(), product["id_product"], id_business),
        )
        row = db.fetch_one(
            "SELECT name, quantity, price, type FROM Product WHERE id_product = %s",
            (product["id_product"],),
        )
        return {"ok": True, "product": _product_view(row)}

    return summary, do


def update_stock(id_business, product_name, change):
    product = _find_product(id_business, product_name)
    change = _to_int(change, "จำนวนที่เปลี่ยน")
    if change == 0:
        raise ToolError("จำนวนที่เปลี่ยนต้องไม่เป็น 0")
    old_quantity = int(product["quantity"])
    new_quantity = old_quantity + change
    if new_quantity < 0:
        raise ToolError(
            f"ลดไม่ได้ '{product['name']}' เหลือแค่ {old_quantity:,} แต่ขอลด {abs(change):,}"
        )
    if new_quantity > MAX_QUANTITY:
        raise ToolError("จำนวนมากเกินไป")

    action = "เพิ่ม" if change > 0 else "ลด"
    summary = (f"{action}สต็อก '{product['name']}' {abs(change):,} ชิ้น "
               f"(จาก {old_quantity:,} เป็น {new_quantity:,})")

    def do():
        # บวกลบในคำสั่ง SQL เลย และเช็กซ้ำว่าไม่ติดลบ เผื่อมีคนขายของไประหว่างรอยืนยัน
        changed = db.execute(
            "UPDATE Product SET quantity = quantity + %s "
            "WHERE id_product = %s AND id_business = %s AND quantity + %s >= 0",
            (change, product["id_product"], id_business, change),
        )
        if changed == 0:
            raise ToolError("จำนวนคงเหลือเปลี่ยนไประหว่างรอยืนยัน ทำให้ลดไม่ได้ ลองใหม่อีกครั้ง")
        row = db.fetch_one(
            "SELECT quantity FROM Product WHERE id_product = %s", (product["id_product"],)
        )
        return {"ok": True, "name": product["name"], "change": change,
                "quantity_before": old_quantity, "quantity_after": int(row["quantity"])}

    return summary, do


_DISCOUNT_TYPES = {
    "percent": "percent", "%": "percent", "percentage": "percent", "เปอร์เซ็นต์": "percent",
    "amount": "amount", "baht": "amount", "บาท": "amount",
}


def create_promotion(id_business, product_name, promotion_name, discount_type,
                     discount_value, start_date, end_date):
    product = _find_product(id_business, product_name)
    if _is_blank(promotion_name):
        raise ToolError("ต้องระบุชื่อโปรโมชั่น")
    promotion_name = str(promotion_name).strip()

    kind = _DISCOUNT_TYPES.get(str(discount_type or "").strip().lower())
    if kind is None:
        raise ToolError("discount_type ต้องเป็น 'percent' (ลดเป็นเปอร์เซ็นต์) หรือ 'amount' (ลดเป็นบาท)")

    value = round(_to_number(discount_value, "ส่วนลด"), 2)
    price = float(product["price"])
    if value <= 0:
        raise ToolError("ส่วนลดต้องมากกว่า 0")
    if kind == "percent":
        if value > 100:
            raise ToolError("ส่วนลดแบบเปอร์เซ็นต์ห้ามเกิน 100")
        price_after = round(price * (1 - value / 100), 2)
        discount_text = f"ลด {value:g}%"
    else:
        if value > price:
            raise ToolError(f"ส่วนลด {_money(value)} บาท มากกว่าราคาสินค้า ({_money(price)} บาท)")
        price_after = round(price - value, 2)
        discount_text = f"ลด {_money(value)} บาท"

    start = _to_datetime(start_date, "วันเริ่ม")
    end = _to_datetime(end_date, "วันสิ้นสุด", end_of_day=True)
    if end < start:
        raise ToolError("วันสิ้นสุดต้องไม่ก่อนวันเริ่ม")
    if end < datetime.datetime.now():
        raise ToolError(f"วันสิ้นสุด {end:%Y-%m-%d} ผ่านมาแล้ว ให้เช็กปีและวันที่อีกครั้ง")

    summary = (f"ร่างโปรโมชั่น '{promotion_name}' สำหรับ '{product['name']}'\n"
               f"  {discount_text}: ราคา {_money(price)} → {_money(price_after)} บาท\n"
               f"  ช่วงเวลา: {start:%Y-%m-%d} ถึง {end:%Y-%m-%d}\n"
               f"  สถานะ: ฉบับร่าง (ยังไม่มีผลกับราคาขายจนกว่าจะอนุมัติ)")

    def do():
        id_promotions = db.insert(
            "INSERT INTO Promotions (id_business, id_product, name, discount_type, "
            "discount_value, start_date, end_date) VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (id_business, product["id_product"], promotion_name, kind, value,
             start.strftime("%Y-%m-%d %H:%M:%S"), end.strftime("%Y-%m-%d %H:%M:%S")),
        )
        return {"ok": True, "id_promotions": id_promotions, "promotion_name": promotion_name,
                "product": product["name"], "discount_type": kind, "discount_value": value,
                "price_before": price, "price_after": price_after,
                "start_date": f"{start:%Y-%m-%d}", "end_date": f"{end:%Y-%m-%d}",
                "status": "draft"}

    return summary, do


# =====================================================================
# กันโมเดลแต่งค่าเอง
# =====================================================================

# ค่าที่ผู้ใช้ต้องเป็นคนบอกเท่านั้น ถ้าค่าที่โมเดลส่งมาไม่เคยอยู่ในข้อความของผู้ใช้เลย
# ถือว่าโมเดลแต่งเอง จะไม่ยอมทำ แล้วบอกให้โมเดลกลับไปถามผู้ใช้
USER_DECIDED = {
    "add_product": {"price": "ราคา", "quantity": "จำนวน"},
    "edit_product": {"new_price": "ราคาใหม่"},
    "create_promotion": {"discount_value": "ส่วนลด", "start_date": "วันเริ่ม",
                         "end_date": "วันสิ้นสุด"},
}
_NUMBER_IN_TEXT = re.compile(r"\d+(?:,\d{3})*(?:\.\d+)?")
_DATE_IN_TEXT = re.compile(r"(\d{4})-(\d{1,2})-(\d{1,2})")


def check_user_said(name, arguments, user_texts, today=None):
    """ตรวจว่าค่าที่ผู้ใช้ต้องตัดสินใจเอง มีอยู่ในสิ่งที่ผู้ใช้พิมพ์มาจริง"""
    fields = USER_DECIDED.get(name)
    if not fields:
        return
    today = today or datetime.date.today()
    text = " ".join(user_texts)

    numbers = {float(n.replace(",", "")) for n in _NUMBER_IN_TEXT.findall(text)}
    if "โหล" in text:
        numbers |= {n * 12 for n in numbers} | {12.0}

    dates = set()
    for year, month, day in _DATE_IN_TEXT.findall(text):
        year = int(year) - 543 if int(year) >= 2400 else int(year)
        try:
            dates.add(datetime.date(year, int(month), int(day)))
        except ValueError:
            pass
    month_end = today.replace(day=calendar.monthrange(today.year, today.month)[1])
    relative_days = {"วันนี้": today, "พรุ่งนี้": today + datetime.timedelta(days=1),
                     "มะรืน": today + datetime.timedelta(days=2), "สิ้นเดือน": month_end}
    dates |= {day for word, day in relative_days.items() if word in text}

    missing = []
    for field, label in fields.items():
        value = arguments.get(field)
        if _is_blank(value):
            continue
        if field.endswith("_date"):
            try:
                day = _to_datetime(value, label).date()
            except ToolError:
                continue        # รูปแบบวันที่ผิด ปล่อยให้ตัวตรวจปกติเป็นคนแจ้ง
            # ยอมรับถ้าผู้ใช้พิมพ์วันนั้นไว้ หรืออย่างน้อยพิมพ์เลขวันที่ (เช่น "ถึง 31")
            if day not in dates and float(day.day) not in numbers:
                missing.append(label)
        else:
            try:
                number = float(str(value).replace(",", "").strip())
            except ValueError:
                continue        # ไม่ใช่ตัวเลข ปล่อยให้ตัวตรวจปกติเป็นคนแจ้ง
            if field == "quantity" and number == 0:
                continue
            if number not in numbers:
                missing.append(label)
    if missing:
        raise ToolError(
            f"ผู้ใช้ยังไม่ได้บอก{' '.join(missing)} ห้ามใส่ค่าเอง ให้ถามผู้ใช้ก่อน"
        )


# =====================================================================
# ทะเบียนฟังก์ชัน และคำอธิบายที่ส่งให้โมเดล
# =====================================================================

READ_TOOLS = {
    "list_products": list_products,
    "get_product": get_product,
}

WRITE_TOOLS = {
    "add_product": add_product,
    "edit_product": edit_product,
    "update_stock": update_stock,
    "create_promotion": create_promotion,
}


def check_arguments(function, arguments):
    """เช็กว่าโมเดลส่งชื่อค่ามาครบและไม่มีชื่อแปลกปลอม ก่อนเรียกฟังก์ชันจริง"""
    if not isinstance(arguments, dict):
        raise ToolError("ค่าที่ส่งมาต้องเป็นชุดของชื่อกับค่า")
    allowed = [n for n in inspect.signature(function).parameters if n != "id_business"]
    unknown = [n for n in arguments if n not in allowed]
    if unknown:
        raise ToolError(f"ไม่รู้จักค่า {', '.join(unknown)} ค่าที่ใช้ได้คือ {', '.join(allowed)}")
    try:
        inspect.signature(function).bind(0, **arguments)
    except TypeError:
        raise ToolError(f"ส่งค่ามาไม่ครบ ค่าที่ใช้ได้คือ {', '.join(allowed)}") from None


def _tool(name, description, properties, required):
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {"type": "object", "properties": properties, "required": required},
        },
    }


TOOL_SCHEMAS = [
    _tool(
        "list_products",
        "ดูรายการสินค้าในร้านพร้อมจำนวนคงเหลือและราคา ใช้เมื่อผู้ใช้ถามภาพรวม "
        "หรืออยากรู้ว่าสินค้าไหนใกล้หมด",
        {
            "keyword": {"type": "string",
                        "description": "ชื่อสินค้าที่จะค้น ใส่แค่ชื่อ เช่น ขนมปัง ไม่ใส่คือดูทั้งหมด"},
            "low_stock_below": {"type": "integer",
                                "description": "ใส่เฉพาะตอนผู้ใช้ถามหาของใกล้หมด จะแสดงเฉพาะสินค้าที่เหลือน้อยกว่าจำนวนนี้"},
        },
        [],
    ),
    _tool(
        "get_product",
        "ดูข้อมูลสินค้าหนึ่งตัว: จำนวนคงเหลือ ราคา ประเภท ใช้เมื่อผู้ใช้ถามว่าสินค้าเหลือเท่าไหร่ หรือราคาเท่าไหร่",
        {"product_name": {"type": "string", "description": "ชื่อหรือคำที่ผู้ใช้ใช้เรียกสินค้า เช่น โค้ก ไม่ต้องเป็นชื่อเต็ม ใส่แค่ชื่อสินค้า"}},
        ["product_name"],
    ),
    _tool(
        "add_product",
        "เพิ่มสินค้าใหม่ที่ยังไม่เคยมีในร้าน ต้องรู้ชื่อและราคาจากผู้ใช้ก่อน ถ้าผู้ใช้ยังไม่บอกราคา ห้ามเรียก ให้ถามผู้ใช้"
        " เรียกได้ทันทีเมื่อข้อมูลครบ ระบบจะถามผู้ใช้ยืนยันก่อนบันทึกเอง ไม่ต้องถามผู้ใช้ก่อน",
        {
            "name": {"type": "string", "description": "ชื่อสินค้าใหม่"},
            "price": {"type": "number",
                      "description": "ราคาขายต่อชิ้น หน่วยบาท ต้องเป็นราคาที่ผู้ใช้บอกเท่านั้น ห้ามเดา"},
            "quantity": {"type": "integer", "description": "จำนวนเริ่มต้น ไม่ใส่คือ 0"},
            "type": {"type": "string", "description": "ประเภทสินค้า เช่น เครื่องดื่ม"},
        },
        ["name", "price"],
    ),
    _tool(
        "edit_product",
        "แก้ชื่อ ราคาขาย หรือประเภทของสินค้าที่มีอยู่แล้ว เช่น ขึ้นราคา เปลี่ยนชื่อ ใส่เฉพาะค่าที่ต้องการเปลี่ยน "
        "ห้ามใช้แก้จำนวน ให้ใช้ update_stock แทน"
        " เรียกได้ทันทีเมื่อข้อมูลครบ ระบบจะถามผู้ใช้ยืนยันก่อนบันทึกเอง ไม่ต้องถามผู้ใช้ก่อน",
        {
            "product_name": {"type": "string", "description": "ชื่อหรือคำที่ผู้ใช้ใช้เรียกสินค้า เช่น โค้ก ไม่ต้องเป็นชื่อเต็ม ใส่แค่ชื่อสินค้า"},
            "new_name": {"type": "string", "description": "ชื่อใหม่"},
            "new_price": {"type": "number", "description": "ราคาใหม่ หน่วยบาท"},
            "new_type": {"type": "string", "description": "ประเภทใหม่"},
        },
        ["product_name"],
    ),
    _tool(
        "update_stock",
        "เพิ่มหรือลดจำนวนสินค้าในสต็อก ของเข้าใส่เลขบวก ส่วนขายไป เอาออก ตัดออก ของเสีย หรือหมดอายุ ใส่เลขลบ"
        " เรียกได้ทันทีเมื่อข้อมูลครบ ระบบจะถามผู้ใช้ยืนยันก่อนบันทึกเอง ไม่ต้องถามผู้ใช้ก่อน",
        {
            "product_name": {"type": "string", "description": "ชื่อหรือคำที่ผู้ใช้ใช้เรียกสินค้า เช่น โค้ก ไม่ต้องเป็นชื่อเต็ม ใส่แค่ชื่อสินค้า"},
            "change": {"type": "integer",
                       "description": "จำนวนที่เปลี่ยน เช่น 24 คือเพิ่ม 24 ชิ้น, -5 คือลด 5 ชิ้น"},
        },
        ["product_name", "change"],
    ),
    _tool(
        "create_promotion",
        "ร่างโปรโมชั่นลดราคาให้สินค้าหนึ่งตัว จะถูกบันทึกเป็นฉบับร่าง ยังไม่มีผลกับราคาขาย "
        "ส่วนลดและวันที่ต้องมาจากผู้ใช้เท่านั้น เรียกได้ทันทีเมื่อข้อมูลครบ ระบบจะถามผู้ใช้ยืนยันก่อนบันทึกเอง ไม่ต้องถามผู้ใช้ก่อน",
        {
            "product_name": {"type": "string", "description": "ชื่อหรือคำที่ผู้ใช้ใช้เรียกสินค้า เช่น โค้ก ไม่ต้องเป็นชื่อเต็ม ใส่แค่ชื่อสินค้า"},
            "promotion_name": {"type": "string", "description": "ชื่อโปรโมชั่น"},
            "discount_type": {"type": "string", "enum": ["percent", "amount"],
                              "description": "percent คือลดเป็นเปอร์เซ็นต์, amount คือลดเป็นบาท"},
            "discount_value": {"type": "number", "description": "ตัวเลขส่วนลด เช่น 10"},
            "start_date": {"type": "string", "description": "วันเริ่ม รูปแบบ YYYY-MM-DD"},
            "end_date": {"type": "string", "description": "วันสิ้นสุด รูปแบบ YYYY-MM-DD"},
        },
        ["product_name", "promotion_name", "discount_type", "discount_value",
         "start_date", "end_date"],
    ),
]
