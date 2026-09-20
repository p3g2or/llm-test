import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal


@dataclass(frozen=True)
class Settings:
    storage_backend: Literal["memory", "azure"] = "memory"
    board_title: str = "Field Notes"
    azure_storage_account_url: str = ""
    azure_storage_container: str = "notes"
    static_dir: Path = Path(__file__).parent / "static"

    def __post_init__(self) -> None:
        if self.storage_backend not in ("memory", "azure"):
            raise ValueError("STORAGE_BACKEND must be memory or azure")
        if not self.board_title.strip() or len(self.board_title) > 80:
            raise ValueError("BOARD_TITLE must contain 1 to 80 characters")
        if self.storage_backend == "azure":
            if not re.fullmatch(
                r"https://[a-z0-9]{3,24}\.blob\.core\.windows\.net/?",
                self.azure_storage_account_url,
            ):
                raise ValueError("AZURE_STORAGE_ACCOUNT_URL must be an Azure Blob HTTPS URL")
            if not re.fullmatch(
                r"[a-z0-9](?:[a-z0-9]|-(?!-)){1,61}[a-z0-9]", self.azure_storage_container
            ):
                raise ValueError("AZURE_STORAGE_CONTAINER must be a valid container name")

    @classmethod
    def from_env(cls) -> "Settings":
        backend = os.getenv("STORAGE_BACKEND", "memory")
        if backend not in ("memory", "azure"):
            raise ValueError("STORAGE_BACKEND must be memory or azure")
        return cls(
            storage_backend="azure" if backend == "azure" else "memory",
            board_title=os.getenv("BOARD_TITLE", "Field Notes").strip(),
            azure_storage_account_url=os.getenv("AZURE_STORAGE_ACCOUNT_URL", ""),
            azure_storage_container=os.getenv("AZURE_STORAGE_CONTAINER", "notes"),
            static_dir=Path(os.getenv("STATIC_DIR", str(cls.static_dir))),
        )
