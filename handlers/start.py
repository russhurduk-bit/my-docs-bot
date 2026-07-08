from aiogram import Router, F
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton

router = Router()

MAIN_KB = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="📄 Новый документ"), KeyboardButton(text="👤 Мой профиль")],
        [KeyboardButton(text="🗂 Мои документы"), KeyboardButton(text="❓ Помощь")],
    ],
    resize_keyboard=True,
)

WELCOME = (
    "Привет! Я <b>Мои Документы</b> — личный юрист-документовед.\n\n"
    "Опиши ситуацию своими словами — подготовлю нужные бумаги в PDF со ссылками "
    "на актуальные статьи законов РФ.\n\n"
    "<b>Что я умею:</b>\n"
    "• Договоры (купли-продажи, аренды, услуг, подряда, займа)\n"
    "• Заявления (налоговая, суд, работодатель, ЖКХ, паспортный стол)\n"
    "• Претензии и жалобы (ЗоЗПП, Роспотребнадзор, прокуратура)\n"
    "• Доверенности, расписки, акты\n"
    "• Трудовые документы (приём, увольнение, отпуск, приказы)\n"
    "• Исковые заявления в суд\n"
    "• Заявления на документы (паспорт, загран, СНИЛС, ИНН, водительское)\n\n"
    "Для начала — заполни профиль: /profile\n"
    "Или просто напиши что тебе нужно."
)

HELP_TEXT = (
    "<b>Как пользоваться:</b>\n\n"
    "1️⃣ Заполни профиль (/profile) — паспорт, ИНН, СНИЛС, адрес. "
    "Эти данные будут автоматически подставляться во все документы.\n\n"
    "2️⃣ Опиши ситуацию свободным текстом. Примеры:\n"
    "• «Нужен договор купли-продажи авто, покупаю Toyota Camry 2020 за 1.5 млн у Иванова И.И.»\n"
    "• «Сосед затопил квартиру, составь акт и претензию»\n"
    "• «Заявление на увольнение по собственному с 1 мая»\n"
    "• «Доверенность на получение почты на маму»\n"
    "• «Жалоба в Роспотребнадзор — DNS не возвращает деньги за брак»\n\n"
    "3️⃣ Я задам недостающие вопросы и пришлю готовые PDF.\n\n"
    "<b>Команды:</b>\n"
    "/profile — мои данные\n"
    "/vault — моё хранилище сканов\n"
    "/find &lt;слово&gt; — найти документ в хранилище\n"
    "/history — мои сгенерированные документы\n"
    "/reset — сбросить текущий диалог\n"
)


@router.message(CommandStart())
async def cmd_start(message: Message):
    await message.answer(WELCOME, parse_mode="HTML", reply_markup=MAIN_KB)


@router.message(Command("help"))
@router.message(F.text == "❓ Помощь")
async def cmd_help(message: Message):
    await message.answer(HELP_TEXT, parse_mode="HTML")


@router.message(Command("reset"))
async def cmd_reset(message: Message):
    from config import owner_id
    from db import clear_dialog_state
    await clear_dialog_state(owner_id(message.from_user.id))
    await message.answer("Текущий диалог сброшен. Опиши новую задачу.")


@router.message(F.text == "📄 Новый документ")
async def btn_new_doc(message: Message):
    await message.answer(
        "Опиши что нужно — своими словами.\n\n"
        "Примеры:\n"
        "• «договор аренды квартиры на год, сдаю за 45 тыс/мес»\n"
        "• «претензия в магазин — не принимают возврат ноутбука»\n"
        "• «заявление на замену паспорта в 45 лет»"
    )
