"""FSM-диалог заполнения профиля + /profile для просмотра."""
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message

from config import owner_id
from db import PROFILE_FIELDS, get_profile, upsert_profile

router = Router()

FIELD_LABELS = {
    "full_name": "ФИО (полностью)",
    "birth_date": "Дата рождения (ДД.ММ.ГГГГ)",
    "birth_place": "Место рождения (как в паспорте)",
    "passport_series": "Серия паспорта (4 цифры)",
    "passport_number": "Номер паспорта (6 цифр)",
    "passport_issued": "Кем выдан паспорт",
    "passport_date": "Дата выдачи паспорта (ДД.ММ.ГГГГ)",
    "passport_code": "Код подразделения (XXX-XXX)",
    "inn": "ИНН (12 цифр)",
    "snils": "СНИЛС (XXX-XXX-XXX XX)",
    "address_reg": "Адрес регистрации (полностью с индексом)",
    "address_live": "Адрес фактического проживания (если отличается, иначе «—»)",
    "phone": "Телефон (+7...)",
    "email": "Email",
}


class ProfileFSM(StatesGroup):
    editing = State()


def _render_profile(p: dict) -> str:
    lines = ["<b>Мой профиль:</b>\n"]
    for k in PROFILE_FIELDS:
        v = p.get(k) or "—"
        lines.append(f"<b>{FIELD_LABELS[k]}:</b> {v}")
    return "\n".join(lines)


@router.message(Command("profile"))
@router.message(F.text == "👤 Мой профиль")
async def cmd_profile(message: Message, state: FSMContext):
    await state.clear()
    p = await get_profile(owner_id(message.from_user.id))
    text = _render_profile(p)
    text += "\n\nЧтобы заполнить/изменить — /edit_profile"
    await message.answer(text, parse_mode="HTML")


@router.message(Command("edit_profile"))
async def cmd_edit_profile(message: Message, state: FSMContext):
    p = await get_profile(owner_id(message.from_user.id))
    await state.set_state(ProfileFSM.editing)
    # начинаем с первого незаполненного поля
    to_fill = [f for f in PROFILE_FIELDS if not p.get(f)]
    if not to_fill:
        to_fill = PROFILE_FIELDS[:]
    await state.update_data(queue=to_fill)
    await _ask_next(message, state)


async def _ask_next(message: Message, state: FSMContext):
    data = await state.get_data()
    queue = data.get("queue", [])
    if not queue:
        await state.clear()
        p = await get_profile(owner_id(message.from_user.id))
        await message.answer("Профиль сохранён ✅\n\n" + _render_profile(p), parse_mode="HTML")
        return
    field = queue[0]
    await message.answer(
        f"<b>{FIELD_LABELS[field]}</b>\n\nВведи значение или напиши /skip чтобы пропустить, /stop чтобы закончить.",
        parse_mode="HTML",
    )


@router.message(ProfileFSM.editing, Command("stop"))
async def fsm_stop(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Редактирование завершено.")


@router.message(ProfileFSM.editing, Command("skip"))
async def fsm_skip(message: Message, state: FSMContext):
    data = await state.get_data()
    queue = data.get("queue", [])
    if queue:
        queue = queue[1:]
        await state.update_data(queue=queue)
    await _ask_next(message, state)


@router.message(ProfileFSM.editing, F.text)
async def fsm_value(message: Message, state: FSMContext):
    data = await state.get_data()
    queue = data.get("queue", [])
    if not queue:
        await state.clear()
        return
    field = queue[0]
    value = (message.text or "").strip()
    if value and value != "—":
        await upsert_profile(owner_id(message.from_user.id), {field: value})
    await state.update_data(queue=queue[1:])
    await _ask_next(message, state)
