import os
import asyncio
import io
from aiogram import Bot, Dispatcher, types, F
from aiogram.types import BufferedInputFile
from aiogram.fsm.storage.memory import MemoryStorage
from aiohttp import web, ClientSession
from PIL import Image

# Токены и URL из переменных окружения Render
TOKEN = os.getenv("BOT_TOKEN")
RENDER_EXTERNAL_URL = os.getenv("RENDER_EXTERNAL_URL")

# Настройки GitHub (заполняются в панели Render)
GITHUB_OWNER = os.getenv("GITHUB_OWNER")      # Ваше имя пользователя на GitHub
GITHUB_REPO = os.getenv("GITHUB_REPO")        # Название вашего репозитория
GITHUB_BRANCH = os.getenv("GITHUB_BRANCH", "main")  # Ветка (обычно main или master)
GITHUB_FILE_PATH = os.getenv("GITHUB_FILE_PATH", "template.attheme") # Путь к файлу шаблона в репо

bot = Bot(token=TOKEN)
dp = Dispatcher(storage=MemoryStorage())

async def download_template_from_github() -> str:
    """Скачивает сырой файл шаблона темы из репозитория GitHub"""
    # Используем URL для получения raw-контента файла
    url = f"https://githubusercontent.com{GITHUB_OWNER}/{GITHUB_REPO}/{GITHUB_BRANCH}/{GITHUB_FILE_PATH}"
    
    async with ClientSession() as session:
        async with session.get(url) as response:
            if response.status == 200:
                return await response.text(encoding='utf-8')
            else:
                # На случай ошибки вернем базовый встроенный шаблон, чтобы бот не падал
                print(f"Ошибка скачивания с GitHub: {response.status}")
                return "windowBackgroundWhite = {bg_color}\nactionBarDefault = {primary_color}"

def get_dominant_color(image_bytes: bytes) -> tuple:
    """Определяет доминантный цвет картинки"""
    image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    image_small = image.resize((1, 1), resample=Image.Resampling.LANCZOS)
    return image_small.getpixel((0, 0))

def generate_theme_file(template: str, rgb: tuple) -> str:
    """Подставляет цвета в шаблон, скачанный с GitHub"""
    def rgb_to_hex(r, g, b):
        return f"#{r:02x}{g:02x}{b:02x}"

    primary_hex = rgb_to_hex(*rgb)
    brightness = sum(rgb) / 3
    
    # Логика подбора контрастного фона
    if brightness > 127:
        bg_hex = "#ffffff"
        bg_light_hex = "#f0f0f0"
        text_hex = "#000000"
        text_muted = "#777777"
    else:
        bg_hex = "#181818"
        bg_light_hex = "#2c2c2c"
        text_hex = "#ffffff"
        text_muted = "#aaaaaa"
        
    primary_alpha_hex = rgb_to_hex(max(0, rgb[0]-20), max(0, rgb[1]-20), max(0, rgb[2]-20))

    # Шаблон на GitHub должен содержать плейсхолдеры вроде {bg_color}, {primary_color} и т.д.
    try:
        theme_content = template.format(
            bg_color=bg_hex,
            bg_color_light=bg_light_hex,
            primary_color=primary_hex,
            primary_color_alpha=primary_alpha_hex,
            text_color=text_hex,
            text_color_muted=text_muted
        )
    except KeyError as e:
        # Если в файле на GitHub есть лишние фигурные скобки {}, форматтер выдаст ошибку.
        # Защита: просто возвращаем исходный текст, если что-то пошло не так
        print(f"Ошибка форматирования шаблона: {e}")
        theme_content = template

    return theme_content.strip()

@dp.message(F.text == "/start")
async def start_cmd(message: types.Message):
    await message.answer("👋 Привет! Отправь мне картинку, и я соберу тему на основе актуального шаблона из GitHub!")

@dp.message(F.photo)
async def process_photo(message: types.Message):
    await message.answer("⏳ Загружаю свежий шаблон с GitHub и собираю тему...")
    
    try:
        # 1. Скачиваем фото пользователя
        photo = message.photo[-1]
        file_info = await bot.get_file(photo.file_id)
        photo_bytes = await bot.download_file(file_info.file_path)
        
        # 2. Скачиваем шаблон из GitHub
        github_template = await download_template_from_github()
        
        # 3. Определяем цвет
        rgb = get_dominant_color(photo_bytes.read())
        
        # 4. Генерируем тему
        theme_data = generate_theme_file(github_template, rgb)
        
        # 5. Отправляем файл
        theme_file = BufferedInputFile(theme_data.encode('utf-8'), filename="github_custom_theme.attheme")
        await message.answer_document(document=theme_file, caption="🎨 Твоя тема готова!")
        
    except Exception as e:
        # Если что-то пойдет не так, бот пришлет точный текст ошибки прямо в чат
        await message.answer(f"❌ Произошла ошибка внутри бота:\n`{str(e)}`", parse_mode="Markdown")
        
# --- Настройка Webhook для Render ---
async def handle_webhook(request):
    url = str(request.url)
    index = url.rfind('/')
    token = url[index+1:]
    
    if token == TOKEN:
        update = types.Update.model_validate(await request.json(), context={"bot": bot})
        await dp.feed_update(bot, update)
        return web.Response()
    return web.Response(status=403)

async def on_startup(app):
    webhook_url = f"{RENDER_EXTERNAL_URL}/webhook/{TOKEN}"
    await bot.set_webhook(webhook_url)

async def on_shutdown(app):
    await bot.delete_webhook()

def main():
    app = web.Application()
    app.router.add_post(f'/webhook/{TOKEN}', handle_webhook)
    app.on_startup.append(on_startup)
    app.on_shutdown.append(on_shutdown)
    
    port = int(os.getenv("PORT", 10000))
    web.run_app(app, host='0.0.0.0', port=port)

if __name__ == '__main__':
    main()
