import os
import requests
from datetime import datetime, timedelta
from flask import Flask, request, jsonify
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
SYSTEM_PROMPT = os.environ.get("SYSTEM_PROMPT", "Ты дружелюбный ассистент.")

conversations = {}
MAX_HISTORY = 40
SESSION_TTL = 24


def get_messages(conv_id):
    now = datetime.utcnow()
    expired = [k for k, v in conversations.items()
               if now - v["last_active"] > timedelta(hours=SESSION_TTL)]
    for k in expired:
        del conversations[k]
    if conv_id not in conversations:
        conversations[conv_id] = {"messages": [], "last_active": now}
    else:
        conversations[conv_id]["last_active"] = now
    return conversations[conv_id]["messages"]


@app.route("/", methods=["GET"])
def health():
    return jsonify({"status": "ok", "service": "QIP Mini App Backend"})


@app.route("/chat", methods=["POST"])
def chat():
    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "No JSON"}), 400

        conv_id = data.get("conversation_id", "default")
        user_message = data.get("message", "").strip()

        if not user_message:
            return jsonify({"error": "Empty message"}), 400

        messages = get_messages(conv_id)
        messages.append({"role": "user", "content": user_message})

        if len(messages) > MAX_HISTORY:
            messages = messages[-MAX_HISTORY:]
            conversations[conv_id]["messages"] = messages

        resp = requests.post(
    "https://aiprime.store/v1/messages",
            headers={
                "x-api-key": ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": "claude-sonnet-4-20250514",
                "max_tokens": 2048,
                "system": SYSTEM_PROMPT,
                "messages": messages,
            },
            timeout=60,
        )

        resp.raise_for_status()
        reply = resp.json()["content"][0]["text"]

        messages.append({"role": "assistant", "content": reply})

        return jsonify({"reply": reply, "conversation_id": conv_id})

    except requests.HTTPError as e:
        app.logger.error(f"Anthropic HTTP error: {e}")
        return jsonify({"error": str(e)}), 502
    except Exception as e:
        app.logger.error(f"Error: {e}")
        return jsonify({"error": "Internal error"}), 500


@app.route("/clear", methods=["POST"])
def clear():
    data = request.get_json()
    conv_id = data.get("conversation_id", "default") if data else "default"
    if conv_id in conversations:
        conversations[conv_id]["messages"] = []
    return jsonify({"status": "cleared"})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
