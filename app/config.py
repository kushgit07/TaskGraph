"""Central configuration, loaded from environment variables."""
import os

from dotenv import load_dotenv

load_dotenv()


class Settings:
    database_url: str = os.getenv(
        "DATABASE_URL", "sqlite:///./taskgraph.db"
    )
    groq_api_key: str = os.getenv("GROQ_API_KEY", "")
    groq_model: str = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")
    storage_dir: str = os.getenv("STORAGE_DIR", "./artifacts")
    task_timeout_seconds: int = int(os.getenv("TASK_TIMEOUT_SECONDS", "30"))
    task_memory_limit_mb: int = int(os.getenv("TASK_MEMORY_LIMIT_MB", "1024"))
    max_task_attempts: int = int(os.getenv("MAX_TASK_ATTEMPTS", "3"))
    claim_heartbeat_timeout_seconds: int = int(
        os.getenv("CLAIM_HEARTBEAT_TIMEOUT_SECONDS", "120")
    )
    orchestrator_poll_interval_seconds: float = float(
        os.getenv("ORCHESTRATOR_POLL_INTERVAL_SECONDS", "1.0")
    )
    worker_poll_interval_seconds: float = float(
        os.getenv("WORKER_POLL_INTERVAL_SECONDS", "1.0")
    )

    @property
    def use_mock_llm(self) -> bool:
        """Fall back to a deterministic mock LLM when no API key is set,
        so the system is runnable and testable with zero external cost."""
        return not self.groq_api_key


settings = Settings()
