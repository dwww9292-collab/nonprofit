from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=(".env", "../.env"), extra="ignore")

    database_url: str = "postgresql+psycopg://npo:npo@localhost:5432/npo_sales"
    jwt_secret: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 720

    admin_email: str = "admin@ionesoftbank.co.kr"
    admin_password: str = "admin1234!"

    cors_origins: str = "http://localhost:5173"
    upload_dir: str = "./uploads"

    # 로그인 실패 잠금 (docs/05-screens.md 1. 로그인)
    login_max_attempts: int = 5
    login_lock_minutes: int = 5

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
