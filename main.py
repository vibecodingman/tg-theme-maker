import os
import io
from aiogram import Bot, Dispatcher, types, F
from aiogram.types import BufferedInputFile
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web, ClientSession
from PIL import Image

TOKEN = os.getenv("BOT_TOKEN")
RENDER_EXTERNAL_URL = os.getenv("RENDER_EXTERNAL_URL")

bot = Bot(token=TOKEN)
dp = Dispatcher(storage=MemoryStorage())

async def download_template_from_github() -> str:
    url = "https://githubusercontent.com"
    fallback_template = "windowBackgroundWhite = {bg_color}\nactionBarDefault = {primary_color}"
    try:
        async with ClientSession() as session:
            async with session.get(url, timeout=5) as response:
                if response.status == 200:
                    return await response.text(encoding='utf-8')
                return fallback_template
    except Exception:
        return fallback_template

def get_advanced_palette(image_bytes: bytes) -> dict:
    """Вытаскивает палитру и распределяет цвета исключительно на основе картинки"""
    image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    image.thumbnail((200, 200))
    
    quantized = image.quantize(colors=5, method=Image.Quantize.MAXCOVERAGE)
    palette = quantized.getpalette()[:15]
    
    colors = [tuple(palette[i:i+3]) for i in range(0, len(palette), 3)]
    
    # Сортируем от самого темного к самому светлому
    colors.sort(key=lambda rgb: sum(rgb) / 3)
    
    def rgb_to_hex(rgb_tuple):
        return f"#{rgb_tuple[0]:02x}{rgb_tuple[1]:02x}{rgb_tuple[2]:02x}"

    # Считаем яркость самого частого цвета (фона)
    bg_rgb = colors[0]
    bg_brightness = sum(bg_rgb) / 3
    
    # Автоматически определяем контрастный цвет текста
    if bg_brightness > 127:
        text_hex = "#000000"
        text_muted_hex = "#666666"
    else:
        text_hex = "#ffffff"
        text_muted_hex = "#aaaaaa"

    # Берем цвета строго из картинки!
    return {
        "bg_color": rgb_to_hex(colors[0]),          # Самый глубокий темный цвет картинки
        "bg_color_light": rgb_to_hex(colors[1]),    # Чуть светлее для панелей чата
        "primary_color": rgb_to_hex(colors[-1]),    # Самый яркий/светлый акцент (салатовый!)
        "primary_color_alpha": rgb_to_hex(colors[-2]), # Второй по яркости для выделения
        "text_color": text_hex,                     # Контрастный текст (белый или черный)
        "text_muted": text_muted_hex
    }

def generate_theme_file(template: str, palette: dict) -> str:
    """Подставляет готовую палитру в шаблон"""
    try:
        return template.format(**palette).strip()
    except Exception as e:
        print(f"Ошибка форматирования: {e}")
        return template.strip()

# --- Хэндлеры бота ---
@dp.message(F.text == "/start")
async def start_cmd(message: types.Message):
    await message.answer("👋 Привет! Отправь мне картинку, и я соберу сочную тему на основе нового алгоритма палитры!")

@dp.message(F.photo | (F.document & F.document.mime_type.startswith("image/")))
async def process_photo(message: types.Message):
    await message.answer("⏳ Магия Pillow: раскладываю картинку на спектр и собираю тему...")
    try:
        file_id = message.photo[-1].file_id if message.photo else message.document.file_id
        file_info = await bot.get_file(file_id)
        photo_bytes = await bot.download_file(file_info.file_path)
        
        github_template = await download_template_from_github()
        
        # Получаем умную палитру вместо одного цвета
        palette = get_advanced_palette(photo_bytes.read())
        
        theme_data = generate_theme_file(github_template, palette)
        
        theme_file = BufferedInputFile(theme_data.encode('utf-8'), filename="premium_custom_theme.attheme")
        await message.answer_document(document=theme_file, caption="🎨 Твоя сочная тема готова! Примени её, чтобы оценить контраст.")
    except Exception as e:
        await message.answer(f"❌ Произошла ошибка внутри бота:\n`{str(e)}`", parse_mode="Markdown")

async def on_startup(bot: Bot) -> None:
    base_url = RENDER_EXTERNAL_URL.strip().rstrip('/')
    webhook_url = f"{base_url}/webhook"
    await bot.set_webhook(webhook_url)

def main():
    dp.startup.register(on_startup)
    app = web.Application()
    webhook_requests_handler = SimpleRequestHandler(dispatcher=dp, bot=bot)
    webhook_requests_handler.register(app, path="/webhook")
    setup_application(app, dp, bot=bot)
    port = int(os.getenv("PORT", 10000))
    web.run_app(app, host='0.0.0.0', port=port)

if __name__ == '__main__':
    main()
