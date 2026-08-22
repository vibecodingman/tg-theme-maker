import os
import asyncio
import io
from aiogram import Bot, Dispatcher, types, F
from aiogram.types import BufferedInputFile
from aiogram.fsm.storage.memory import MemoryStorage
from aiohttp import web, ClientSession
from PIL import Image

# 1. Считываем переменные окружения
TOKEN = os.getenv("BOT_TOKEN")
RENDER_EXTERNAL_URL = os.getenv("RENDER_EXTERNAL_URL")

GITHUB_OWNER = os.getenv("GITHUB_OWNER", "")      
GITHUB_REPO = os.getenv("GITHUB_REPO", "")        
GITHUB_BRANCH = os.getenv("GITHUB_BRANCH", "main")  
GITHUB_FILE_PATH = os.getenv("GITHUB_FILE_PATH", "template.attheme") 

# 2. Инициализация бота
bot = Bot(token=TOKEN)
dp = Dispatcher(storage=MemoryStorage())

async def download_template_from_github() -> str:
    """Безопасное скачивание шаблона с GitHub"""
    owner = GITHUB_OWNER.strip().strip('/')
    repo = GITHUB_REPO.strip().strip('/')
    branch = GITHUB_BRANCH.strip().strip('/')
    file_path = GITHUB_FILE_PATH.strip().lstrip('/')
    
    url = f"https://githubusercontent.com{owner}/{repo}/{branch}/{file_path}"
    print(f"Скачивание шаблона по адресу: {url}")
    
    async with ClientSession() as session:
        async with session.get(url) as response:
            if response.status == 200:
                return await response.text(encoding='utf-8')
            print(f"Ошибка GitHub API! Статус: {response.status}")
            return "windowBackgroundWhite = {bg_color}\nactionBarDefault = {primary_color}"

def get_dominant_color(image_bytes: bytes) -> tuple:
    """Определение главного цвета через Pillow"""
    image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    image_small = image.resize((1, 1), resample=Image.Resampling.LANCZOS)
    return image_small.getpixel((0, 0))

def generate_theme_file(template: str, rgb: tuple) -> str:
    """Сборка констант темы"""
    def rgb_to_hex(r, g, b):
        return f"#{r:02x}{g:02x}{b:02x}"
        
    primary_hex = rgb_to_hex(*rgb)
    if (sum(rgb) / 3) > 127:
        bg_hex, bg_light_hex, text_hex, text_muted = "#ffffff", "#f0f0f0", "#000000", "#777777"
    else:
        bg_hex, bg_light_hex, text_hex, text_muted = "#181818", "#2c2c2c", "#ffffff", "#aaaaaa"
        
    primary_alpha_hex = rgb_to_hex(max(0, rgb[0]-20), max(0, rgb[1]-20), max(0, rgb[2]-20))
    
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

@dp.message(F.text == "/start")
async def start_cmd(message: types.Message):
    await message.answer("👋 Привет! Отправь мне картинку, и я соберу тему на основе актуального шаблона из GitHub!")

@dp.message(F.photo)
async def process_photo(message: types.Message):
    await message.answer("⏳ Загружаю свежий шаблон с GitHub и собираю тему...")
    try:
        photo = message.photo[-1]
        file_info = await bot.get_file(photo.file_id)
        photo_bytes = await bot.download_file(file_info.file_path)
        
        github_template = await download_template_from_github()
        rgb = get_dominant_color(photo_bytes.read())
        theme_data = generate_theme_file(github_template, rgb)
        
        theme_file = BufferedInputFile(theme_data.encode('utf-8'), filename="github_custom_theme.attheme")
        await message.answer_document(document=theme_file, caption="🎨 Твоя тема готова!")
    except Exception as e:
        await message.answer(f"❌ Произошла ошибка внутри бота:\n`{str(e)}`", parse_mode="Markdown")

# --- Вебхук эндпоинт ---
async def handle_webhook(request):
    try:
        update = types.Update.model_validate(await request.json(), context={"bot": bot})
        await dp.feed_update(bot, update)
    except Exception as e:
        print(f"Ошибка вебхука: {e}")
    return web.Response(text="OK")

async def on_startup(app):
    webhook_url = f"{RENDER_EXTERNAL_URL}/webhook"
    await bot.set_webhook(webhook_url)
    print(f"Сервер запущен. Вебхук: {webhook_url}")

async def on_shutdown(app):
    await bot.delete_webhook()

def main():
    app = web.Application()
    app.router.add_post('/webhook', handle_webhook)
    app.on_startup.append(on_startup)
    app.on_shutdown.append(on_shutdown)
    port = int(os.getenv("PORT", 10000))
    web.run_app(app, host='0.0.0.0', port=port)

if __name__ == '__main__':
    main()
