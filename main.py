import telebot
import json
import os
import re
import logging
from datetime import datetime

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

TOKEN = os.getenv("TOKEN")
ADMIN_ID = 1206122142
BOT_USERNAME = "azk_shop_idish_bot"

if not TOKEN:
    raise ValueError("TOKEN environment variable is not set.")

bot = telebot.TeleBot(TOKEN, parse_mode="HTML")

# ── JSON management ───────────────────────────────────────────────────────────

def ensure_file(name, default):
    if not os.path.exists(name):
        with open(name, "w", encoding="utf-8") as f:
            json.dump(default, f, ensure_ascii=False, indent=2)

ensure_file("users.json", [])
ensure_file("referrals.json", {})
ensure_file("orders.json", [])
ensure_file("products.json", {
    "1": {"name": "Likopcha", "price": 15000, "stock": 50, "sold": 0, "limit": 20, "category": "Ro'zg'or uchun", "image_url": ""},
    "2": {"name": "Krujka", "price": 25000, "stock": 30, "sold": 0, "limit": 20, "category": "Sovg'a uchun", "image_url": ""}
})
ensure_file("alerts.json", {})
ensure_file("cart.json", {})

def load_json(name):
    with open(name, "r", encoding="utf-8") as f:
        return json.load(f)

def save_json(name, data):
    with open(name, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

# ── State ─────────────────────────────────────────────────────────────────────

waiting_for_broadcast = set()
checkout_data = {}

# ── Helpers ───────────────────────────────────────────────────────────────────

def is_admin(chat_id):
    return chat_id == ADMIN_ID

def is_valid_uzbek_phone(phone):
    phone = phone.strip().replace(" ", "").replace("-", "")
    return bool(re.match(r'^(\+998|998)?\d{9}$', phone))

def check_low_stock():
    try:
        products = load_json("products.json")
        alerts = load_json("alerts.json")
        for pid, p in products.items():
            if p["stock"] < p["limit"]:
                if alerts.get(pid) != p["stock"]:
                    bot.send_message(
                        ADMIN_ID,
                        f"⚠️ <b>Ogohlantirish!</b>\n\n📦 {p['name']} omborda <b>{p['stock']} ta</b> qoldi!"
                    )
                    alerts[pid] = p["stock"]
        save_json("alerts.json", alerts)
    except Exception as e:
        logger.error(f"check_low_stock error: {e}")

# ── Keyboards ─────────────────────────────────────────────────────────────────

def admin_keyboard():
    markup = telebot.types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(
        telebot.types.KeyboardButton("📊 Statistika"),
        telebot.types.KeyboardButton("📦 Mahsulotlar"),
        telebot.types.KeyboardButton("🛒 Zakazlar"),
        telebot.types.KeyboardButton("👥 Referral"),
        telebot.types.KeyboardButton("📣 Reklama"),
        telebot.types.KeyboardButton("🏆 Top Mahsulotlar"),
        telebot.types.KeyboardButton("👤 Userlar"),
    )
    return markup

def customer_keyboard():
    markup = telebot.types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(
        telebot.types.KeyboardButton("🛍 Mahsulotlar"),
        telebot.types.KeyboardButton("🛒 Savat"),
        telebot.types.KeyboardButton("📦 Mening buyurtmam"),
    )
    return markup

ALLOWED_CATEGORIES = ["Ro'zg'or uchun", "Sovg'a uchun"]
CATEGORY_LABELS   = {"Ro'zg'or uchun": "🏠 Ro'zg'or uchun", "Sovg'a uchun": "🎁 Sovg'a uchun"}

def categories_keyboard():
    markup = telebot.types.InlineKeyboardMarkup(row_width=1)
    for cat in ALLOWED_CATEGORIES:
        markup.add(telebot.types.InlineKeyboardButton(CATEGORY_LABELS[cat], callback_data=f"cat:{cat}"))
    return markup

def products_in_category_keyboard(category):
    prods = load_json("products.json")
    markup = telebot.types.InlineKeyboardMarkup(row_width=1)
    for pid, p in prods.items():
        if p.get("category") == category and p["stock"] > 0:
            markup.add(telebot.types.InlineKeyboardButton(
                f"{p['name']} — {p['price']:,} so'm",
                callback_data=f"prod:{pid}"
            ))
    markup.add(telebot.types.InlineKeyboardButton("⬅️ Kategoriyalar", callback_data="back:cats"))
    return markup

def product_detail_keyboard(pid, qty=1):
    markup = telebot.types.InlineKeyboardMarkup(row_width=3)
    markup.add(
        telebot.types.InlineKeyboardButton("➖", callback_data=f"qty:{pid}:{max(1, qty - 1)}"),
        telebot.types.InlineKeyboardButton(str(qty), callback_data="noop"),
        telebot.types.InlineKeyboardButton("➕", callback_data=f"qty:{pid}:{qty + 1}"),
    )
    markup.add(telebot.types.InlineKeyboardButton("🛒 Savatga qo'shish", callback_data=f"add:{pid}:{qty}"))
    prods = load_json("products.json")
    cat = prods.get(pid, {}).get("category", "")
    markup.add(telebot.types.InlineKeyboardButton("⬅️ Orqaga", callback_data=f"cat:{cat}"))
    return markup

def cart_keyboard():
    markup = telebot.types.InlineKeyboardMarkup(row_width=1)
    markup.add(telebot.types.InlineKeyboardButton("✅ Zakaz berish", callback_data="checkout"))
    markup.add(telebot.types.InlineKeyboardButton("🗑 Savatni tozalash", callback_data="clear_cart"))
    return markup

# ── /start ────────────────────────────────────────────────────────────────────

@bot.message_handler(commands=['start'])
def start(message):
    try:
        users = load_json("users.json")
        refs = load_json("referrals.json")
        chat_id = message.chat.id
        parts = message.text.split()
        ref_id = parts[1] if len(parts) > 1 else None

        if chat_id not in users:
            users.append(chat_id)
            save_json("users.json", users)
            if ref_id and ref_id != str(chat_id):
                if ref_id not in refs:
                    refs[ref_id] = []
                if chat_id not in refs[ref_id]:
                    refs[ref_id].append(chat_id)
                save_json("referrals.json", refs)

        ref_link = f"https://t.me/{BOT_USERNAME}?start={chat_id}"

        if is_admin(chat_id):
            bot.send_message(
                chat_id,
                f"👋 <b>Salom, Admin!</b>\n\n"
                f"🔗 Referral linkingiz:\n<code>{ref_link}</code>\n\n"
                f"⚙️ Admin panelni ochish uchun /panel yuboring.",
                reply_markup=customer_keyboard()
            )
        else:
            bot.send_message(
                chat_id,
                f"👋 <b>Salom!</b>\n\n"
                f"Botga xush kelibsiz.\n\n"
                f"🔗 Referral linkingiz:\n<code>{ref_link}</code>",
                reply_markup=customer_keyboard()
            )
        logger.info(f"/start from {chat_id}")
    except Exception as e:
        logger.error(f"/start error: {e}")

# ── /panel ────────────────────────────────────────────────────────────────────

@bot.message_handler(commands=['panel'])
def panel(message):
    if not is_admin(message.chat.id):
        return
    try:
        bot.send_message(
            message.chat.id,
            "🛠 <b>Admin panel</b>\nQuyidagi tugmalardan foydalaning:",
            reply_markup=admin_keyboard()
        )
    except Exception as e:
        logger.error(f"/panel error: {e}")

# ── Admin commands ────────────────────────────────────────────────────────────

@bot.message_handler(commands=['admin'])
def admin_help(message):
    if not is_admin(message.chat.id):
        return
    try:
        bot.send_message(message.chat.id,
            "🛠 <b>Admin buyruqlari</b>\n\n"
            "/stat — obunachilar soni\n"
            "/userlist — foydalanuvchilar ro'yxati\n"
            "/referrals — referral hisobot\n"
            "/products — mahsulotlar va daromad\n"
            "/topproducts — eng ko'p sotilgan\n"
            "/orders — oxirgi zakazlar\n"
            "/addproduct id|nom|narx|soni|limit|kategoriya|rasm_url\n"
            "/sell id|mijoz|soni\n"
            "/broadcast xabar — barchaga yuborish\n"
            "/panel — admin panel"
        )
    except Exception as e:
        logger.error(f"/admin error: {e}")

@bot.message_handler(commands=['stat'])
def stat(message):
    if not is_admin(message.chat.id):
        return
    try:
        users = load_json("users.json")
        bot.send_message(message.chat.id, f"👥 Obunachilar: <b>{len(users)}</b>")
    except Exception as e:
        logger.error(f"/stat error: {e}")

@bot.message_handler(commands=['referrals'])
def referrals(message):
    if not is_admin(message.chat.id):
        return
    try:
        refs = load_json("referrals.json")
        if not refs:
            bot.send_message(message.chat.id, "Referral yo'q.")
            return
        text = "📊 <b>Referral hisobot</b>\n\n"
        for rid, people in refs.items():
            text += f"👤 <code>{rid}</code> → {len(people)} ta odam\n"
        bot.send_message(message.chat.id, text)
    except Exception as e:
        logger.error(f"/referrals error: {e}")

@bot.message_handler(commands=['products'])
def products_cmd(message):
    if not is_admin(message.chat.id):
        return
    try:
        prods = load_json("products.json")
        total = 0
        text = "📦 <b>Mahsulotlar</b>\n\n"
        for pid, p in prods.items():
            revenue = p["sold"] * p["price"]
            total += revenue
            text += (
                f"🆔 {pid} | 📌 {p['name']} | 🏷 {p.get('category', '—')}\n"
                f"💵 {p['price']:,} so'm | 📦 Qoldiq: {p['stock']} | 🛒 Sotilgan: {p['sold']}\n"
                f"💰 Daromad: {revenue:,} so'm\n\n"
            )
        text += f"💸 <b>Umumiy daromad:</b> {total:,} so'm"
        bot.send_message(message.chat.id, text)
        check_low_stock()
    except Exception as e:
        logger.error(f"/products error: {e}")

@bot.message_handler(commands=['orders'])
def orders_cmd(message):
    if not is_admin(message.chat.id):
        return
    try:
        ords = load_json("orders.json")
        prods = load_json("products.json")
        if not ords:
            bot.send_message(message.chat.id, "🛒 Zakazlar yo'q.")
            return
        text = "🛒 <b>Oxirgi zakazlar</b>\n\n"
        for o in ords[-10:]:
            if "items" in o:
                items_text = ", ".join([f"{i['name']} x{i['qty']}" for i in o["items"]])
                text += (
                    f"📅 {o['date']} | 👤 {o.get('name', '?')}\n"
                    f"📞 {o.get('phone', '—')} | 📍 {o.get('address', '—')}\n"
                    f"📦 {items_text}\n"
                    f"💰 {o.get('total', 0):,} so'm\n\n"
                )
            else:
                name = prods.get(o.get("product_id", ""), {}).get("name", "Noma'lum")
                text += f"📅 {o['date']}\n👤 {o.get('customer', '?')}\n📦 {name}\n🔢 {o.get('quantity', '?')} ta\n\n"
        bot.send_message(message.chat.id, text)
    except Exception as e:
        logger.error(f"/orders error: {e}")

@bot.message_handler(commands=['addproduct'])
def addproduct(message):
    if not is_admin(message.chat.id):
        return
    try:
        data = message.text.replace("/addproduct", "", 1).strip().split("|")
        pid       = data[0].strip()
        name      = data[1].strip()
        price     = int(data[2].strip())
        stock     = int(data[3].strip())
        limit     = int(data[4].strip())
        category  = data[5].strip() if len(data) > 5 else "Boshqa"
        image_url = data[6].strip() if len(data) > 6 else ""

        if category not in ALLOWED_CATEGORIES:
            bot.send_message(
                message.chat.id,
                f"❌ Noto'g'ri kategoriya: <b>{category}</b>\n\n"
                f"Faqat quyidagilar ruxsat etilgan:\n"
                + "\n".join(f"• {c}" for c in ALLOWED_CATEGORIES)
            )
            return

        prods = load_json("products.json")
        prods[pid] = {
            "name": name, "price": price, "stock": stock,
            "sold": 0, "limit": limit, "category": category, "image_url": image_url
        }
        save_json("products.json", prods)
        bot.send_message(message.chat.id, f"✅ {name} ({category}) qo'shildi")
    except Exception as e:
        logger.error(f"/addproduct error: {e}")
        bot.send_message(message.chat.id,
            "❌ Format:\n/addproduct id|nom|narx|soni|limit|kategoriya|rasm_url\n\n"
            "Kategoriyalar:\n• Ro'zg'or uchun\n• Sovg'a uchun"
        )

@bot.message_handler(commands=['broadcast'])
def broadcast(message):
    if not is_admin(message.chat.id):
        return
    try:
        text = message.text.replace("/broadcast", "", 1).strip()
        if not text:
            bot.send_message(message.chat.id, "❌ Xabar matni kiriting:\n/broadcast Yangi mahsulotlar keldi!")
            return
        users = load_json("users.json")
        sent, failed = 0, 0
        for uid in users:
            try:
                bot.send_message(uid, text)
                sent += 1
            except Exception:
                failed += 1
        bot.send_message(message.chat.id, f"📢 Broadcast yakunlandi!\n\n✅ Sent: {sent}\n❌ Failed: {failed}")
        logger.info(f"Broadcast: sent={sent}, failed={failed}")
    except Exception as e:
        logger.error(f"/broadcast error: {e}")

@bot.message_handler(commands=['userlist'])
def userlist(message):
    if not is_admin(message.chat.id):
        return
    try:
        users = load_json("users.json")
        total = len(users)
        text = f"👥 <b>Jami foydalanuvchilar: {total}</b>\n\n"
        for uid in users[:20]:
            text += f"• <code>{uid}</code>\n"
        if total > 20:
            text += f"\n... va yana {total - 20} ta"
        bot.send_message(message.chat.id, text)
    except Exception as e:
        logger.error(f"/userlist error: {e}")

@bot.message_handler(commands=['topproducts'])
def topproducts(message):
    if not is_admin(message.chat.id):
        return
    try:
        prods = load_json("products.json")
        sorted_prods = sorted(prods.items(), key=lambda x: x[1]["sold"], reverse=True)
        text = "🏆 <b>Top mahsulotlar (sotilgan bo'yicha)</b>\n\n"
        for i, (pid, p) in enumerate(sorted_prods, 1):
            text += (
                f"{i}. 📌 {p['name']} [{p.get('category', '—')}]\n"
                f"   🛒 Sotilgan: {p['sold']} ta | 📦 Qoldiq: {p['stock']} ta\n"
                f"   💵 {p['price']:,} so'm\n\n"
            )
        bot.send_message(message.chat.id, text)
    except Exception as e:
        logger.error(f"/topproducts error: {e}")

@bot.message_handler(commands=['sell'])
def sell(message):
    if not is_admin(message.chat.id):
        return
    try:
        data = message.text.replace("/sell", "", 1).strip().split("|")
        pid      = data[0].strip()
        customer = data[1].strip()
        qty      = int(data[2].strip())

        prods = load_json("products.json")
        ords  = load_json("orders.json")

        if pid not in prods:
            bot.send_message(message.chat.id, "❌ Mahsulot topilmadi")
            return
        if prods[pid]["stock"] < qty:
            bot.send_message(message.chat.id, "❌ Yetarli mahsulot yo'q")
            return

        prods[pid]["stock"] -= qty
        prods[pid]["sold"]  += qty
        order = {
            "product_id": pid, "customer": customer,
            "quantity": qty, "date": datetime.now().strftime("%Y-%m-%d %H:%M")
        }
        ords.append(order)
        save_json("products.json", prods)
        save_json("orders.json", ords)

        bot.send_message(message.chat.id, f"✅ Sotuv qo'shildi: {prods[pid]['name']} - {qty} ta")
        bot.send_message(ADMIN_ID,
            f"🛒 Yangi sotuv!\n📦 {prods[pid]['name']}\n"
            f"👤 {customer}\n🔢 {qty} ta\n📦 Qoldiq: {prods[pid]['stock']} ta"
        )
        check_low_stock()
    except Exception as e:
        logger.error(f"/sell error: {e}")
        bot.send_message(message.chat.id, "❌ Format:\n/sell 1|Ali|2")

# ── Customer shop helpers ─────────────────────────────────────────────────────

def show_categories(message):
    try:
        bot.send_message(
            message.chat.id,
            "🗂 <b>Kategoriyani tanlang:</b>",
            reply_markup=categories_keyboard()
        )
    except Exception as e:
        logger.error(f"show_categories error: {e}")

def show_cart(message):
    try:
        cart = load_json("cart.json")
        user_cart = cart.get(str(message.chat.id), {})
        if not user_cart:
            bot.send_message(message.chat.id, "🛒 Savatingiz bo'sh.")
            return
        prods = load_json("products.json")
        total = 0
        text = "🛒 <b>Savatingiz:</b>\n\n"
        for pid, qty in user_cart.items():
            p = prods.get(pid)
            if not p:
                continue
            subtotal = p["price"] * qty
            total += subtotal
            text += f"• {p['name']} x{qty} = {subtotal:,} so'm\n"
        text += f"\n💰 <b>Jami: {total:,} so'm</b>"
        bot.send_message(message.chat.id, text, reply_markup=cart_keyboard())
    except Exception as e:
        logger.error(f"show_cart error: {e}")

def show_my_orders(message):
    try:
        ords = load_json("orders.json")
        user_id = message.chat.id
        my_orders = [o for o in ords if o.get("customer_id") == user_id]
        if not my_orders:
            bot.send_message(message.chat.id, "📦 Sizda hali buyurtma yo'q.")
            return
        text = "📦 <b>Sizning buyurtmalaringiz:</b>\n\n"
        for o in my_orders[-5:]:
            if "items" in o:
                items_text = ", ".join([f"{i['name']} x{i['qty']}" for i in o["items"]])
                text += f"📅 {o['date']}\n📦 {items_text}\n💰 {o.get('total', 0):,} so'm\n\n"
        bot.send_message(message.chat.id, text)
    except Exception as e:
        logger.error(f"show_my_orders error: {e}")

# ── Callback query handlers ───────────────────────────────────────────────────

@bot.callback_query_handler(func=lambda call: call.data == "noop")
def handle_noop(call):
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data == "back:cats")
def handle_back_cats(call):
    try:
        bot.edit_message_text(
            "🗂 <b>Kategoriyani tanlang:</b>",
            call.message.chat.id,
            call.message.message_id,
            reply_markup=categories_keyboard()
        )
        bot.answer_callback_query(call.id)
    except Exception as e:
        logger.error(f"back:cats error: {e}")

@bot.callback_query_handler(func=lambda call: call.data.startswith("cat:"))
def handle_category(call):
    try:
        category = call.data[4:]
        prods = load_json("products.json")
        items_in_cat = [p for p in prods.values() if p.get("category") == category and p["stock"] > 0]
        if not items_in_cat:
            bot.answer_callback_query(call.id, "Bu kategoriyada mahsulot yo'q.", show_alert=True)
            return
        label = CATEGORY_LABELS.get(category, category)
        bot.edit_message_text(
            f"📦 <b>{label}</b> mahsulotlari:",
            call.message.chat.id,
            call.message.message_id,
            reply_markup=products_in_category_keyboard(category)
        )
        bot.answer_callback_query(call.id)
    except Exception as e:
        logger.error(f"cat: error: {e}")

@bot.callback_query_handler(func=lambda call: call.data.startswith("prod:"))
def handle_product(call):
    try:
        pid = call.data[5:]
        prods = load_json("products.json")
        p = prods.get(pid)
        if not p:
            bot.answer_callback_query(call.id, "Mahsulot topilmadi.", show_alert=True)
            return
        text = (
            f"📌 <b>{p['name']}</b>\n"
            f"🏷 Kategoriya: {p.get('category', '—')}\n"
            f"💵 Narx: <b>{p['price']:,} so'm</b>\n"
            f"📦 Mavjud: {p['stock']} ta"
        )
        if p.get("image_url"):
            text += f"\n\n🖼 <a href=\"{p['image_url']}\">Rasmni ko'rish</a>"
        bot.edit_message_text(
            text,
            call.message.chat.id,
            call.message.message_id,
            reply_markup=product_detail_keyboard(pid, 1),
            disable_web_page_preview=True
        )
        bot.answer_callback_query(call.id)
    except Exception as e:
        logger.error(f"prod: error: {e}")

@bot.callback_query_handler(func=lambda call: call.data.startswith("qty:"))
def handle_qty(call):
    try:
        _, pid, qty_str = call.data.split(":")
        qty = max(1, int(qty_str))
        bot.edit_message_reply_markup(
            call.message.chat.id,
            call.message.message_id,
            reply_markup=product_detail_keyboard(pid, qty)
        )
        bot.answer_callback_query(call.id)
    except Exception as e:
        logger.error(f"qty: error: {e}")

@bot.callback_query_handler(func=lambda call: call.data.startswith("add:"))
def handle_add_to_cart(call):
    try:
        _, pid, qty_str = call.data.split(":")
        qty = int(qty_str)
        prods = load_json("products.json")
        p = prods.get(pid)
        if not p or p["stock"] < qty:
            bot.answer_callback_query(call.id, "❌ Yetarli mahsulot yo'q!", show_alert=True)
            return
        cart = load_json("cart.json")
        user_key = str(call.message.chat.id)
        if user_key not in cart:
            cart[user_key] = {}
        cart[user_key][pid] = cart[user_key].get(pid, 0) + qty
        save_json("cart.json", cart)
        bot.answer_callback_query(call.id, f"✅ {p['name']} savatga qo'shildi!", show_alert=False)
    except Exception as e:
        logger.error(f"add: error: {e}")

@bot.callback_query_handler(func=lambda call: call.data == "clear_cart")
def handle_clear_cart(call):
    try:
        cart = load_json("cart.json")
        cart.pop(str(call.message.chat.id), None)
        save_json("cart.json", cart)
        bot.edit_message_text("🗑 Savat tozalandi.", call.message.chat.id, call.message.message_id)
        bot.answer_callback_query(call.id)
    except Exception as e:
        logger.error(f"clear_cart error: {e}")

@bot.callback_query_handler(func=lambda call: call.data == "checkout")
def handle_checkout(call):
    try:
        cart = load_json("cart.json")
        if not cart.get(str(call.message.chat.id)):
            bot.answer_callback_query(call.id, "Savatingiz bo'sh!", show_alert=True)
            return
        bot.answer_callback_query(call.id)
        msg = bot.send_message(call.message.chat.id, "👤 Ism familiyangizni kiriting:")
        bot.register_next_step_handler(msg, get_name)
    except Exception as e:
        logger.error(f"checkout error: {e}")

# ── Checkout steps ────────────────────────────────────────────────────────────

def get_name(message):
    user_id = message.chat.id
    name = (message.text or "").strip()
    if len(name) < 2:
        msg = bot.send_message(user_id, "❌ Iltimos, to'liq ismingizni kiriting:")
        bot.register_next_step_handler(msg, get_name)
        return
    checkout_data[user_id] = {"name": name}
    msg = bot.send_message(user_id, "📞 Telefon raqamingizni kiriting:\n(+998XXXXXXXXX yoki 9XXXXXXXX)")
    bot.register_next_step_handler(msg, get_phone)

def get_phone(message):
    user_id = message.chat.id
    phone = (message.text or "").strip()
    if not is_valid_uzbek_phone(phone):
        msg = bot.send_message(user_id, "❌ Noto'g'ri telefon raqam. Qaytadan kiriting:\n(+998901234567 yoki 901234567)")
        bot.register_next_step_handler(msg, get_phone)
        return
    checkout_data[user_id]["phone"] = phone
    msg = bot.send_message(user_id, "📍 Manzilingizni kiriting:")
    bot.register_next_step_handler(msg, get_address)

def get_address(message):
    user_id = message.chat.id
    address = (message.text or "").strip()
    if len(address) < 5:
        msg = bot.send_message(user_id, "❌ Manzil juda qisqa. To'liqroq kiriting:")
        bot.register_next_step_handler(msg, get_address)
        return
    checkout_data[user_id]["address"] = address
    msg = bot.send_message(user_id, "📝 Izoh yoki eslatma kiriting (yo'q bo'lsa — yuboring):")
    bot.register_next_step_handler(msg, get_comment)

def get_comment(message):
    user_id = message.chat.id
    comment = (message.text or "—").strip()
    checkout_data[user_id]["comment"] = comment or "—"
    process_order(message)

def process_order(message):
    user_id = message.chat.id
    data = checkout_data.pop(user_id, {})
    try:
        cart  = load_json("cart.json")
        prods = load_json("products.json")
        ords  = load_json("orders.json")
        user_cart = cart.get(str(user_id), {})

        if not user_cart:
            bot.send_message(user_id, "❌ Savatingiz bo'sh!")
            return

        items = []
        total = 0
        for pid, qty in user_cart.items():
            p = prods.get(pid)
            if not p:
                continue
            qty = min(qty, p["stock"])
            if qty <= 0:
                continue
            subtotal = p["price"] * qty
            total += subtotal
            items.append({"pid": pid, "name": p["name"], "qty": qty, "subtotal": subtotal})
            prods[pid]["stock"] -= qty
            prods[pid]["sold"]  += qty

        if not items:
            bot.send_message(user_id, "❌ Savatchadagi mahsulotlar omborda yo'q.")
            return

        order = {
            "id": len(ords) + 1,
            "customer_id": user_id,
            "name":    data.get("name", "—"),
            "phone":   data.get("phone", "—"),
            "address": data.get("address", "—"),
            "comment": data.get("comment", "—"),
            "items":   items,
            "total":   total,
            "date":    datetime.now().strftime("%Y-%m-%d %H:%M")
        }
        ords.append(order)
        save_json("orders.json", ords)
        save_json("products.json", prods)

        cart.pop(str(user_id), None)
        save_json("cart.json", cart)

        bot.send_message(
            user_id,
            "✅ <b>Zakaz qabul qilindi!</b>\n\nTez orada siz bilan bog'lanamiz. Rahmat! 🙏",
            reply_markup=customer_keyboard()
        )

        bot.send_message(ADMIN_ID, "🚨 Sizda yangi zakaz mavjud!")
        items_text = "\n".join([f"  - {i['name']} x{i['qty']} = {i['subtotal']:,} so'm" for i in items])
        receipt = (
            f"🛒 <b>YANGI ZAKAZ</b>\n\n"
            f"👤 Ism: {order['name']}\n"
            f"📞 Telefon: {order['phone']}\n"
            f"📍 Manzil: {order['address']}\n"
            f"📝 Izoh: {order['comment']}\n\n"
            f"📦 Mahsulotlar:\n{items_text}\n\n"
            f"💰 Jami: {total:,} so'm\n"
            f"🕒 Sana: {order['date']}"
        )
        bot.send_message(ADMIN_ID, receipt)
        check_low_stock()
        logger.info(f"New order #{order['id']} from {user_id}, total={total}")
    except Exception as e:
        logger.error(f"process_order error: {e}")
        bot.send_message(user_id, "❌ Xatolik yuz berdi. Iltimos, qaytadan urinib ko'ring.")

# ── Text message routing ──────────────────────────────────────────────────────

ADMIN_BUTTONS = {
    "📊 Statistika", "📦 Mahsulotlar", "🛒 Zakazlar",
    "👥 Referral", "📣 Reklama", "🏆 Top Mahsulotlar", "👤 Userlar"
}

@bot.message_handler(func=lambda m: m.content_type == "text")
def handle_text(message):
    text = message.text.strip()
    chat_id = message.chat.id

    # Admin: broadcast state
    if chat_id in waiting_for_broadcast:
        waiting_for_broadcast.discard(chat_id)
        try:
            users = load_json("users.json")
            sent, failed = 0, 0
            for uid in users:
                try:
                    bot.send_message(uid, text)
                    sent += 1
                except Exception:
                    failed += 1
            bot.send_message(
                chat_id,
                f"📢 Broadcast yakunlandi!\n\n✅ Sent: {sent}\n❌ Failed: {failed}",
                reply_markup=admin_keyboard()
            )
        except Exception as e:
            logger.error(f"Broadcast error: {e}")
        return

    # Admin panel buttons
    if is_admin(chat_id) and text in ADMIN_BUTTONS:
        if text == "📊 Statistika":
            stat(message)
        elif text == "📦 Mahsulotlar":
            products_cmd(message)
        elif text == "🛒 Zakazlar":
            orders_cmd(message)
        elif text == "👥 Referral":
            referrals(message)
        elif text == "🏆 Top Mahsulotlar":
            topproducts(message)
        elif text == "👤 Userlar":
            userlist(message)
        elif text == "📣 Reklama":
            waiting_for_broadcast.add(chat_id)
            bot.send_message(chat_id, "✍️ Yuboriladigan reklama matnini yuboring:")
        return

    # Customer menu buttons (all users including admin)
    if text == "🛍 Mahsulotlar":
        show_categories(message)
    elif text == "🛒 Savat":
        show_cart(message)
    elif text == "📦 Mening buyurtmam":
        show_my_orders(message)

# ── Start ─────────────────────────────────────────────────────────────────────

logger.info("Bot ishga tushdi...")
check_low_stock()
bot.infinity_polling(skip_pending=True, logger_level=logging.ERROR, timeout=60, long_polling_timeout=60)
