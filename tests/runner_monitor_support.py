"""Finish actual signed RPC checks around instant fake execution and migrated SQLite."""

from reverse_hr.services.code_runner.runner_monitor import StopMonitor as BaseStopMonitor


def drain_monitors(monkeypatch):
    import reverse_hr.services.code_runner.runner_monitor as monitoring
    import reverse_hr.services.code_runner.submitted_runner as submitted

    class DrainedMonitor(BaseStopMonitor):
        def __init__(self, check, **kwargs):
            # This fixture tests results/ledger with an instant fake executor, not
            # the production watchdog SLA. Allow slow local RPC/SQLite scheduling;
            # dedicated stalled-monitor tests retain the original class/deadline.
            kwargs.setdefault("max_age", 10)
            super().__init__(check, **kwargs)

        def __exit__(self, *args):
            result = super().__exit__(*args)
            if self.thread:
                self.thread.join(timeout=5)
                assert not self.thread.is_alive(), "signed admission check did not finish"
            return result

    monkeypatch.setattr(monitoring, "StopMonitor", DrainedMonitor)
    # Submitted worker holds an imported alias rather than importing at call time.
    monkeypatch.setattr(submitted, "StopMonitor", DrainedMonitor)
