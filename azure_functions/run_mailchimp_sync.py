import json
import logging
import os
from pathlib import Path

def load_local_settings() -> None:
    settings_path = Path("local.settings.json")
    settings = json.loads(settings_path.read_text(encoding="utf-8"))

    for key, value in settings.get("Values", {}).items():
        if isinstance(value, str):
            os.environ.setdefault(key, value)

load_local_settings()

from common.mailchimp_sync import execute

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s"
)

if __name__ == "__main__":
    added_count, updated_count = execute()
    print(f"Completed. Added: {added_count}, Updated: {updated_count}")