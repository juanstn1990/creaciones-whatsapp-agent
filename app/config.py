from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # LLM (OpenAI-compatible)
    moonshot_api_key: str
    moonshot_base_url: str = "https://api.openai.com/v1"
    moonshot_model: str = "gpt-4o-mini"

    # Evolution API
    evolution_api_url: str
    evolution_api_key: str
    evolution_instance: str

    # PostgreSQL (Evolution API DB)
    database_url: str

    # Agent behavior
    webhook_secret: str = ""
    history_limit: int = 15          # messages of context per chat
    personality_sample: int = 200    # agent messages used to build personality
    personality_ttl: int = 3600      # seconds before refreshing personality
    ignore_groups: bool = True       # skip group chats

    port: int = 8000

    class Config:
        env_file = ".env"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
