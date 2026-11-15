from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_DIR = BASE_DIR / "config"
CONFIG_DIR.mkdir(exist_ok=True)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "DS Agent Studio"
    debug: bool = False

    host: str = "127.0.0.1"
    port: int = 8787

    cookies_path: Path = CONFIG_DIR / "cookies.json"

    cloudflare_server_port: int = 8000
    cloudflare_server_script: Path = BASE_DIR / "app" / "services" / "auth" / "cloudflare_server.py"

    agent_max_iterations: int = 25
    agent_max_runtime_seconds: int = 600
    agent_max_tokens: int = 200_000

    default_workspace: Path = BASE_DIR / "workspace"


settings = Settings()
settings.default_workspace.mkdir(exist_ok=True)
