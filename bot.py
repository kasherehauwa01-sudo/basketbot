import asyncio
import os
import random
from pathlib import Path
from typing import Any

from aiogram import Bot, Dispatcher, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.types import FSInputFile, Message, Poll, PollAnswer

TOKEN = "PASTE_YOUR_BOT_TOKEN_HERE"
UNLOCK_MEDIA_PATH = Path(__file__).with_name("UNLOCKED.gif")
UNLOCK_TEXT = "Достигнуто: 7 игроков\nРазблокирован новый персонаж — @Ilhomchik_R"

router = Router()

polls: dict[str, dict[str, Any]] = {}

PLAYERS_SKILL = {
    "@imico699": "high",
    "@ProtsenkoMax": "high",
    "@Ilhomchik_R": "medium",
    "@Shutto4ka": "high",
    "@AnikoV": "medium",
    "@alexandrgritsuk": "medium",
    "Жека Богатый": "high",
    "@select_valentin": "medium",
    "@MrR1cco": "medium",
    "Михаил": "medium",
    "@Vitaliitreid": "medium",
    "@My_mf_life": "high",
    "@RomanGladyshko": "medium",
}

SKILL_TO_SCORE = {"high": 3, "medium": 2, "low": 1}

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


def get_player_score(player_name: str) -> int:
    # Если игрок не найден в справочнике, по ТЗ используем уровень medium.
    level = PLAYERS_SKILL.get(player_name)
    if level is None:
        level = PLAYERS_SKILL.get(player_name.lower())
    return SKILL_TO_SCORE.get(level or "medium", 2)


def balance_teams(team1: list[tuple[str, int]], team2: list[tuple[str, int]]) -> None:
    # Простая балансировка одним улучшающим обменом (swap), если разница > 1.
    score1 = sum(score for _, score in team1)
    score2 = sum(score for _, score in team2)
    current_diff = abs(score1 - score2)
    if current_diff <= 1:
        return

    for i, (_, s1) in enumerate(team1):
        for j, (_, s2) in enumerate(team2):
            new_score1 = score1 - s1 + s2
            new_score2 = score2 - s2 + s1
            new_diff = abs(new_score1 - new_score2)
            if new_diff < current_diff:
                team1[i], team2[j] = team2[j], team1[i]
                return


def generate_teams(voted_users: list[str]) -> str:
    # 1) Формируем пары (игрок, score) и перемешиваем для случайности внутри одинаковых уровней.
    users_with_scores = [(user, get_player_score(user)) for user in voted_users]
    random.shuffle(users_with_scores)

    # 2) Сортируем по силе по убыванию.
    users_with_scores = sorted(users_with_scores, key=lambda x: x[1], reverse=True)

    # 3) Делим "змейкой": 1,2,2,1,1,2,...
    team1: list[tuple[str, int]] = []
    team2: list[tuple[str, int]] = []
    snake_pattern = (1, 2, 2, 1)

    for i, player in enumerate(users_with_scores):
        if snake_pattern[i % 4] == 1:
            team1.append(player)
        else:
            team2.append(player)

    # 4) Балансировка одним улучшающим swap.
    balance_teams(team1, team2)

    # 5) Рандомно определяем, у какой команды мяч.
    ball_team = random.choice([1, 2])
    team1_header = "Команда 1 🏀:" if ball_team == 1 else "Команда 1:"
    team2_header = "Команда 2 🏀:" if ball_team == 2 else "Команда 2:"

    team1_lines = [f"* {name}" for name, _ in team1] or ["* —"]
    team2_lines = [f"* {name}" for name, _ in team2] or ["* —"]

    return "\n".join(
        [
            f"🏀 Проголосовало: {len(voted_users)} человек",
            "",
            team1_header,
            *team1_lines,
            "",
            team2_header,
            *team2_lines,
        ]
    )


def get_voted_users_for_first_option(poll_id: str) -> list[str]:
    poll_data = polls[poll_id]
    first_option_user_ids = poll_data["options"].get(0, {}).get("votes", set())
    user_labels = poll_data.get("user_labels", {})

    # Строим актуальный список отображаемых имен участников первого варианта.
    return [user_labels.get(user_id, str(user_id)) for user_id in sorted(first_option_user_ids)]


def build_combined_text(poll_id: str) -> str:
    poll_data = polls[poll_id]
    first_option_votes = poll_data["options"].get(0, {}).get("count", 0)
    voted_users = get_voted_users_for_first_option(poll_id)

    return "\n".join(
        [
            f"Количество игроков: {first_option_votes}",
            f"Стоимость игры: {format_game_cost(first_option_votes)} руб",
            "",
            generate_teams(voted_users),
        ]
    )


async def maybe_send_unlock_message(bot: Bot, poll_id: str) -> None:
    poll_data = polls.get(poll_id)
    if poll_data is None or poll_data.get("unlock_message_sent"):
        return

    first_option_votes = poll_data["options"].get(0, {}).get("count", 0)
    if first_option_votes > 7:
        if UNLOCK_MEDIA_PATH.exists():
            await bot.send_animation(
                chat_id=poll_data["chat_id"],
                animation=FSInputFile(UNLOCK_MEDIA_PATH),
                caption=UNLOCK_TEXT,
            )
        else:
            await bot.send_message(chat_id=poll_data["chat_id"], text=UNLOCK_TEXT)

        poll_data["unlock_message_sent"] = True


async def update_results_message(bot: Bot, poll_id: str) -> None:
    poll_data = polls.get(poll_id)
    if poll_data is None:
        return

    await bot.edit_message_text(
        chat_id=poll_data["chat_id"],
        message_id=poll_data["message_id"],
        text=build_combined_text(poll_id),
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
        "user_choices": {},
        "user_labels": {},
        "options": {
            option_id: {"text": option.text, "votes": set(), "count": option.voter_count}
            for option_id, option in enumerate(bot_poll_message.poll.options)
        },
    }

    results_message = await message.bot.send_message(
        chat_id=message.chat.id,
        text=build_combined_text(bot_poll_id),
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
    user_choices: dict[int, set[int]] = poll_data.setdefault("user_choices", {})
    new_choices = set(poll_answer.option_ids)
    if new_choices:
        user_choices[user_id] = new_choices
    else:
        user_choices.pop(user_id, None)

    username = poll_answer.user.username
    display_name = f"@{username}" if username else poll_answer.user.full_name
    poll_data.setdefault("user_labels", {})[user_id] = display_name

    # На каждом событии голоса полностью пересчитываем состояние с нуля на основе user_choices.
    for option in poll_data["options"].values():
        option["votes"].clear()

    for uid, option_ids in user_choices.items():
        for option_id in option_ids:
            option = poll_data["options"].get(option_id)
            if option is not None:
                option["votes"].add(uid)

    for option in poll_data["options"].values():
        option["count"] = len(option["votes"])

    poll_data["total_voter_count"] = sum(1 for option_ids in user_choices.values() if option_ids)

    await update_results_message(bot=poll_answer.bot, poll_id=poll_id)
    await maybe_send_unlock_message(bot=poll_answer.bot, poll_id=poll_id)


async def main() -> None:
    bot = Bot(token=get_token())
    dp = Dispatcher()
    dp.include_router(router)
    await bot.delete_webhook()
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
