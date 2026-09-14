import json
import os
from threading import Lock


DATA_FILE = os.path.join(
    os.path.dirname(__file__),
    "config.json"
)

_lock = Lock()


def _load() -> dict:
    if not os.path.exists(DATA_FILE):
        return {}

    with open(
        DATA_FILE,
        "r",
        encoding="utf-8"
    ) as f:
        try:
            data = json.load(f)

            if not isinstance(data, dict):
                return {}

            return data

        except json.JSONDecodeError:
            return {}


def _save(data: dict) -> None:
    temp_file = DATA_FILE + ".tmp"

    with open(
        temp_file,
        "w",
        encoding="utf-8"
    ) as f:
        json.dump(
            data,
            f,
            ensure_ascii=False,
            indent=2
        )

    os.replace(
        temp_file,
        DATA_FILE
    )


def get_guild_config(guild_id: int) -> dict:
    guild_id = str(guild_id)

    with _lock:
        data = _load()

        config = data.get(guild_id, {})

        if not isinstance(config, dict):
            return {}

        return config.copy()


def set_guild_value(
    guild_id: int,
    key: str,
    value
) -> None:
    guild_id = str(guild_id)

    with _lock:
        data = _load()

        if guild_id not in data:
            data[guild_id] = {}

        if value is None:
            data[guild_id].pop(key, None)
        else:
            data[guild_id][key] = value

        _save(data)
