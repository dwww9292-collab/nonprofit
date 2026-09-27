"""애플리케이션 설정.

비밀값(JWT_SECRET, ADMIN_PASSWORD, DATABASE_URL)에는 **기본값을 두지 않는다.**
기본값이 있으면 환경변수를 빠뜨린 채 배포됐을 때 저장소에 공개된 값으로 서비스가 떠버린다.
값이 없으면 기동 단계에서 명확한 메시지와 함께 실패하는 편이 안전하다.
"""

from functools import lru_cache

from pydantic import ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict

REQUIRED_HINT = """
필수 환경변수가 설정되지 않았습니다. 저장소 루트의 .env.example을 .env로 복사한 뒤 값을 채우세요.

  DATABASE_URL   예: postgresql+psycopg://사용자:비밀번호@호스트:5432/npo_sales
  JWT_SECRET     아래 명령으로 생성한 임의 문자열
                 python -c "import secrets; print(secrets.token_urlsafe(48))"
  ADMIN_PASSWORD 초기 관리자 계정 비밀번호 (12자 이상 권장)

docker compose를 쓰는 경우 .env 파일만 만들어 두면 compose가 자동으로 읽습니다.
"""


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=(".env", "../.env"), extra="ignore")

    # --- 비밀값: 기본값 없음 (미설정 시 기동 실패) ---
    database_url: str
    jwt_secret: str
    admin_password: str

    # --- 비밀이 아닌 설정 ---
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 720
    admin_email: str = "admin@example.com"
    cors_origins: str = "http://localhost:5173"

    # 로그인 실패 잠금 (docs/05-screens.md 1. 로그인)
    login_max_attempts: int = 5
    login_lock_minutes: int = 5

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    try:
        return Settings()
    except ValidationError as exc:
        missing = [str(e["loc"][0]).upper() for e in exc.errors() if e["type"] == "missing"]
        if missing:
            raise RuntimeError(f"{REQUIRED_HINT}\n누락된 값: {', '.join(missing)}") from exc
        raise


settings = get_settings()
