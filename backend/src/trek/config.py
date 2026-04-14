from pydantic_settings import BaseSettings
from pydantic import SecretStr


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://trek:trek_dev@db:5432/trek"
    password_hash: str = ""
    session_secret: SecretStr = SecretStr("change-me-in-production")
    session_max_age: int = 86400
    cors_origins: list[str] = ["http://localhost:5173"]

    model_config = {"env_prefix": "TREK_", "env_file": ".env"}


settings = Settings()
