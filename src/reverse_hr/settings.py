from typing import Literal
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from reverse_hr.llm_configuration import GatewayConfiguration
from reverse_hr.runtime_policy import TrustedRuntime

SERVICES = (
    "identity",
    "privacy",
    "candidate",
    "employer",
    "assessment",
    "coding-workspace",
    "code-runner",
    "whiteboard",
    "media",
    "proctoring",
    "evaluation",
    "matching",
    "hiring",
    "achievements",
    "integration",
    "notification",
    "audit",
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="HR_", extra="ignore")
    service_name: str = "candidate"
    root_path: str = ""
    database_url: SecretStr = Field(default=SecretStr("sqlite:///./candidate.db"))
    oidc_issuer: str = "http://localhost:8080/realms/reverse-hr"
    oidc_audience: str = "reverse-hr-api"
    oidc_jwks_url: str = "http://localhost:8080/realms/reverse-hr/protocol/openid-connect/certs"
    privacy_api_url: str = "http://privacy:8000"
    assessment_api_url: str = "http://assessment:8000"
    proctoring_api_url: str = "http://proctoring:8000"
    evaluation_api_url: str = "http://evaluation:8000"
    candidate_api_url: str = "http://candidate:8000"
    employer_api_url: str = "http://employer:8000"
    hiring_api_url: str = "http://hiring:8000"
    media_api_url: str = "http://media:8000"
    whiteboard_api_url: str = "http://whiteboard:8000"
    workspace_api_url: str = "http://coding-workspace:8000"
    evaluation_llm_enabled: bool = False
    evaluation_llm_model: str = Field(default="", max_length=200)
    evaluation_llm_config: GatewayConfiguration | None = None
    evaluation_llm_key_file: str = ""
    evaluation_llm_timeout_seconds: int = Field(default=30, ge=1, le=30)
    media_transcription_enabled: bool = False
    media_transcription_origin: str = ""
    media_transcription_model: str = Field(default="", max_length=200)
    media_transcription_key_file: str = ""
    media_storage_root: str = ""
    media_storage_backend: Literal["file", "s3"] = "file"
    media_s3_bucket: str = ""
    media_s3_prefix: str = "media/"
    s3_region: str = "us-east-1"
    s3_endpoint: str = ""
    s3_credentials_file: str = ""
    s3_allow_insecure_local: bool = False
    s3_kms_key_id: str = ""
    backup_s3_bucket: str = ""
    backup_s3_prefix: str = "backups/"
    backup_purge_required: bool = False
    media_antivirus_required: bool = True
    media_clamd_host: str = "clamav"
    media_clamd_port: int = Field(default=3310, ge=1, le=65535)
    media_antivirus_timeout_seconds: int = Field(default=15, ge=1, le=30)
    media_antivirus_max_signature_age_hours: int = Field(default=48, ge=1, le=168)
    media_decoder_socket: str = ""
    media_decoder_required: bool = True
    decoder_container_required: bool = True
    media_ffprobe_binary: str = "ffprobe"
    media_ffmpeg_binary: str = "ffmpeg"
    media_validation_timeout_seconds: int = Field(default=20, ge=1, le=30)
    runner_execution_enabled: bool = False
    assessment_trusted_runtimes: list[TrustedRuntime] = Field(default_factory=list, max_length=32)
    runner_verification_file: str = ""
    runner_node_id: UUID | None = None
    runner_backend: Literal["disabled", "nsjail"] = "disabled"
    runner_nsjail_binary: str = ""
    runner_nsjail_sha256: str = ""
    runner_rootfs: str = ""
    runner_rootfs_manifest: str = ""
    runner_rootfs_manifest_sha256: str = ""
    runner_cgroup_parent: str = ""
    runner_scratch: str = "/tmp"
    amqp_url: SecretStr = SecretStr("amqp://localhost:5672/")
    event_private_key_file: str = ""
    event_public_keys_file: str = ".secrets/public-keys.json"
    event_max_attempts: int = Field(default=5, ge=1, le=20)
    event_retry_delay_seconds: int = Field(default=5, ge=1, le=300)

    def model_post_init(self, context: object) -> None:
        entries = self.assessment_trusted_runtimes
        if len({(item.node_id, item.fingerprint) for item in entries}) != len(entries) or len(
            {item.policy_id for item in entries}
        ) != len(entries):
            raise ValueError("Runtime policies must have unique IDs and node/fingerprint pairs")
        for origin in (
            self.privacy_api_url,
            self.assessment_api_url,
            self.workspace_api_url,
            self.evaluation_api_url,
            self.proctoring_api_url,
            self.candidate_api_url,
            self.employer_api_url,
            self.hiring_api_url,
            self.media_api_url,
            self.whiteboard_api_url,
        ):
            self.validate_origin(origin)
        if self.service_name not in SERVICES:
            raise ValueError("Unknown service name")
        if not self.event_private_key_file:
            self.event_private_key_file = f".secrets/{self.service_name}.key"

    @staticmethod
    def validate_origin(origin):
        parsed = urlsplit(origin)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or parsed.path not in {"", "/"}
        ):
            raise ValueError("Service URL must be a fixed HTTP(S) origin")
