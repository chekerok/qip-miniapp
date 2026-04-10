"""
Backend для QIP Mini App
Проксирует запросы к Claude API, хранит историю разговоров в памяти.

Деплой на Render.com:
  1. Создай новый Web Service
  2. Укажи Start Command: gunicorn app:app
  3. Добавь переменные окружения:
     ANTHROPIC_API_KEY = sk-ant-...
     SYSTEM_PROMPT     = (твой system prompt, можно очень длинный)
"""

import os
import json
from datetime import datetime, timedelta
from flask import Flask, request, jsonify
from flask_cors import CORS
import anthropic

app = Flask(__name__)
CORS(app)  # Разрешаем запросы с GitHub Pages

# ─── Клиент Anthropic ───────────────────────────────────────────────
client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY", ""))

# ─── System prompt ──────────────────────────────────────────────────
# Берётся из переменной окружения SYSTEM_PROMPT
# Можно вставить хоть 150k слов — передаётся в каждом запросе
SYSTEM_PROMPT = os.environ.get("SYSTEM_PROMPT", "Ты дружелюбный ассистент.")

# ─── Хранилище истории (in-memory) ──────────────────────────────────
# Структура: { conversation_id: { messages: [...], last_active: datetime } }
conversations = {}

# Максимальное количество сообщений в истории (туда-обратно = 2 на обмен)
MAX_HISTORY_MESSAGES = 40

# Удалять неактивные разговоры через N часов
SESSION_TTL_HOURS = 24


def get_or_create_conversation(conv_id: str) -> list:
    """Возвращает историю сообщений для данного conversation_id."""
    now = datetime.utcnow()

    # Чистим старые сессии
    expired = [
        k for k, v in conversations.items()
        if now - v["last_active"] > timedelta(hours=SESSION_TTL_HOURS)
    ]
    for k in expired:
        del conversations[k]

    if conv_id not in conversations:
        conversations[conv_id] = {"messages": [], "last_active": now}
    else:
        conversations[conv_id]["last_active"] = now

    return conversations[conv_id]["messages"]


def trim_history(messages: list) -> list:
    """Обрезаем историю если она слишком длинная."""
    if len(messages) > MAX_HISTORY_MESSAGES:
        # Оставляем первые 2 (начало разговора) + последние N
        return messages[:2] + messages[-(MAX_HISTORY_MESSAGES - 2):]
    return messages


@app.route("/", methods=["GET"])
def health():
    return jsonify({"status": "ok", "service": "QIP Mini App Backend"})


@app.route("/chat", methods=["POST"])
def chat():
    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "No JSON body"}), 400

        conv_id = data.get("conversation_id", "default")
        user_message = data.get("message", "").strip()
        user_name = data.get("user_name", "Пользователь")

        if not user_message:
            return jsonify({"error": "Empty message"}), 400

        # Получаем историю
        messages = get_or_create_conversation(conv_id)

        # Добавляем сообщение пользователя
        messages.append({
            "role": "user",
            "content": user_message
        })

        # Обрезаем если нужно
        messages = trim_history(messages)
        conversations[conv_id]["messages"] = messages

        # Запрос к Claude
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=2048,
            system=SYSTEM_PROMPT,
            messages=messages
        )

        reply = response.content[0].text

        # Добавляем ответ ассистента в историю
        messages.append({
            "role": "assistant",
            "content": reply
        })

        return jsonify({
            "reply": reply,
            "conversation_id": conv_id,
            "message_count": len(messages)
        })

    except anthropic.APIStatusError as e:
        app.logger.error(f"Anthropic API error: {e}")
        return jsonify({"error": f"API error: {e.status_code}"}), 502

    except Exception as e:
        app.logger.error(f"Unexpected error: {e}")
        return jsonify({"error": "Internal server error"}), 500


@app.route("/clear", methods=["POST"])
def clear():
    """Очищает историю разговора."""
    try:
        data = request.get_json()
        conv_id = data.get("conversation_id", "default") if data else "default"

        if conv_id in conversations:
            conversations[conv_id]["messages"] = []

        return jsonify({"status": "cleared", "conversation_id": conv_id})

    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
