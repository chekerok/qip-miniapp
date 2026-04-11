import os
import requests
from datetime import datetime, timedelta
from flask import Flask, request, jsonify
from flask_cors import CORS

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
SYSTEM_PROMPT = os.environ.get("SYSTEM_PROMPT", "Ты дружелюбный ассистент.")
API_URL = "https://aiprime.store/api/v1/messages"

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


@app.after_request
def after_request(response):
    response.headers.add('Access-Control-Allow-Origin', '*')
    response.headers.add('Access-Control-Allow-Headers', 'Content-Type,Authorization')
    response.headers.add('Access-Control-Allow-Methods', 'GET,POST,OPTIONS')
    return response


@app.route("/", methods=["GET"])
def health():
    return jsonify({"status": "ok", "service": "QIP Mini App Backend"})


@app.route("/chat", methods=["POST", "OPTIONS"])
def chat():
    if request.method == "OPTIONS":
        return jsonify({}), 200

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
            API_URL,
        headers={
                 "Authorization": "Bearer " + ANTHROPIC_API_KEY,
                 "x-api-key": ANTHROPIC_API_KEY,
                 "anthropic-version": "2023-06-01",
                 "content-type": "application/json",
            },
            json={
                "model": "claude-sonnet-4-5",
                "max_tokens": 2048,
                "system": SYSTEM_PROMPT,
                "messages": messages,
            },
            timeout=120,
        )

        resp.raise_for_status()
        reply = resp.json()["content"][0]["text"]
        messages.append({"role": "assistant", "content": reply})

        return jsonify({"reply": reply, "conversation_id": conv_id})

    except requests.HTTPError as e:
        app.logger.error(f"API error: {e.response.text if e.response else str(e)}")
        return jsonify({"error": str(e)}), 502
    except Exception as e:
        app.logger.error(f"Error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/clear", methods=["POST", "OPTIONS"])
def clear():
    if request.method == "OPTIONS":
        return jsonify({}), 200
    data = request.get_json()
    conv_id = data.get("conversation_id", "default") if data else "default"
    if conv_id in conversations:
        conversations[conv_id]["messages"] = []
    return jsonify({"status": "cleared"})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
