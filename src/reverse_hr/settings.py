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


EXTERNAL_SERVICES = ("demo-fsp", "demo-codenrock", "demo-ats")
SIGNING_SERVICES = SERVICES + EXTERNAL_SERVICES


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="HR_", extra="ignore")
    service_name: str = "candidate"
    root_path: str = ""
    database_url: SecretStr = Field(default=SecretStr("sqlite:///./candidate.db"))
    oidc_issuer: str = "http://localhost:8080/realms/reverse-hr"
    oidc_audience: str = "reverse-hr-api"
    oidc_jwks_url: str = "http://localhost:8080/realms/reverse-hr/protocol/openid-connect/certs"
    identity_api_url: str = "http://identity:8000"
    identity_export_enabled: bool = False
    identity_export_origin: str = ""
    identity_export_realm: str = "reverse-hr"
    identity_export_client_id: str = ""
    identity_export_key_file: str = ""
    identity_export_timeout_seconds: int = Field(default=5, ge=1, le=15)
    identity_export_trusted_local: bool = False
    identity_export_attribute_names: list[str] = Field(default_factory=list, max_length=50)
    privacy_api_url: str = "http://privacy:8000"
    assessment_api_url: str = "http://assessment:8000"
    proctoring_api_url: str = "http://proctoring:8000"
    evaluation_api_url: str = "http://evaluation:8000"
    candidate_api_url: str = "http://candidate:8000"
    employer_api_url: str = "http://employer:8000"
    deployment_mode: Literal["production", "demo"] = "demo"
    achievements_api_url: str = "http://achievements:8000"
    integration_api_url: str = "http://integration:8000"
    demo_fsp_api_url: str = "http://demo-fsp:8000"
    demo_codenrock_api_url: str = "http://demo-codenrock:8000"
    demo_ats_api_url: str = "http://demo-ats:8000"
    demo_source_scenario: Literal["normal", "empty", "updated", "revoked", "unavailable"] = "normal"
    matching_achievements_enabled: bool = False
    resume_achievements_enabled: bool = False
    hiring_api_url: str = "http://hiring:8000"
    matching_api_url: str = "http://matching:8000"
    code_runner_api_url: str = "http://code-runner:8000"
    notification_api_url: str = "http://notification:8000"
    audit_api_url: str = "http://audit:8000"
    notification_delivery_enabled: bool = False
    notification_provider_url: str = ""
    notification_provider_key_file: str = ""
    notification_provider_callback_public_key_file: str = ""
    notification_challenge_key_file: str = ""
    notification_application_link: str = ""
    notification_delivery_max_attempts: int = Field(default=3, ge=1, le=10)
    notification_delivery_lease_seconds: int = Field(default=60, ge=30, le=300)
    notification_delivery_timeout_seconds: int = Field(default=5, ge=1, le=15)
    notification_delivery_retry_seconds: int = Field(default=30, ge=1, le=3600)
    audit_retention_days: int = Field(default=365, ge=1, le=3650)
    media_api_url: str = "http://media:8000"
    whiteboard_api_url: str = "http://whiteboard:8000"
    workspace_api_url: str = "http://coding-workspace:8000"
    matching_llm_enabled: bool = False
    matching_llm_model: str = Field(default="", max_length=200)
    matching_llm_config: GatewayConfiguration | None = None
    matching_llm_key_file: str = ""
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
    privacy_request_sla_days: int = Field(default=30, ge=1, le=365)
    appeal_filing_seconds: int = Field(default=2592000, ge=1, le=31536000)
    appeal_review_seconds: int = Field(default=1209600, ge=1, le=31536000)
    resume_storage_root: str = ""
    resume_pdf_socket: str = ""
    resume_antivirus_required: bool = True
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
            self.identity_api_url,
            self.privacy_api_url,
            self.assessment_api_url,
            self.workspace_api_url,
            self.evaluation_api_url,
            self.proctoring_api_url,
            self.candidate_api_url,
            self.employer_api_url,
            self.hiring_api_url,
            self.matching_api_url,
            self.audit_api_url,
            self.code_runner_api_url,
            self.notification_api_url,
            self.media_api_url,
            self.whiteboard_api_url,
            self.achievements_api_url,
            self.integration_api_url,
            self.demo_fsp_api_url,
            self.demo_codenrock_api_url,
            self.demo_ats_api_url,
        ):
            self.validate_origin(origin)
        if self.service_name not in SIGNING_SERVICES:
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
