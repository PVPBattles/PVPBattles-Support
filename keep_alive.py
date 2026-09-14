import os
import threading

from flask import Flask


app = Flask(__name__)


@app.route("/")
def home():
    return "Welcome Bot is online!"


def start_keep_alive():
    port = int(os.environ.get("PORT", 10000))

    thread = threading.Thread(
        target=lambda: app.run(
            host="0.0.0.0",
            port=port
        ),
        daemon=True
    )

    thread.start()
