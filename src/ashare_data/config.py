from functools import cached_property
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ENV_FILE = PROJECT_ROOT / ".env"


class Settings(BaseSettings):
    """Runtime settings loaded from the project root .env file."""

    model_config = SettingsConfigDict(env_file=ENV_FILE, env_file_encoding="utf-8", extra="ignore")

    tushare_token: str = Field(default="", alias="TUSHARE_TOKEN")
    project_root: Path = Field(default=PROJECT_ROOT)
    data_dir: Path = Path("data")
    raw_dir: Path = Path("data/raw")
    warehouse_dir: Path = Path("data/warehouse")
    report_dir: Path = Path("reports/dq")
    duckdb_path: Path = Path("data/warehouse/ashare.duckdb")

    @cached_property
    def sql_dir(self) -> Path:
        return Path(__file__).parent / "sql"

    def resolve_paths(self) -> "Settings":
        for field_name in ["data_dir", "raw_dir", "warehouse_dir", "report_dir", "duckdb_path"]:
            value = getattr(self, field_name)
            if not value.is_absolute():
                setattr(self, field_name, self.project_root / value)
        return self

    def require_token(self) -> str:
        token = self.tushare_token.strip()
        if not token:
            raise RuntimeError(
                "Missing TUSHARE_TOKEN. Please create .env in the project root with "
                "TUSHARE_TOKEN=your_tushare_pro_token."
            )
        return token
