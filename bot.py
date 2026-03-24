import asyncio
import os
from typing import Any

from aiogram import Bot, Dispatcher, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.types import Message, Poll, PollAnswer

TOKEN = "PASTE_YOUR_BOT_TOKEN_HERE"

router = Router()

polls: dict[str, dict[str, Any]] = {}

DIGIT_EMOJI = {
    "0": "0️⃣",
    "1": "1️⃣",
    "2": "2️⃣",
    "3": "3️⃣",
    "4": "4️⃣",
    "5": "5️⃣",
    "6": "6️⃣",
    "7": "7️⃣",
    "8": "8️⃣",
    "9": "9️⃣",
}


def number_to_emoji(n: int) -> str:
    return "".join(DIGIT_EMOJI[digit] for digit in str(n))


def get_token() -> str:
    env_token = os.getenv("token", "").strip()
    if env_token:
        return env_token

    legacy_env_token = os.getenv("BOT_TOKEN", "").strip()
    if legacy_env_token:
        return legacy_env_token

    token = TOKEN.strip()
    if token and token != "PASTE_YOUR_BOT_TOKEN_HERE":
        return token

    raise RuntimeError(
        "Токен не задан. Укажите токен в переменной окружения token "
        "(или BOT_TOKEN для обратной совместимости) "
        "или замените значение константы TOKEN в bot.py."
    )


def format_game_cost(first_option_votes: int) -> str:
    if first_option_votes <= 0:
        return "—"

    cost = 2250 / first_option_votes
    if cost.is_integer():
        return str(int(cost))
    return f"{cost:.2f}".replace(".", ",")


def build_results_text(poll_id: str) -> str:
    poll_data = polls[poll_id]
    lines = ["📊 Результаты голосования", ""]

    for option in poll_data["options"].values():
        votes_count = option.get("count", len(option["votes"]))
        lines.append(f'{option["text"]} — {number_to_emoji(votes_count)}')

    total_voters = poll_data.get(
        "total_voter_count",
        len({user_id for option in poll_data["options"].values() for user_id in option["votes"]}),
    )
    first_option_votes = poll_data["options"].get(0, {}).get("count", 0)
    lines.extend(
        [
            "",
            f"Всего: {total_voters} человек",
            f"Стоимость игры: {format_game_cost(first_option_votes)} руб",
        ]
    )
    return "\n".join(lines)


async def maybe_send_unlock_message(bot: Bot, poll_id: str) -> None:
    poll_data = polls.get(poll_id)
    if poll_data is None or poll_data.get("unlock_message_sent"):
        return

    first_option_votes = poll_data["options"].get(0, {}).get("count", 0)
    if first_option_votes > 7:
        await bot.send_message(
            chat_id=poll_data["chat_id"],
            text="Достигнуто: 7 игроков\nРазблокирован новый персонаж — @Ilhomchik_R",
        )
        poll_data["unlock_message_sent"] = True


async def update_results_message(bot: Bot, poll_id: str) -> None:
    poll_data = polls.get(poll_id)
    if poll_data is None:
        return

    await bot.edit_message_text(
        chat_id=poll_data["chat_id"],
        message_id=poll_data["message_id"],
        text=build_results_text(poll_id),
    )


async def resend_poll_from_bot(message: Message) -> None:
    poll = message.poll
    if poll is None:
        return

    options = [option.text for option in poll.options]
    poll_kwargs: dict[str, Any] = {
        "chat_id": message.chat.id,
        "question": poll.question,
        "options": options,
        "is_anonymous": False,
        "type": poll.type,
        "allows_multiple_answers": poll.allows_multiple_answers,
    }

    if poll.type == "quiz" and poll.correct_option_id is not None:
        poll_kwargs["correct_option_id"] = poll.correct_option_id
        if poll.explanation:
            poll_kwargs["explanation"] = poll.explanation
        if poll.explanation_entities:
            poll_kwargs["explanation_entities"] = poll.explanation_entities

    bot_poll_message = await message.bot.send_poll(**poll_kwargs)
    if bot_poll_message.poll is None:
        return

    bot_poll_id = bot_poll_message.poll.id
    polls[bot_poll_id] = {
        "chat_id": message.chat.id,
        "message_id": 0,
        "total_voter_count": bot_poll_message.poll.total_voter_count,
        "unlock_message_sent": False,
        "options": {
            option_id: {"text": option.text, "votes": set(), "count": option.voter_count}
            for option_id, option in enumerate(bot_poll_message.poll.options)
        },
    }

    results_message = await message.bot.send_message(
        chat_id=message.chat.id,
        text=build_results_text(bot_poll_id),
    )
    polls[bot_poll_id]["message_id"] = results_message.message_id

    try:
        await message.delete()
    except TelegramAPIError:
        pass


@router.message(F.poll)
async def handle_poll_message(message: Message) -> None:
    poll = message.poll
    if poll is None or poll.is_anonymous:
        return

    if message.from_user and message.from_user.is_bot:
        return

    await resend_poll_from_bot(message)


@router.poll()
async def handle_poll_update(poll: Poll) -> None:
    poll_data = polls.get(poll.id)
    if poll_data is None:
        return

    poll_data["total_voter_count"] = poll.total_voter_count

    for option_id, option in enumerate(poll.options):
        if option_id in poll_data["options"]:
            poll_data["options"][option_id]["text"] = option.text
            poll_data["options"][option_id]["count"] = option.voter_count

    await update_results_message(bot=poll.bot, poll_id=poll.id)
    await maybe_send_unlock_message(bot=poll.bot, poll_id=poll.id)


@router.poll_answer()
async def handle_poll_answer(poll_answer: PollAnswer) -> None:
    poll_id = poll_answer.poll_id
    poll_data = polls.get(poll_id)
    if poll_data is None:
        return

    user_id = poll_answer.user.id

    for option in poll_data["options"].values():
        option["votes"].discard(user_id)

    for option_id in poll_answer.option_ids:
        if option_id in poll_data["options"]:
            poll_data["options"][option_id]["votes"].add(user_id)

    for option in poll_data["options"].values():
        option["count"] = len(option["votes"])

    if poll_answer.option_ids:
        poll_data["total_voter_count"] = max(
            poll_data.get("total_voter_count", 0),
            len({uid for option in poll_data["options"].values() for uid in option["votes"]}),
        )
    else:
        poll_data["total_voter_count"] = len(
            {uid for option in poll_data["options"].values() for uid in option["votes"]}
        )

    await update_results_message(bot=poll_answer.bot, poll_id=poll_id)
    await maybe_send_unlock_message(bot=poll_answer.bot, poll_id=poll_id)


async def main() -> None:
    bot = Bot(token=get_token())
    dp = Dispatcher()
    dp.include_router(router)
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
