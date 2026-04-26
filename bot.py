import asyncio
import os
import random
from pathlib import Path
from typing import Any

from aiogram import Bot, Dispatcher, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.types import FSInputFile, Message, Poll, PollAnswer

TOKEN = "8794835785:AAEVOQlEI7H2fep4Dut_MVOdpacBZZ6sdNc"
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


def get_display_name(user: dict[str, Any]) -> str:
    first_name = (user.get("first_name") or "").strip()
    last_name = (user.get("last_name") or "").strip()
    username = (user.get("username") or "").strip()

    if first_name and last_name:
        return f"{first_name} {last_name}"
    if first_name:
        return first_name
    if username:
        return f"@{username}"
    return "Без имени"


def get_player_score(user: dict[str, Any]) -> int:
    # Для определения уровня по ТЗ используем username, иначе medium.
    username = (user.get("username") or "").strip()
    username_key = f"@{username}" if username else ""
    level = PLAYERS_SKILL.get(username_key)
    if level is None:
        level = PLAYERS_SKILL.get(username_key.lower())
    return SKILL_TO_SCORE.get(level or "medium", 2)


def balance_teams(team1: list[dict[str, Any]], team2: list[dict[str, Any]]) -> None:
    # Простая балансировка одним улучшающим обменом (swap), если разница > 1.
    score1 = sum(player["score"] for player in team1)
    score2 = sum(player["score"] for player in team2)
    current_diff = abs(score1 - score2)
    if current_diff <= 1:
        return

    for i, player1 in enumerate(team1):
        s1 = player1["score"]
        for j, player2 in enumerate(team2):
            s2 = player2["score"]
            new_score1 = score1 - s1 + s2
            new_score2 = score2 - s2 + s1
            new_diff = abs(new_score1 - new_score2)
            if new_diff < current_diff:
                team1[i], team2[j] = team2[j], team1[i]
                return


def split_by_snake(players: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    shuffled_players = players[:]
    random.shuffle(shuffled_players)
    sorted_players = sorted(shuffled_players, key=lambda p: p["score"], reverse=True)

    team1: list[dict[str, Any]] = []
    team2: list[dict[str, Any]] = []
    snake_pattern = (1, 2, 2, 1)

    for i, player in enumerate(sorted_players):
        if snake_pattern[i % 4] == 1:
            team1.append(player)
        else:
            team2.append(player)

    balance_teams(team1, team2)
    return team1, team2


def team_power(team_main: list[dict[str, Any]]) -> int:
    # Сила считается только по main-составу.
    return sum(player["score"] for player in team_main)


def generate_teams(voted_users: list[dict[str, Any]], ball_team: int | None = None) -> str:
    # Убираем дубли по user.id и сохраняем актуальные данные пользователя.
    users_by_id: dict[int, dict[str, Any]] = {}
    for user in voted_users:
        user_id = user.get("id")
        if isinstance(user_id, int):
            users_by_id[user_id] = user

    normalized_users: list[dict[str, Any]] = []
    for user in users_by_id.values():
        normalized_users.append(
            {
                **user,
                "display_name": get_display_name(user),
                "score": get_player_score(user),
            }
        )

    # Базовая структура состояния команд.
    teams: dict[str, list[dict[str, Any]]] = {
        "team1_main": [],
        "team2_main": [],
        "team1_extra": [],
        "team2_extra": [],
    }

    total_players = len(normalized_users)

    # До 10 игроков — обычная логика балансировки без отдельного запаса.
    if total_players <= 10:
        team1, team2 = split_by_snake(normalized_users)
        teams["team1_main"] = team1
        teams["team2_main"] = team2
    else:
        # Для 11+ сначала формируем основу из первых 10 (5 на 5).
        first_ten = normalized_users[:10]
        team1, team2 = split_by_snake(first_ten)
        teams["team1_main"] = team1[:5]
        teams["team2_main"] = team2[:5]

        # Дополнительных игроков обрабатываем отдельно, без полной пересборки обеих команд.
        for new_player in normalized_users[10:]:
            score = new_player["score"]
            if score == 1:
                # LOW: сразу в запас более слабой команды.
                if team_power(teams["team1_main"]) <= team_power(teams["team2_main"]):
                    teams["team1_extra"].append(new_player)
                else:
                    teams["team2_extra"].append(new_player)
                continue

            if score == 2:
                # MEDIUM: HIGH фиксированы, нового MEDIUM направляем в более слабую команду.
                if team_power(teams["team1_main"]) <= team_power(teams["team2_main"]):
                    target_main = teams["team1_main"]
                    target_extra = teams["team1_extra"]
                else:
                    target_main = teams["team2_main"]
                    target_extra = teams["team2_extra"]

                target_main.append(new_player)
                if len(target_main) > 5:
                    medium_candidates = [p for p in target_main if p["score"] == 2]
                    if medium_candidates:
                        moved_player = random.choice(medium_candidates)
                        target_main.remove(moved_player)
                        target_extra.append(moved_player)
                continue

            # HIGH: перераспределяем только HIGH+MEDIUM в main, затем случайный MEDIUM отправляется в extra.
            main_high_medium = [
                *[p for p in teams["team1_main"] if p["score"] >= 2],
                *[p for p in teams["team2_main"] if p["score"] >= 2],
                new_player,
            ]

            rebuilt_t1, rebuilt_t2 = split_by_snake(main_high_medium)
            teams["team1_main"] = rebuilt_t1[:]
            teams["team2_main"] = rebuilt_t2[:]

            # Оставляем main размером 5 на 5 за счёт случайного MEDIUM из той команды, где он есть.
            while len(teams["team1_main"]) > 5:
                medium_candidates = [p for p in teams["team1_main"] if p["score"] == 2]
                if not medium_candidates:
                    break
                moved_player = random.choice(medium_candidates)
                teams["team1_main"].remove(moved_player)
                teams["team1_extra"].append(moved_player)

            while len(teams["team2_main"]) > 5:
                medium_candidates = [p for p in teams["team2_main"] if p["score"] == 2]
                if not medium_candidates:
                    break
                moved_player = random.choice(medium_candidates)
                teams["team2_main"].remove(moved_player)
                teams["team2_extra"].append(moved_player)

            # Если после перераспределения все еще >10 игроков в main, переносим MEDIUM из более длинной команды.
            while len(teams["team1_main"]) + len(teams["team2_main"]) > 10:
                source_main = (
                    teams["team1_main"]
                    if len(teams["team1_main"]) >= len(teams["team2_main"])
                    else teams["team2_main"]
                )
                source_extra = (
                    teams["team1_extra"] if source_main is teams["team1_main"] else teams["team2_extra"]
                )
                medium_candidates = [p for p in source_main if p["score"] == 2]
                if not medium_candidates:
                    break
                moved_player = random.choice(medium_candidates)
                source_main.remove(moved_player)
                source_extra.append(moved_player)

    resolved_ball_team = ball_team if ball_team in {1, 2} else random.choice([1, 2])
    team1_header = "Команда 1 🏀:" if resolved_ball_team == 1 else "Команда 1:"
    team2_header = "Команда 2 🏀:" if resolved_ball_team == 2 else "Команда 2:"
    team1_main_lines = [f"* {player['display_name']}" for player in teams["team1_main"]] or ["* —"]
    team1_extra_lines = [f"* {player['display_name']}" for player in teams["team1_extra"]] or ["* —"]
    team2_main_lines = [f"* {player['display_name']}" for player in teams["team2_main"]] or ["* —"]
    team2_extra_lines = [f"* {player['display_name']}" for player in teams["team2_extra"]] or ["* —"]

    return "\n".join(
        [
            team1_header,
            *team1_main_lines,
            *team1_extra_lines,
            "",
            team2_header,
            *team2_main_lines,
            *team2_extra_lines,
        ]
    )


def get_voted_users_for_first_option(poll_id: str) -> list[dict[str, Any]]:
    poll_data = polls[poll_id]
    first_option_user_ids = poll_data["options"].get(0, {}).get("votes", set())
    user_profiles: dict[int, dict[str, Any]] = poll_data.get("user_profiles", {})

    # Строим актуальный список пользователей, проголосовавших за первый вариант.
    return [user_profiles[user_id] for user_id in sorted(first_option_user_ids) if user_id in user_profiles]


def build_combined_text(poll_id: str) -> str:
    poll_data = polls[poll_id]
    first_option_votes = poll_data["options"].get(0, {}).get("count", 0)
    total_voted = poll_data.get("total_voter_count", 0)
    voted_users = get_voted_users_for_first_option(poll_id)
    ball_team = poll_data.get("ball_team")

    # Мяч фиксируется только при достижении 10 игроков и дальше не меняется.
    if first_option_votes >= 10 and ball_team not in {1, 2}:
        ball_team = random.choice([1, 2])
        poll_data["ball_team"] = ball_team
    elif first_option_votes < 10:
        poll_data["ball_team"] = None
        ball_team = None

    return "\n".join(
        [
            f"Всего игроков: {first_option_votes} человек",
            f"Проголосовавших: {total_voted} человек",
            f"Стоимость игры: {format_game_cost(first_option_votes)} руб",
            "",
            generate_teams(voted_users, ball_team=ball_team),
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
        "user_profiles": {},
        "ball_team": None,
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

    poll_data.setdefault("user_profiles", {})[user_id] = {
        "id": poll_answer.user.id,
        "username": poll_answer.user.username,
        "first_name": poll_answer.user.first_name,
        "last_name": poll_answer.user.last_name,
    }

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
