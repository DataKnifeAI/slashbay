from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    host: str = Field(default="0.0.0.0", alias="SLASHBAY_HOST")
    port: int = Field(default=8080, alias="SLASHBAY_PORT")
    dry_run: bool = Field(default=True, alias="SLASHBAY_DRY_RUN")
    state_dsn: str = Field(default="memory://", alias="SLASHBAY_STATE_DSN")

    repo_allowlist: str = Field(default="DataKnifeAI/*", alias="SLASHBAY_REPO_ALLOWLIST")
    trigger_events: str = Field(default="opened,reopened", alias="SLASHBAY_TRIGGER_EVENTS")
    trigger_label: str = Field(default="", alias="SLASHBAY_TRIGGER_LABEL")
    max_concurrent: int = Field(default=3, alias="SLASHBAY_MAX_CONCURRENT")

    openai_api_key: str = Field(default="", alias="OPENAI_API_KEY")
    triage_model: str = Field(default="gpt-5-nano", alias="SLASHBAY_TRIAGE_MODEL")
    triage_escalate_model: str = Field(
        default="gpt-5.6-luna", alias="SLASHBAY_TRIAGE_ESCALATE_MODEL"
    )
    triage_escalate_below: float = Field(default=0.7, alias="SLASHBAY_TRIAGE_ESCALATE_BELOW")

    cursor_api_key: str = Field(default="", alias="CURSOR_API_KEY")
    workspace_git_url: str = Field(default="", alias="SLASHBAY_WORKSPACE_GIT_URL")

    coder_access_url: str = Field(default="", alias="CODER_ACCESS_URL")
    coder_token: str = Field(default="", alias="CODER_TOKEN")
    coder_template: str = Field(default="dkai-agent", alias="CODER_TEMPLATE")
    coder_organization: str = Field(default="", alias="CODER_ORGANIZATION")
    coder_workspace_owner: str = Field(default="me", alias="CODER_WORKSPACE_OWNER")

    github_webhook_secret: str = Field(default="", alias="GITHUB_WEBHOOK_SECRET")
    github_token: str = Field(default="", alias="GITHUB_TOKEN")
    github_api_url: str = Field(default="https://api.github.com", alias="GITHUB_API_URL")

    gitlab_webhook_token: str = Field(default="", alias="GITLAB_WEBHOOK_TOKEN")
    gitlab_token: str = Field(default="", alias="GITLAB_TOKEN")
    gitlab_api_url: str = Field(default="https://gitlab.com/api/v4", alias="GITLAB_API_URL")

    def allowlist_patterns(self) -> list[str]:
        return [p.strip() for p in self.repo_allowlist.split(",") if p.strip()]

    def trigger_event_set(self) -> set[str]:
        return {e.strip().lower() for e in self.trigger_events.split(",") if e.strip()}


@lru_cache
def get_settings() -> Settings:
    return Settings()


def reset_settings() -> None:
    get_settings.cache_clear()


Platform = Literal["github", "gitlab"]
