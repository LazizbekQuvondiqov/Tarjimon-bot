# main.py
import logging
import json
import asyncio
import os
import traceback # Xatoliklarni batafsil loglash uchun

# --- .env faylini yuklash uchun ---
from dotenv import load_dotenv
load_dotenv() # .env faylidagi o'zgaruvchilarni os.environ ga yuklaydi
# -----------------------------------

from aiogram import Bot, Dispatcher, types
from aiogram.utils import executor
from aiogram.types import (ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove,
                           InlineKeyboardMarkup, InlineKeyboardButton, ParseMode)
from aiogram.utils.exceptions import (BotBlocked, ChatNotFound, UserDeactivated, CantParseEntities,
                                      MessageNotModified, RetryAfter, TelegramAPIError)
from aiogram.contrib.middlewares.logging import LoggingMiddleware
# <<< FSM uchun kerakli importlar >>>
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import State, StatesGroup
# <<< FSM importlar tugadi >>>

from googletrans import Translator, LANGUAGES

# dictionar.py fayli shu papkada deb taxmin qilinadi
from dictionar import get_definitions

# --- Logging sozlamalari (o'zgarishsiz) ---
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(name)s - %(message)s')
log = logging.getLogger(__name__)

# --- Konfiguratsiyani .env yoki environment dan o'qish ---
# Endi bu yerda to'g'ridan-to'g'ri qiymat berilmaydi
API_TOKEN = os.environ.get("BOT_TOKEN")
ADMIN_IDS_STR = os.environ.get("ADMIN_IDS")
# --- Fayl nomlari (o'zgarishsiz) ---
USER_FILE = "foydalanuvchi_idlar.txt"
CHANNEL_CONFIG_FILE = "kanal_id.txt"

# --- Kirish ma'lumotlarini tekshirish ---
if not API_TOKEN:
    log.critical("XATOLIK: BOT_TOKEN environment o'zgaruvchisi yoki .env faylida topilmadi!")
    exit(1) # Tokensiz bot ishlay olmaydi

# --- Admin IDlarini qayta ishlash ---
ADMIN_IDS = set() # Boshida bo'sh set yaratamiz
if ADMIN_IDS_STR: # Agar ADMIN_IDS .env da yoki environmentda topilgan bo'lsa...
    try:
        # ...uni vergul bilan ajratib, har birini int ga o'tkazib, set ga qo'shamiz
        ADMIN_IDS = {int(admin_id.strip()) for admin_id in ADMIN_IDS_STR.split(',') if admin_id.strip()}
        log.info(f"Admin IDlar yuklandi: {ADMIN_IDS}")
    except ValueError:
        # Agar ID lar orasida raqam bo'lmasa, xatolik beramiz
        log.critical(f"ADMIN_IDS ('{ADMIN_IDS_STR}') ichida xato format. Faqat raqamlar va vergul ishlating.")
        ADMIN_IDS = set() # Xatolik bo'lsa ham, adminlar ro'yxatini bo'shatamiz
else:
    # Agar ADMIN_IDS umuman topilmasa, ogohlantiramiz
    log.warning("ADMIN_IDS environment o'zgaruvchisi yoki .env faylida topilmadi. Admin buyruqlari ishlamaydi.")

# --- Global o'zgaruvchi: Joriy kanal ID si (o'zgarishsiz) ---
JORIY_KANAL_ID = None

# --- FSM uchun Storage (o'zgarishsiz) ---
storage = MemoryStorage() # Holatlarni xotirada saqlash

# --- Asosiy obyektlar (o'zgarishsiz) ---
# Bot obyektini yaratishda .env dan olingan API_TOKEN ishlatiladi
bot = Bot(token=API_TOKEN, parse_mode=ParseMode.MARKDOWN)
# Dispatcherga storage ni berish (o'zgarishsiz)
dp = Dispatcher(bot, storage=storage)
dp.middleware.setup(LoggingMiddleware())
translator = Translator()

# --- Foydalanuvchi va Kanal ID boshqaruvi (o'zgarishsiz) ---
FOYDALANUVCHI_IDLAR_CACHE = set()
def foydalanuvchi_idlarni_yuklash():
    global FOYDALANUVCHI_IDLAR_CACHE
    if not os.path.exists(USER_FILE):
        log.warning(f"Foydalanuvchi fayli '{USER_FILE}' topilmadi. Bo'sh ro'yxat bilan boshlanmoqda.")
        FOYDALANUVCHI_IDLAR_CACHE = set()
        try:
            with open(USER_FILE, "w"): pass
            log.info(f"Bo'sh foydalanuvchi fayli yaratildi: {USER_FILE}")
        except IOError as e:
             log.error(f"Foydalanuvchi faylini yaratishda xatolik {USER_FILE}: {e}")
        return
    try:
        with open(USER_FILE, "r") as f:
            ids = {int(line.strip()) for line in f if line.strip().isdigit()}
            FOYDALANUVCHI_IDLAR_CACHE = ids
            log.info(f"{len(FOYDALANUVCHI_IDLAR_CACHE)} ta foydalanuvchi IDsi {USER_FILE} faylidan yuklandi")
    except ValueError as e:
        log.error(f"'{USER_FILE}' faylini o'qishda xatolik. Noto'g'ri ID bormi? {e}")
    except Exception as e:
        log.error(f"'{USER_FILE}' faylini o'qishda xatolik: {e}")

def get_foydalanuvchi_idlar():
    return FOYDALANUVCHI_IDLAR_CACHE.copy()

def foydalanuvchi_id_qoshish(user_id: int):
    if user_id not in FOYDALANUVCHI_IDLAR_CACHE:
        FOYDALANUVCHI_IDLAR_CACHE.add(user_id)
        try:
            with open(USER_FILE, "a") as f:
                f.write(str(user_id) + "\n")
            log.info(f"Yangi foydalanuvchi qo'shildi: {user_id}. Jami: {len(FOYDALANUVCHI_IDLAR_CACHE)}")
            return True
        except IOError as e:
            log.error(f"Foydalanuvchi ID {user_id} ni '{USER_FILE}' fayliga yozishda xatolik: {e}")
            return False
    return False

def kanal_idni_yuklash():
    global JORIY_KANAL_ID
    try:
        if os.path.exists(CHANNEL_CONFIG_FILE):
            with open(CHANNEL_CONFIG_FILE, "r") as f:
                kanal_id = f.readline().strip()
                if kanal_id:
                    JORIY_KANAL_ID = kanal_id
                    log.info(f"Kanal IDsi fayldan yuklandi: {JORIY_KANAL_ID}")
                    return True
                else:
                    log.warning(f"Kanal konfiguratsiya fayli '{CHANNEL_CONFIG_FILE}' bo'sh.")
        else:
             log.warning(f"Kanal konfiguratsiya fayli '{CHANNEL_CONFIG_FILE}' topilmadi. Kanal o'rnatilmagan.")
    except Exception as e:
        log.error(f"'{CHANNEL_CONFIG_FILE}' dan kanal ID sini yuklashda xatolik: {e}")
    JORIY_KANAL_ID = None
    return False

def kanal_idni_saqlash(kanal_id: str):
    global JORIY_KANAL_ID
    try:
        cleaned_id = kanal_id.strip()
        with open(CHANNEL_CONFIG_FILE, "w") as f:
            f.write(cleaned_id)
        JORIY_KANAL_ID = cleaned_id
        log.info(f"Kanal IDsi muvaffaqiyatli o'rnatildi va saqlandi: {JORIY_KANAL_ID}")
        return True
    except IOError as e:
        log.error(f"Kanal ID '{kanal_id}' ni '{CHANNEL_CONFIG_FILE}' ga saqlashda xatolik: {e}")
        return False
    except Exception as e:
        log.exception(f"Kanal ID sini saqlashda kutilmagan xatolik: {e}")
        return False

# --- Kanalga a'zolikni tekshirish va xabar yuborish (o'zgarishsiz) ---
async def azolikni_tekshirish(user_id: int) -> bool:
    if not JORIY_KANAL_ID:
        log.debug("A'zolik tekshiruvi o'tkazib yuborildi: Kanal ID si o'rnatilmagan.")
        return True
    try:
        member = await bot.get_chat_member(chat_id=JORIY_KANAL_ID, user_id=user_id)
        is_member = member.status in [types.ChatMemberStatus.MEMBER,
                                       types.ChatMemberStatus.ADMINISTRATOR,
                                       types.ChatMemberStatus.CREATOR]
        log.debug(f"A'zolik tekshiruvi: Foydalanuvchi={user_id}, Kanal={JORIY_KANAL_ID}: Status={member.status}, A'zo={is_member}")
        return is_member
    except ChatNotFound:
        log.error(f"A'zolik tekshiruvi muvaffaqiyatsiz: Belgilangan kanal ({JORIY_KANAL_ID}) topilmadi yoki bot admin emas.")
        return False # Kanal topilmasa yoki bot admin bo'lmasa, a'zo emas deb hisoblaymiz
    except UserDeactivated:
        log.warning(f"A'zolik tekshiruvi muvaffaqiyatsiz: Foydalanuvchi {user_id} akkaunti o'chirilgan.")
        return False # O'chirilgan akkaunt a'zo emas
    except Exception as e:
        log.error(f"Foydalanuvchi {user_id} ning {JORIY_KANAL_ID} kanalidagi a'zoligini tekshirishda xatolik: {e}")
        return False # Boshqa xatoliklarda ham a'zo emas deb hisoblaymiz (xavfsizlik uchun)

async def azolik_xabarini_yuborish(chat_id: int):
    if not JORIY_KANAL_ID:
        await bot.send_message(chat_id, "Bot hozirda hech qanday kanalga ulanmagan. Administrator sozlamalarni amalga oshirishini kuting.")
        log.warning(f"A'zolik xabarini yuborishga urinildi (chat: {chat_id}), lekin kanal o'rnatilmagan.")
        return

    keyboard = InlineKeyboardMarkup(row_width=1)
    kanal_nomi = JORIY_KANAL_ID # Default nom sifatida ID ni olamiz
    kanal_link = None

    try:
        # Kanal ma'lumotlarini olishga harakat qilamiz
        chat_info = await bot.get_chat(JORIY_KANAL_ID)
        kanal_nomi = chat_info.full_name or chat_info.title or JORIY_KANAL_ID # To'liq nom, sarlavha yoki ID
        if chat_info.username: # Agar kanal public bo'lsa va username bo'lsa
            kanal_link = f"https://t.me/{chat_info.username}"
        else: # Agar kanal private bo'lsa yoki username bo'lmasa
             log.warning(f"Belgilangan kanal ({JORIY_KANAL_ID}) yopiq yoki username'ga ega emas. Oddiy havola yaratib bo'lmadi.")
             # Bu yerda invite link olishga harakat qilish mumkin, lekin u vaqtinchalik bo'lishi mumkin
    except ChatNotFound:
         log.error(f"Belgilangan kanal ({JORIY_KANAL_ID}) ma'lumotlarini olib bo'lmadi. ID xato yoki botda ruxsat yo'q.")
         # Foydalanuvchiga xato haqida xabar berish
         await bot.send_message(chat_id, f"❗️ Administrator tomonidan belgilangan kanal ({JORIY_KANAL_ID}) topilmadi yoki botda ruxsat yo'q. Administrator bilan bog'laning.")
         return # Kanal topilmasa, xabar yuborishni to'xtatamiz
    except Exception as e:
        # Boshqa kutilmagan xatoliklar
        log.warning(f"Kanal ({JORIY_KANAL_ID}) ma'lumotlarini olishda xatolik. Asosiy ma'lumotlardan foydalanilmoqda. Xatolik: {e}")
        # Agar ID @ bilan boshlansa, uni link qilishga urinib ko'ramiz
        if JORIY_KANAL_ID.startswith('@'):
            kanal_link = f"https://t.me/{JORIY_KANAL_ID[1:]}"

    # Xabar matni
    xabar_matni = f"✨ Botdan toʻliq foydalanish uchun, iltimos, *{kanal_nomi}* kanalimizga aʼzo boʻling.\n\n"

    # Agar kanal linki mavjud bo'lsa, tugmani qo'shamiz
    if kanal_link:
        keyboard.add(InlineKeyboardButton(f"➕ '{kanal_nomi}' ga a'zo bo'lish", url=kanal_link))
    else:
        # Agar link bo'lmasa (masalan, yopiq kanal), foydalanuvchiga qidirishni aytamiz
         xabar_matni += "Kanalni qidiruv orqali topishingiz mumkin.\n\n"

    # Har doim tekshirish tugmasini qo'shamiz
    keyboard.add(InlineKeyboardButton("✅ A'zolikni Tekshirish", callback_data="azolikni_tekshir"))
    xabar_matni += "A'zo bo'lgach, '✅ A'zolikni Tekshirish' tugmasini bosing."

    # Xabarni yuborish
    await bot.send_message(
        chat_id,
        xabar_matni,
        reply_markup=keyboard,
        parse_mode=ParseMode.MARKDOWN
    )


# --- Xavfsiz xabar yuborish (o'zgarishsiz) ---
async def xavfsiz_xabar_yuborish(chat_id: int, text: str, **kwargs):
    try:
        return await bot.send_message(chat_id, text, **kwargs)
    except BotBlocked:
        log.warning(f"Xabar yuborib bo'lmadi (chat {chat_id}): Bot foydalanuvchi tomonidan bloklangan.")
    except ChatNotFound:
        log.warning(f"Xabar yuborib bo'lmadi (chat {chat_id}): Chat topilmadi.")
    except UserDeactivated:
        log.warning(f"Xabar yuborib bo'lmadi (chat {chat_id}): Foydalanuvchi akkaunti o'chirilgan.")
    except CantParseEntities as e:
        log.warning(f"Markdown xatoligi ({chat_id}): {e}. Oddiy matn yuborilmoqda.")
        try:
            # Eng ko'p ishlatiladigan markdown belgilarni olib tashlash
            plain_text = text.replace('*','').replace('_','').replace('`','').replace('[','').replace(']','')
            return await bot.send_message(chat_id, plain_text, **kwargs)
        except Exception as plain_err:
            log.error(f"Oddiy matnli xabarni yuborishda xatolik ({chat_id}): {plain_err}")
    except RetryAfter as e:
        log.warning(f"Flood control ({chat_id}). {e.timeout} soniya kutamiz.")
        await asyncio.sleep(e.timeout)
        return await xavfsiz_xabar_yuborish(chat_id, text, **kwargs) # Qayta urinish
    except TelegramAPIError as e:
        log.error(f"Telegram API xatoligi tufayli xabar yuborilmadi ({chat_id}): {e}")
    except Exception as e:
        log.error(f"Xabar yuborishda kutilmagan xatolik ({chat_id}): {e}\n{traceback.format_exc()}")
    return None # Xatolik bo'lsa None qaytaradi

# --- FSM uchun Holatlar (States) (o'zgarishsiz) ---
class AdminStates(StatesGroup):
    kanal_id_kutish = State()  # Kanal ID sini kutish holati
    reklama_matn_kutish = State() # Reklama matnini kutish holati

# --- Klaviaturalar (o'zgarishsiz) ---
oddiy_foydalanuvchi_kb = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
oddiy_foydalanuvchi_kb.add(KeyboardButton("🆘 Yordam"), KeyboardButton("📊 Statistika"))

admin_asosiy_kb = ReplyKeyboardMarkup(resize_keyboard=True)
admin_asosiy_kb.add(KeyboardButton("📢 Reklama Yuborish"))
admin_asosiy_kb.add(KeyboardButton("🔧 Kanal Sozlash"), KeyboardButton("🗑 Kanalni O'chirish"))
admin_asosiy_kb.add(KeyboardButton("⬅️ Ortga (Foydalanuvchi rejimi)"))


# --- Asosiy Handlerlar (o'zgarishsiz) ---
# !!! Handlerlarning TARTIBI muhim !!!

# 1. Umumiy buyruqlar (start, admin, cancel)
@dp.message_handler(commands=["start"], state="*") # Barcha holatlarda /start ishlasin
async def start_buyrugi(message: types.Message, state: FSMContext):
    await state.finish() # Har qanday FSM holatini bekor qilish
    user_id = message.from_user.id
    chat_id = message.chat.id
    first_name = message.from_user.first_name

    # Foydalanuvchini faylga qo'shish (agar yo'q bo'lsa)
    yangi_foydalanuvchi = foydalanuvchi_id_qoshish(user_id)
    if yangi_foydalanuvchi:
        log.info(f"Yangi foydalanuvchi start bosdi: {first_name} (ID: {user_id})")

    # Kanalga a'zolikni tekshirish
    if not await azolikni_tekshirish(user_id):
        await azolik_xabarini_yuborish(chat_id)
        return # A'zo bo'lmasa, shu yerda to'xtatamiz

    # A'zo bo'lgan foydalanuvchiga xush kelibsiz xabari
    keyboard_to_show = oddiy_foydalanuvchi_kb
    salom_matni = f"👋 Salom, {first_name}! Speak English botiga xush kelibsiz 😊\n\nFoydalanish uchun so'z yoki ibora yuboring, yoki pastdagi tugmalardan birini bosing 👇"

    # Agar foydalanuvchi admin bo'lsa, eslatma qo'shamiz
    # ADMIN_IDS endi .env dan olingan qiymatga asoslanadi
    if user_id in ADMIN_IDS:
        salom_matni += "\n\n*(Siz adminsiz. /admin buyrug'i orqali admin paneliga o'tishingiz mumkin)*"
        # Adminga ham boshida oddiy klaviaturani ko'rsatamiz

    await xavfsiz_xabar_yuborish(chat_id, salom_matni, reply_markup=keyboard_to_show)

@dp.message_handler(commands=['cancel'], state='*') # Barcha holatlardan chiqish uchun
async def bekor_qilish_buyrugi(message: types.Message, state: FSMContext):
    current_state = await state.get_state()
    if current_state is None:
        # Hech qanday holatda bo'lmasa, xabar beramiz
        await message.reply("Siz hozir hech qanday jarayonda emassiz.", reply_markup=oddiy_foydalanuvchi_kb)
        return

    # Holat mavjud bo'lsa, uni bekor qilamiz
    log.info(f'Holat bekor qilinmoqda: {current_state} (foydalanuvchi: {message.from_user.id})')
    await state.finish()
    # Foydalanuvchiga mos klaviaturani ko'rsatamiz
    kb_to_show = oddiy_foydalanuvchi_kb
    if message.from_user.id in ADMIN_IDS:
         kb_to_show = admin_asosiy_kb # Adminga admin panelini qaytarish
    await message.reply('Jarayon bekor qilindi.', reply_markup=kb_to_show)


# /admin buyrug'i faqat ADMIN_IDS dagi foydalanuvchilar uchun va hech qanday FSM holatida bo'lmaganda ishlaydi
@dp.message_handler(commands=['admin'], user_id=ADMIN_IDS, state=None)
async def admin_paneli_buyrugi(message: types.Message):
    await message.reply("Salom, Admin! Kerakli bo'limni tanlang:", reply_markup=admin_asosiy_kb)


# 2. Admin tugmalari uchun handlerlar (holatni o'rnatadi)
# "Reklama Yuborish" tugmasi bosilganda
@dp.message_handler(lambda message: message.text == "📢 Reklama Yuborish", user_id=ADMIN_IDS, state=None)
async def reklama_yuborish_sorash(message: types.Message, state: FSMContext):
    await state.set_state(AdminStates.reklama_matn_kutish) # Reklama matnini kutish holatiga o'tish
    await message.reply("Yuboriladigan reklama matnini kiriting (bekor qilish uchun /cancel):",
                        reply_markup=ReplyKeyboardRemove()) # Asosiy klaviaturani yashirish

# "Kanal Sozlash" tugmasi bosilganda
@dp.message_handler(lambda message: message.text == "🔧 Kanal Sozlash", user_id=ADMIN_IDS, state=None)
async def kanal_sozlash_sorash(message: types.Message, state: FSMContext):
    await state.set_state(AdminStates.kanal_id_kutish) # Kanal ID sini kutish holatiga o'tish
    current_channel_info = f"Joriy kanal: `{JORIY_KANAL_ID}`" if JORIY_KANAL_ID else "Hozirda kanal belgilanmagan."
    await message.reply(f"{current_channel_info}\n\nMajburiy a'zolik uchun kanal manzilini kiriting (@username yoki -ID):\n\nBekor qilish uchun /cancel.",
                        reply_markup=ReplyKeyboardRemove(), parse_mode=ParseMode.MARKDOWN)

# "Kanalni O'chirish" tugmasi bosilganda
@dp.message_handler(lambda message: message.text == "🗑 Kanalni O'chirish", user_id=ADMIN_IDS, state=None)
async def kanal_ochirish_bajarish(message: types.Message, state: FSMContext): # state bu yerda ishlatilmaydi
    global JORIY_KANAL_ID
    if not JORIY_KANAL_ID:
        await message.reply("❗️ Majburiy a'zolik uchun hech qanday kanal belgilanmagan.", reply_markup=admin_asosiy_kb)
        return

    # Tasdiqlash so'rash mantiqan to'g'ri bo'lardi, lekin hozircha yo'q
    # confirm_kb = InlineKeyboardMarkup().add(
    #     InlineKeyboardButton("Ha, o'chirilsin", callback_data="confirm_delete_channel"),
    #     InlineKeyboardButton("Yo'q", callback_data="cancel_delete_channel")
    # )
    # await message.reply(f"`{JORIY_KANAL_ID}` kanalini majburiy a'zolikdan o'chirishga ishonchingiz komilmi?", reply_markup=confirm_kb)
    # Bu callback handlerni keyinroq qo'shish kerak bo'ladi

    # Hozircha to'g'ridan-to'g'ri o'chiramiz
    old_channel_id = JORIY_KANAL_ID
    JORIY_KANAL_ID = None # Xotiradagi ID ni tozalash
    deleted_from_file = False
    try:
        if os.path.exists(CHANNEL_CONFIG_FILE):
            os.remove(CHANNEL_CONFIG_FILE) # Faylni o'chirish
            log.info(f"Majburiy a'zolik kanali fayli ({CHANNEL_CONFIG_FILE}) o'chirildi (admin buyrug'i).")
            deleted_from_file = True
        else:
            log.info("Majburiy a'zolik kanali fayli allaqachon mavjud emas edi (admin buyrug'i).")
            deleted_from_file = True # Fayl yo'q bo'lsa ham, o'chirilgan hisoblaymiz
    except OSError as e:
        log.error(f"Kanal konfiguratsiya faylini ({CHANNEL_CONFIG_FILE}) o'chirishda xatolik (admin): {e}")
    except Exception as e:
        log.exception(f"Kanal konfiguratsiya faylini o'chirishda kutilmagan xatolik (admin): {e}")

    # Agar xotiradan va fayldan (yoki fayl yo'q bo'lsa) o'chirilgan bo'lsa
    if deleted_from_file and JORIY_KANAL_ID is None:
         await message.reply(f"✅ Majburiy a'zolik funksiyasi o'chirildi (avvalgi kanal: `{old_channel_id}`).",
                             reply_markup=admin_asosiy_kb, parse_mode=ParseMode.MARKDOWN)
    else:
         # Agar faylni o'chirishda xatolik bo'lsa
         await message.reply("❌ Majburiy a'zolikni o'chirishda xatolik yuz berdi. Log fayllarini tekshiring.",
                             reply_markup=admin_asosiy_kb)

# "Ortga (Foydalanuvchi rejimi)" tugmasi bosilganda
@dp.message_handler(lambda message: message.text == "⬅️ Ortga (Foydalanuvchi rejimi)", user_id=ADMIN_IDS, state=None)
async def admin_panelidan_chiqish(message: types.Message):
     # Oddiy foydalanuvchi klaviaturasini ko'rsatish
     await message.reply("Foydalanuvchi rejimi aktiv.", reply_markup=oddiy_foydalanuvchi_kb)


# 3. FSM Holatlari uchun handlerlar (ma'lumotni qabul qiladi va qayta ishlaydi)

# Reklama matnini kutish holatida xabar kelsa
@dp.message_handler(state=AdminStates.reklama_matn_kutish, user_id=ADMIN_IDS, content_types=types.ContentType.TEXT)
async def reklama_matnini_qabul_qilish(message: types.Message, state: FSMContext):
    reklama_matni = message.text # Kelgan matnni olish
    await state.finish() # Holatni tugatish

    # Reklama yuborish logikasi (avvalgi kod bilan bir xil)
    foydalanuvchi_idlar = get_foydalanuvchi_idlar()
    if not foydalanuvchi_idlar:
        await message.reply("🚫 Foydalanuvchilar ro'yxati bo'sh.", reply_markup=admin_asosiy_kb)
        return

    yuborildi = 0
    xatolik = 0
    # Yuborishdan oldin xabar berish
    tasdiq_xabari = await message.reply(f"🚀 Reklama yuborish boshlanmoqda (jami {len(foydalanuvchi_idlar)} foydalanuvchiga)...",
                                        reply_markup=admin_asosiy_kb) # Admin panelini qayta ko'rsatish
    start_time = asyncio.get_event_loop().time() # Boshlanish vaqti
    broadcast_tasks = [] # Xabar yuborish tasklari uchun ro'yxat

    # Har bir foydalanuvchiga xabar yuborish uchun asinxron task yaratish
    for user_id in foydalanuvchi_idlar:
        task = asyncio.create_task(xavfsiz_xabar_yuborish(user_id, reklama_matni, parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=True))
        broadcast_tasks.append((user_id, task))
        # Telegram limitlariga duch kelmaslik uchun pauza
        if len(broadcast_tasks) % 25 == 0: # Har 25 ta xabardan keyin
            await asyncio.sleep(1.1) # 1.1 soniya kutish

    # Barcha tasklar tugashini kutish va natijalarni yig'ish
    for user_id, task in broadcast_tasks:
         try:
            result = await task # Task natijasini olish (None yoki Message obyekti)
            if result: yuborildi += 1 # Agar xabar yuborilgan bo'lsa
            else: xatolik += 1 # Agar xatolik bo'lgan bo'lsa (blok, topilmadi va hokazo)
         except Exception as task_e:
             # Task bajarilishida kutilmagan xatolik bo'lsa
             log.error(f"Reklama yuborish taskida xatolik (foydalanuvchi {user_id}): {task_e}")
             xatolik += 1

    # Yakuniy natijani hisoblash va xabar berish
    end_time = asyncio.get_event_loop().time() # Tugash vaqti
    duration = end_time - start_time # Sarflangan vaqt
    try:
        # Boshlang'ich xabarni tahrirlash
        await tasdiq_xabari.edit_text(
            f"✅ Reklama yuborish yakunlandi!\n\n"
            f"👤 {yuborildi} yetkazildi.\n"
            f"🚫 {xatolik} xatolik/blok.\n"
            f"⏱ {duration:.2f}s."
        )
    except MessageNotModified: pass # Agar xabar o'zgarmagan bo'lsa (kamdan-kam holat)
    except Exception as edit_e:
        # Agar tahrirlashda xatolik bo'lsa, yangi xabar yuborish
        log.error(f"Reklama statusini tahrirlashda xatolik: {edit_e}")
        await message.reply(
             f"✅ Reklama yuborish yakunlandi!\n"
             f"👤 {yuborildi} yetkazildi.\n"
             f"🚫 {xatolik} xatolik/blok.\n"
             f"⏱ {duration:.2f}s.",
             reply_markup=admin_asosiy_kb
        )


# Kanal ID sini kutish holatida xabar kelsa
@dp.message_handler(state=AdminStates.kanal_id_kutish, user_id=ADMIN_IDS, content_types=types.ContentType.TEXT)
async def kanal_idni_qabul_qilish(message: types.Message, state: FSMContext):
    kiritilgan_manzil = message.text.strip() # Kelgan matnni olish va bo'shliqlarni olib tashlash

    # Kanal manzilini tekshirish va ID/username ni ajratib olish logikasi
    kanal_identifikatori = None
    if kiritilgan_manzil.startswith('@') and len(kiritilgan_manzil) > 1: # @username formatida
        kanal_identifikatori = kiritilgan_manzil
    elif kiritilgan_manzil.startswith('-') and kiritilgan_manzil[1:].isdigit(): # -100... formatida (private ID)
        kanal_identifikatori = kiritilgan_manzil
    elif kiritilgan_manzil.startswith('https://t.me/'): # Telegram link formatida
        try:
            # Linkdan username yoki public ID ni ajratib olishga harakat
            parts = kiritilgan_manzil.split('t.me/')
            if len(parts) > 1:
                identifier_part = parts[1].split('/')[0] # /joinchat/ dan keyingi qismni yoki username ni olish
                # Agar bu username bo'lsa (@ qo'shamiz)
                if identifier_part and not identifier_part.isdigit() and not identifier_part.startswith('+'):
                     kanal_identifikatori = f"@{identifier_part}"
                # Agar bu raqamli ID bo'lsa (lekin odatda linkda bunaqa bo'lmaydi, shuning uchun bu shart keraksiz bo'lishi mumkin)
                # elif identifier_part.isdigit():
                #     kanal_identifikatori = identifier_part # Yoki "-"+identifier_part qilish kerakdir? Tekshirish lozim.
                # Yopiq kanallar uchun invite linklarni bu yerda qayta ishlash qiyin
                else:
                     log.warning(f"Tushunarsiz Telegram link formati: {kiritilgan_manzil}")
        except Exception as e:
            log.error(f"Linkni ('{kiritilgan_manzil}') qayta ishlashda xatolik: {e}")
    # Boshqa formatlar qabul qilinmaydi

    # Agar mos identifikator topilsa
    if kanal_identifikatori:
        await state.finish() # Holatni tugatish
        # Kanal ID sini faylga saqlashga urinish
        if kanal_idni_saqlash(kanal_identifikatori):
            # Muvaffaqiyatli saqlansa, xabar berish
            await message.reply(f"✅ Kanal muvaffaqiyatli o'rnatildi: `{JORIY_KANAL_ID}`",
                                reply_markup=admin_asosiy_kb, parse_mode=ParseMode.MARKDOWN)
            # Bot kanalni topa olishini tekshirish
            try:
                chat_info = await bot.get_chat(JORIY_KANAL_ID)
                await message.reply(f"ℹ️ Bot '{chat_info.title}' ({JORIY_KANAL_ID}) kanalini topa oldi.",
                                    reply_markup=admin_asosiy_kb)
            except Exception as e:
                 # Agar topa olmasa, ogohlantirish
                 await message.reply(f"⚠️ Diqqat: Bot `{JORIY_KANAL_ID}` kanalini topa olmadi yoki ma'lumotlarini o'qiy olmadi. ID to'g'riligini va botning kanalda *admin* huquqi borligini tekshiring.\nXatolik: `{e}`",
                                     reply_markup=admin_asosiy_kb, parse_mode=ParseMode.MARKDOWN)
        else:
            # Saqlashda xatolik bo'lsa
            await message.reply("❌ Kanal ID sini saqlashda xatolik.", reply_markup=admin_asosiy_kb)
    else:
        # Agar kiritilgan format noto'g'ri bo'lsa
        await message.reply("❗️ Format xato. Kanal manzilini `@username`, `-100...` yoki `https://t.me/...` ko'rinishida kiriting.\n\nQaytadan urinib ko'ring yoki /cancel.",
                            reply_markup=ReplyKeyboardRemove()) # Klaviatura yopiqligicha qoladi


# 4. Oddiy foydalanuvchi tugmalari (holatda bo'lmaganda ishlaydi)
# "Yordam" tugmasi bosilganda
@dp.message_handler(lambda message: message.text == "🆘 Yordam", state=None) # state=None - FSM holatida bo'lmaganda
async def yordam_yuborish(message: types.Message):
    user_id = message.from_user.id
    # A'zolikni tekshirish
    if not await azolikni_tekshirish(user_id):
        await azolik_xabarini_yuborish(message.chat.id)
        return

    # Yordam matni
    yordam_matni = (
        "📖 *FOYDALANISH QO‘LLANMASI* 🚀\n\n"
        "🔹 Ingliz yoki o‘zbek tilidagi so‘z yoki iborani yuboring.\n"
        "🔹 Bot sizga quyidagilarni taqdim etadi:\n"
        "  ✅ *Tarjima* (o‘zbekcha <> inglizcha)\n"
        "  ✅ *Ta’rif* (inglizcha so'zlar uchun)\n"
        "  ✅ *Fonetika* (inglizcha so'zlar uchun)\n"
        "  ✅ 🔊 *Talaffuz* (audio, agar mavjud bo‘lsa)\n\n"
        "💡 *Misol:*\n"
        "   Yuboring: `apple`\n"
        "   Bot javobi:\n"
        "   `en -> uz Tarjimasi:`\n"
        "   `olma`\n\n"
        "   `📖 So'z: apple`\n"
        "   `🔊 Fonetika: /ˈæp.əl/`\n"
        "   `📚 Ta'riflar:`\n"
        "   `👉 The round fruit of a tree of the rose family...`\n"
        "   _(Audio fayl ham yuboriladi)_ \n\n"
        "📌 Til o‘rganish – muvaffaqiyat kaliti!"
    )
    # Yordam matnini yuborish (klaviaturani olib tashlash bilan)
    await xavfsiz_xabar_yuborish(message.chat.id, yordam_matni, parse_mode=ParseMode.MARKDOWN, reply_markup=ReplyKeyboardRemove())
    # Foydalanuvchiga asosiy klaviaturani qayta ko'rsatish
    await asyncio.sleep(0.5) # Kichik pauza
    await message.answer("Asosiy menyu:", reply_markup=oddiy_foydalanuvchi_kb)

# "Statistika" tugmasi bosilganda
@dp.message_handler(lambda message: message.text == "📊 Statistika", state=None) # state=None - FSM holatida bo'lmaganda
async def statistika_korish(message: types.Message):
    user_id = message.from_user.id
    # A'zolikni tekshirish
    if not await azolikni_tekshirish(user_id):
        await azolik_xabarini_yuborish(message.chat.id)
        return

    # Statistika olish va yuborish
    foydalanuvchi_soni = len(get_foydalanuvchi_idlar())
    await xavfsiz_xabar_yuborish(message.chat.id, f"📊 Botimizdan jami foydalanuvchilar soni: *{foydalanuvchi_soni}* nafar.")


# 5. Callback Query Handler (inline tugmalar uchun, holatdan mustaqil)
# "A'zolikni Tekshirish" inline tugmasi bosilganda
@dp.callback_query_handler(lambda c: c.data == 'azolikni_tekshir', state="*") # state="*" - barcha FSM holatlarida ishlaydi
async def azolikni_tekshirish_callback(callback_query: types.CallbackQuery, state: FSMContext): # state ni qabul qilamiz
    user_id = callback_query.from_user.id
    chat_id = callback_query.message.chat.id
    message_id = callback_query.message.message_id # Xabarni o'chirish uchun kerak

    # Foydalanuvchiga kutish haqida bildirish (tugma bosilganda kichik xabar)
    await bot.answer_callback_query(callback_query.id, "Tekshirilmoqda...")

    # A'zolikni tekshirish
    if await azolikni_tekshirish(user_id):
        # Agar a'zo bo'lsa
        await xavfsiz_xabar_yuborish(chat_id, "✅ Rahmat! Kanalga a'zo bo'lgansiz.\nEndi botdan foydalanishingiz mumkin.")
        # A'zolik so'ralgan xabarni o'chirish
        try:
            await bot.delete_message(chat_id=chat_id, message_id=message_id)
        except Exception as e:
            log.warning(f"A'zolik so'rov xabarini ({message_id}) o'chirib bo'lmadi: {e}")

        # Agar foydalanuvchi biror FSM holatida bo'lsa, uni tugatish
        current_state = await state.get_state()
        if current_state is not None:
            log.info(f"A'zolik tasdiqlangandan so'ng holat bekor qilinmoqda: {current_state} (foydalanuvchi: {user_id})")
            await state.finish()

        # Foydalanuvchiga mos klaviaturani ko'rsatish (start buyrug'ini qayta chaqirmaymiz)
        kb_to_show = oddiy_foydalanuvchi_kb
        salom_matni = "Asosiy menyu:"
        if user_id in ADMIN_IDS:
            # Adminga admin panelini ko'rsatish yoki oddiyni qoldirish
             kb_to_show = admin_asosiy_kb # Admin panelini ko'rsatish
             salom_matni = "Admin menyusi:"
        await xavfsiz_xabar_yuborish(chat_id, salom_matni, reply_markup=kb_to_show)

    else:
        # Agar a'zo bo'lmasa, ogohlantirish (ekranda katta xabar)
        await bot.answer_callback_query(callback_query.id, "❌ Hali kanalga a'zo bo'lmadingiz yoki a'zoligingizni tekshira olmadim. Qaytadan urinib ko'ring.", show_alert=True)


# 6. Umumiy Matn Handleri ENG OXIRIDA (va hech qanday holatda bo'lmaganda)
# Qolgan barcha matnli xabarlarni qabul qiladi
@dp.message_handler(content_types=types.ContentType.TEXT, state=None) # state=None - FSM holatida bo'lmaganda
async def matn_qayta_ishlash(message: types.Message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    text = message.text.strip() # Xabar matni

    # Agar admin panelidagi tugmalar matni kelsa, e'tiborsiz qoldirish
    admin_tugmalari = ["📢 Reklama Yuborish", "🔧 Kanal Sozlash", "🗑 Kanalni O'chirish", "⬅️ Ortga (Foydalanuvchi rejimi)"]
    if user_id in ADMIN_IDS and text in admin_tugmalari:
        log.debug(f"Admin tugmasi '{text}' umumiy matn handlerida e'tiborsiz qoldirildi.")
        return # Bular uchun alohida handler bor

    # Bo'sh xabarlarni e'tiborsiz qoldirish
    if not text: return

    # A'zolikni tekshirish
    if not await azolikni_tekshirish(user_id):
        await azolik_xabarini_yuborish(chat_id)
        return

    # Tarjima va ta'rif logikasi (o'zgarishsiz)
    qayta_ishlash_xabari = None # "Izlanmoqda..." xabarini saqlash uchun
    try:
        # Tilni aniqlash
        try:
            detected = translator.detect(text)
            lang = detected.lang
            if not lang or lang == 'und' or lang not in LANGUAGES: # Agar aniqlanmasa yoki qo'llab-quvvatlanmasa
                 lang = 'en' # Inglizcha deb hisoblash
                 log.warning(f"Til aniqlanmadi yoki qo'llab-quvvatlanmaydi ('{detected.lang}'). 'en' deb qabul qilinmoqda.")
        except Exception as detect_err:
            log.error(f"Tilni aniqlashda xatolik: {detect_err}. 'en' deb qabul qilinmoqda.")
            lang = 'en' # Xatolik bo'lsa ham inglizcha deb olish

        # Tarjima qilinadigan tilni tanlash
        dest = "uz" if lang == "en" else "en"

        # Tarjima qilish
        try:
            translation_result = translator.translate(text, dest=dest, src=lang)
            tarjima = translation_result.text
            # Agar tarjima asl matndan farq qilsa, yuborish
            if text.strip().lower() != tarjima.strip().lower():
                await xavfsiz_xabar_yuborish(chat_id, f"*{lang}* → *{dest}* Tarjimasi:\n`{tarjima}`", reply_to_message_id=message.message_id)
            else:
                 # Agar bir xil bo'lsa (masalan, raqamlar, ismlar)
                 log.info(f"Tarjima asl matnga o'xshash, tarjima xabari yuborilmadi: '{text}'")
                 # Bu yerda ta'rif qidirish kerakmi? Hozircha shart emas.
        except Exception as translate_err:
             log.error(f"Tarjima qilishda xatolik (googletrans): {translate_err}. Matn: {text[:50]}")
             await xavfsiz_xabar_yuborish(chat_id, "❗️ Tarjima qilishda xatolik yuz berdi.", reply_to_message_id=message.message_id)
             return # Tarjima qila olmasak, davom etmaymiz

        # Ta'rif va talaffuz qidirish (faqat bitta so'z bo'lsa va inglizcha bo'lsa)
        izlanadigan_soz = None
        # Agar asl matn inglizcha va bitta so'z bo'lsa
        if lang == 'en' and len(text.split()) == 1 and text.isalpha(): # isalpha() faqat harflardan iboratligini tekshiradi
            izlanadigan_soz = text.lower()
        # Agar o'zbekchadan inglizchaga tarjima qilingan bo'lsa va natija bitta so'z bo'lsa
        elif dest == 'en' and tarjima and len(tarjima.split()) == 1 and tarjima.isalpha():
            izlanadigan_soz = tarjima.lower()

        # Agar ta'rif izlash uchun so'z topilsa
        if izlanadigan_soz:
            # "Izlanmoqda" xabarini yuborish
            qayta_ishlash_xabari = await xavfsiz_xabar_yuborish(chat_id, f"`{izlanadigan_soz}` uchun ta'rif va talaffuz izlanmoqda...",
                                                                reply_markup=ReplyKeyboardRemove(), parse_mode=ParseMode.MARKDOWN)
            try:
                # dictionar.py dagi funksiyani chaqirish (bloklanmaslik uchun executor da)
                loop = asyncio.get_running_loop()
                lookup_json_str = await loop.run_in_executor(None, get_definitions, izlanadigan_soz, 5) # 5 sekund timeout
                lookup = json.loads(lookup_json_str) # Natijani JSON dan dict ga o'tkazish

                # "Izlanmoqda" xabarini o'chirish (agar yuborilgan bo'lsa)
                if qayta_ishlash_xabari:
                    try: await bot.delete_message(chat_id=chat_id, message_id=qayta_ishlash_xabari.message_id)
                    except Exception as del_err: log.warning(f"Qayta ishlash xabarini ({qayta_ishlash_xabari.message_id}) o'chirib bo'lmadi: {del_err}")

                # Agar natija muvaffaqiyatli va xatoliksiz bo'lsa
                if lookup and isinstance(lookup, dict) and "error" not in lookup:
                    fonetika_matni = lookup.get("phonetic", "_Mavjud emas_")
                    tariflar_list = lookup.get("definitions", [])
                    # Ta'riflarni formatlash
                    tariflar_matni = "\n".join([f"🔹 {t}" for t in tariflar_list]) if tariflar_list else "_Ta'riflar topilmadi._"

                    # Yakuniy javobni yig'ish
                    javob_qismlari = [
                        f"📖 So'z: `{izlanadigan_soz}`",
                        f"🔊 Fonetika: {fonetika_matni}",
                        f"\n📚 Ta'riflar:\n{tariflar_matni}"
                    ]
                    javob = "\n".join(javob_qismlari)
                    await xavfsiz_xabar_yuborish(chat_id, javob, parse_mode=ParseMode.MARKDOWN)

                    # Agar audio linki bo'lsa, audioni yuborish
                    if lookup.get("audio"):
                        audio_url = lookup["audio"]
                        try:
                            log.info(f"Audio yuborilmoqda: {audio_url} ({izlanadigan_soz} uchun)")
                            await bot.send_chat_action(chat_id, types.ChatActions.UPLOAD_VOICE) # "Audio yozilmoqda..." statusi
                            await bot.send_voice(chat_id, audio_url, caption=f"`{izlanadigan_soz}` talaffuzi", parse_mode=ParseMode.MARKDOWN)
                        except Exception as audio_err:
                            log.warning(f"Audio ({audio_url}) yuborishda xatolik ('{izlanadigan_soz}' uchun): {audio_err}")
                            # Audio yuborishda xatolik bo'lsa, shunchaki log qilish yetarli
                            # await xavfsiz_xabar_yuborish(chat_id, "_(Audio faylni yuborishda xatolik yuz berdi.)_")
                else: # Agar ta'rif topilmasa yoki API da xatolik bo'lsa
                    error_msg = lookup.get("error", "Noma'lum sabab") if isinstance(lookup, dict) else "API dan javob kelmadi"
                    log.info(f"'{izlanadigan_soz}' uchun ta'rif topilmadi: {error_msg}")
                    # Agar tarjimasi yuqorida ko'rsatilgan bo'lsa, qo'shimcha xabar berish
                    if text.strip().lower() != tarjima.strip().lower():
                         await xavfsiz_xabar_yuborish(chat_id, f"✅ Tarjimasi yuqorida ko'rsatildi.\n\nℹ️ Qo'shimcha ma'lumot (`{izlanadigan_soz}` uchun ta'rif/fonetika) topilmadi.")
                    else: # Agar tarjima ham bo'lmagan bo'lsa (asl matnga o'xshash bo'lsa)
                        await xavfsiz_xabar_yuborish(chat_id, f"ℹ️ `{izlanadigan_soz}` uchun tarjima, ta'rif yoki fonetika topilmadi.")

            except json.JSONDecodeError as json_err:
                 # Agar get_definitions dan kelgan javob JSON bo'lmasa
                 log.error(f"get_definitions dan kelgan JSON ni decode qilishda xatolik ('{izlanadigan_soz}' uchun): {json_err}. Javob: {lookup_json_str[:200]}")
                 if qayta_ishlash_xabari:
                    try: await bot.delete_message(chat_id=chat_id, message_id=qayta_ishlash_xabari.message_id)
                    except Exception: pass
                 await xavfsiz_xabar_yuborish(chat_id,"❗️ Ta'rif ma'lumotlarini qayta ishlashda xatolik.")
            except Exception as e_def:
                # Boshqa kutilmagan xatoliklar
                log.error(f"Ta'rifni qayta ishlashda xatolik ('{izlanadigan_soz}' uchun): {e_def}\n{traceback.format_exc()}")
                if qayta_ishlash_xabari:
                    try: await bot.delete_message(chat_id=chat_id, message_id=qayta_ishlash_xabari.message_id)
                    except Exception: pass
                await xavfsiz_xabar_yuborish(chat_id, "❗️ Ta'riflarni olishda kutilmagan xatolik yuz berdi.")
            finally:
                 # Ta'rif izlash tugagach (xatolik bo'lsa ham), foydalanuvchiga mos klaviaturani qaytarish
                 kb_to_show = oddiy_foydalanuvchi_kb
                 if user_id in ADMIN_IDS: kb_to_show = admin_asosiy_kb
                 await message.answer("Asosiy menyu:", reply_markup=kb_to_show)

    except Exception as e_main: # Umumiy matnni qayta ishlashdagi eng tashqi xatolik ushlagich
        log.error(f"matn_qayta_ishlash da umumiy xatolik (foydalanuvchi {user_id}, matn '{text}'): {e_main}\n{traceback.format_exc()}")
        if qayta_ishlash_xabari: # Agar "Izlanmoqda" xabari yuborilgan bo'lsa, o'chirish
             try: await bot.delete_message(chat_id=chat_id, message_id=qayta_ishlash_xabari.message_id)
             except Exception: pass
        await xavfsiz_xabar_yuborish(chat_id, "🚫 Noma'lum xatolik yuz berdi. Iltimos, qayta urinib ko'ring yoki keyinroq harakat qiling.")
        # Xatolikdan keyin ham klaviaturani ko'rsatish
        kb_to_show = oddiy_foydalanuvchi_kb
        if user_id in ADMIN_IDS: kb_to_show = admin_asosiy_kb
        await message.answer("Asosiy menyu:", reply_markup=kb_to_show)


# --- Skriptni Ishga Tushirish Nuqtasi ---
if __name__ == "__main__":
    log.info("Bot ishga tushirilmoqda...")
    # .env fayli yuqorida load_dotenv() orqali yuklangan
    # API_TOKEN va ADMIN_IDS allaqachon o'qilgan va tekshirilgan
    if API_TOKEN: # Token mavjudligini yana bir bor tekshirish (garchi exit(1) bo'lsa ham)
        foydalanuvchi_idlarni_yuklash() # Foydalanuvchilarni fayldan yuklash
        kanal_idni_yuklash() # Kanal ID sini fayldan yuklash
        if not JORIY_KANAL_ID:
            log.warning("!!! DIQQAT: Majburiy a'zolik kanali o'rnatilmagan. Kanalni o'rnatish uchun admin sifatida /admin buyrug'i -> 'Kanal Sozlash' tugmasidan foydalaning. !!!")
        log.info("Polling boshlanmoqda...")
        try:
            # Botni ishga tushirish (yangi xabarlarni kutish)
            executor.start_polling(dp, skip_updates=True) # skip_updates=True - bot offlayn bo'lgandagi xabarlarni o'tkazib yuboradi
        except Exception as e:
            log.critical(f"Bot ishga tushishida yoki polling paytida kritik xatolik: {e}", exc_info=True)
        finally:
            log.info("Bot to'xtatildi.")
    else:
        # Bu holat deyarli bo'lmaydi, chunki yuqorida exit(1) bor
        log.critical("API_TOKEN topilmaganligi sababli bot ishga tushirilmadi.")