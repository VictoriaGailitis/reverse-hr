from reverse_hr.services.coding_workspace.domain.coding_workspace import (
    process_deletion_request as process_workspace_deletion,
)
from reverse_hr.shared.event_transport import InvalidEvent, SignedConsumer


class WorkspaceConsumer(SignedConsumer):
    service = "coding-workspace"

    def handler(self, event):
        if event.producer == "code-runner" and event.event_type in {
            "code-runner.run_accepted.v1",
            "code-runner.run_diagnosed.v1",
            "code-runner.run_started.v1",
            "code-runner.run_finished.v1",
            "code-runner.run_cancelled.v1",
        }:
            from reverse_hr.services.coding_workspace.domain.coding_workspace import (
                process_runner_event,
            )

            return process_runner_event
        if event.producer == "privacy" and event.event_type == "privacy.deletion_requested.v1":
            return process_workspace_deletion
        raise InvalidEvent()
