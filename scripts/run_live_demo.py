"""Start the jury image with dotenv parsing, keeping secrets out of command arguments."""

import os
import subprocess
from pathlib import Path

from dotenv import dotenv_values


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    env_path = root / ".env"
    if not env_path.is_file():
        raise SystemExit("Create .env from .env.example before starting the live demo.")
    values = {key: value for key, value in dotenv_values(env_path).items() if value is not None}
    environment = {**os.environ, **values}
    # Explicit shell settings take precedence, as in the application's Settings loader.
    for key in values:
        if key in os.environ:
            environment[key] = os.environ[key]
    if not environment.get("LLM_API_KEY", "").strip():
        raise SystemExit("LLM_API_KEY is missing or empty.")
    keys = sorted(set(values) | {key for key in os.environ if key.startswith("LLM_")})
    command = ["docker", "run", "--rm", "-p", "8501:8501"]
    for key in keys:
        command.extend(["--env", key])
    command.append("parltopic-jury")
    return subprocess.call(command, cwd=root, env=environment)


if __name__ == "__main__":
    raise SystemExit(main())
