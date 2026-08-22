import os
import io
from aiogram import Bot, Dispatcher, types, F
from aiogram.types import BufferedInputFile
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web, ClientSession
from PIL import Image

# 1. Считываем настройки
TOKEN = os.getenv("BOT_TOKEN")
RENDER_EXTERNAL_URL = os.getenv("RENDER_EXTERNAL_URL")

GITHUB_OWNER = os.getenv("GITHUB_OWNER", "")      
GITHUB_REPO = os.getenv("GITHUB_REPO", "")        
GITHUB_BRANCH = os.getenv("GITHUB_BRANCH", "main")  
GITHUB_FILE_PATH = os.getenv("GITHUB_FILE_PATH", "template.attheme") 

# 2. Инициализируем бота и диспетчер
bot = Bot(token=TOKEN)
dp = Dispatcher(storage=MemoryStorage())

async def download_template_from_github() -> str:
    """Безопасное скачивание шаблона с GitHub с резервным планом в коде"""
    url = "https://githubusercontent.com"
    
    # Резервный полноценный шаблон Android темы (сработает, если упадет интернет или DNS на Render)
    fallback_template = """
    windowBackgroundGray = {bg_color}
    windowBackgroundWhite = {bg_color}
    actionBarDefault = {primary_color}
    actionBarDefaultTop = {primary_color}
    actionBarDefaultIcon = {text_color}
    actionBarDefaultTitle = {text_color}
    chat_inBubble = {bg_color_light}
    chat_inBubbleSelected = {primary_color_alpha}
    chat_inText = {text_color}
    chat_outBubble = {primary_color_alpha}
    chat_outText = {text_color}
    chat_outTime = {text_color_muted}
    chat_inTime = {text_color_muted}
    chat_wallpaper = {bg_color}
    """.strip()

    print(f"Попытка скачать шаблон по адресу: {url}")
    
    try:
        async with ClientSession() as session:
            # Ставим жесткий тайм-аут на чтение, чтобы бот не зависал дольше 5 секунд
            async with session.get(url, timeout=5) as response:
                if response.status == 200:
                    print("Шаблон успешно скачан с GitHub!")
                    return await response.text(encoding='utf-8')
                else:
                    print(f"GitHub ответил статусом {response.status}. Использую резервный шаблон.")
                    return fallback_template
    except Exception as e:
        # Сюда попадет как раз наша ошибка DNS "No address associated with hostname"
        print(f"⚠️ Ошибка сети/DNS при обращении к GitHub ({e}). Активирую резервный шаблон!")
        return fallback_template
    
    async with ClientSession() as session:
        async with session.get(url) as response:
            if response.status == 200:
                return await response.text(encoding='utf-8')
            else:
                print(f"Ошибка GitHub! Статус: {response.status}. Отдаю аварийный шаблон.")
                return "windowBackgroundWhite = {bg_color}\nactionBarDefault = {primary_color}"
    
    async with ClientSession() as session:
        async with session.get(url) as response:
            if response.status == 200:
                return await response.text(encoding='utf-8')
            print(f"Ошибка GitHub API! Статус: {response.status}")
            return "windowBackgroundWhite = {bg_color}\nactionBarDefault = {primary_color}"

def get_dominant_color(image_bytes: bytes) -> tuple:
    image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    image_small = image.resize((1, 1), resample=Image.Resampling.LANCZOS)
    return image_small.getpixel((0, 0))

def generate_theme_file(template: str, rgb: tuple) -> str:
    """Сборка констант темы с безопасным расчетом цветов"""
    def rgb_to_hex(r, g, b):
        return f"#{r:02x}{g:02x}{b:02x}"
        
    primary_hex = rgb_to_hex(*rgb)
    
    # Определяем яркость фона
    if (sum(rgb) / 3) > 127:
        bg_hex, bg_light_hex, text_hex, text_muted = "#ffffff", "#f0f0f0", "#000000", "#777777"
    else:
        bg_hex, bg_light_hex, text_hex, text_muted = "#181818", "#2c2c2c", "#ffffff", "#aaaaaa"
        
    # ИСПРАВЛЕНО: Безопасно вычитаем 20 из каждого канала RGB, чтобы цвет не ушел ниже нуля
    r_alpha = max(0, rgb[0] - 20)
    g_alpha = max(0, rgb[1] - 20)
    b_alpha = max(0, rgb[2] - 20)
    primary_alpha_hex = rgb_to_hex(r_alpha, g_alpha, b_alpha)
    
    try:
        return template.format(
            bg_color=bg_hex,
            bg_color_light=bg_light_hex,
            primary_color=primary_hex,
            primary_color_alpha=primary_alpha_hex,
            text_color=text_hex,
            text_color_muted=text_muted
        ).strip()
    except Exception as e:
        print(f"Ошибка форматирования: {e}")
        return template.strip()

# --- Хэндлеры бота ---
@dp.message(F.text == "/start")
async def start_cmd(message: types.Message):
    await message.answer("👋 Привет! Отправь мне картинку (как фото или как файл), и я соберу тему на основе актуального шаблона из GitHub!")

# Этот хэндлер теперь ловит И фотографии, И файлы картинок (PNG, JPG)
@dp.message(F.photo | (F.document & F.document.mime_type.startswith("image/")))
async def process_photo(message: types.Message):
    await message.answer("⏳ Загружаю свежий шаблон с GitHub и собираю тему...")
    try:
        # Определяем, фото это или документ, и берем ID файла
        if message.photo:
            file_id = message.photo[-1].file_id
        else:
            file_id = message.document.file_id
            
        print(f"Получен файл с ID: {file_id}. Начинаю скачивание...")
        
        file_info = await bot.get_file(file_id)
        photo_bytes = await bot.download_file(file_info.file_path)
        
        print("Фото успешно скачано. Запрашиваю шаблон с GitHub...")
        github_template = await download_template_from_github()
        
        print("Шаблон получен. Вычисляю доминантный цвет...")
        rgb = get_dominant_color(photo_bytes.read())
        
        print(f"Цвет определен: {rgb}. Форматирую тему...")
        theme_data = generate_theme_file(github_template, rgb)
        
        print("Тема сгенерирована. Отправляю пользователю...")
        theme_file = BufferedInputFile(theme_data.encode('utf-8'), filename="github_custom_theme.attheme")
        await message.answer_document(document=theme_file, caption="🎨 Твоя тема готова!")
        print("Файл успешно отправлен!")
        
    except Exception as e:
        print(f"КРИТИЧЕСКАЯ ОШИБКА: {e}")
        await message.answer(f"❌ Произошла ошибка внутри бота:\n`{str(e)}`", parse_mode="Markdown")

# --- Функция запуска вебхука через триггеры aiogram 3 ---
async def on_startup(bot: Bot) -> None:
    # Очищаем слэши у базового URL
    base_url = RENDER_EXTERNAL_URL.strip().rstrip('/')
    webhook_url = f"{base_url}/webhook"
    await bot.set_webhook(webhook_url)
    print(f"Вебхук успешно установлен на: {webhook_url}")

def main():
    # Регистрируем событие запуска в диспетчере aiogram
    dp.startup.register(on_startup)
    
    app = web.Application()
    
    # Официальный обработчик вебхуков aiogram 3
    webhook_requests_handler = SimpleRequestHandler(
        dispatcher=dp,
        bot=bot
    )
    # Регистрируем путь /webhook в aiohttp приложении
    webhook_requests_handler.register(app, path="/webhook")
    
    # Связываем приложение и диспетчер
    setup_application(app, dp, bot=bot)
    
    port = int(os.getenv("PORT", 10000))
    web.run_app(app, host='0.0.0.0', port=port)

if __name__ == '__main__':
    main()
