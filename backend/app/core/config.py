"""全局配置：统一从环境变量 / .env 读取，禁止在代码里硬编码密钥。"""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # 应用
    APP_NAME: str = "学业过程管理与智能决策系统"
    APP_ENV: str = "dev"
    DEBUG: bool = True
    API_PREFIX: str = "/api/v1"

    # 数据库
    DB_HOST: str = "127.0.0.1"
    DB_PORT: int = 3306
    DB_USER: str = "root"
    DB_PASSWORD: str = ""
    DB_NAME: str = "student_academic"
    DB_CHARSET: str = "utf8mb4"
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 20
    DB_POOL_RECYCLE: int = 3600
    DB_ECHO: bool = False

    # Redis
    REDIS_HOST: str = "127.0.0.1"
    REDIS_PORT: int = 6379
    REDIS_DB: int = 0
    REDIS_PASSWORD: str = ""

    # JWT
    JWT_SECRET_KEY: str = "dev-secret-key-change-me"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 120

    # 业务
    DEFAULT_MAX_CREDITS_PER_SEMESTER: int = 30
    PASS_SCORE: int = 60
    SELECT_LOCK_TIMEOUT: int = 5

    @property
    def database_url(self) -> str:
        return (
            f"mysql+pymysql://{self.DB_USER}:{self.DB_PASSWORD}"
            f"@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}?charset={self.DB_CHARSET}"
        )

    @property
    def server_database_url(self) -> str:
        """不带库名，用于 CREATE DATABASE。"""
        return (
            f"mysql+pymysql://{self.DB_USER}:{self.DB_PASSWORD}"
            f"@{self.DB_HOST}:{self.DB_PORT}/?charset={self.DB_CHARSET}"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
