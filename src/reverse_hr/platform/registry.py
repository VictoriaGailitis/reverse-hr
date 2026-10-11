"""Lazy composition registry; service code is loaded only when selected."""

from importlib import import_module

DOMAIN_MODULES = {
    "hiring_communication_risk": "reverse_hr.services.hiring.domain.hiring_communication_risk",
    "assessment_appeals": "reverse_hr.services.assessment.domain.assessment_appeals",
    "company_assignments": "reverse_hr.services.assessment.domain.company_assignments",
    "notification_delivery": "reverse_hr.services.notification.domain.notification_delivery",
    "assessment": "reverse_hr.services.assessment.domain.assessment",
    "demo_ats": "reverse_hr.services.demo_ats.domain.demo_ats",
    "assessment_confirmed_grade": (
        "reverse_hr.services.assessment.domain.assessment_confirmed_grade"
    ),
    "assessment_lifecycle": "reverse_hr.services.assessment.domain.assessment_lifecycle",
    "employer_trust": "reverse_hr.services.employer.domain.employer_trust",
    "media": "reverse_hr.services.media.domain.media",
    "whiteboard": "reverse_hr.services.whiteboard.domain.whiteboard",
    "hiring_trust": "reverse_hr.services.hiring.domain.hiring_trust",
    "audit": "reverse_hr.services.audit.domain.audit",
    "assessment_sessions": "reverse_hr.services.assessment.domain.assessment_sessions",
    "proctoring": "reverse_hr.services.proctoring.domain.proctoring",
    "workspace_submitted": "reverse_hr.services.coding_workspace.domain.workspace_submitted",
    "assessment_submitted": "reverse_hr.services.assessment.domain.assessment_submitted",
    "coding_workspace": "reverse_hr.services.coding_workspace.domain.coding_workspace",
    "assessment_grades": "reverse_hr.services.assessment.domain.assessment_grades",
    "notification": "reverse_hr.services.notification.domain.notification",
    "evaluation": "reverse_hr.services.evaluation.domain.evaluation",
    "evaluation_review": "reverse_hr.services.evaluation.domain.evaluation_review",
    "code_runner": "reverse_hr.services.code_runner.domain.code_runner",
    "privacy_archives": "reverse_hr.services.privacy.domain.privacy_archives",
    "hiring_moderation": "reverse_hr.services.hiring.domain.hiring_moderation",
    "privacy_company_results": "reverse_hr.services.privacy.domain.privacy_company_results",
    "matching_governance": "reverse_hr.services.matching.domain.matching_governance",
    "assessment_evaluation": "reverse_hr.services.assessment.domain.assessment_evaluation",
    "assessment_workspace": "reverse_hr.services.assessment.domain.assessment_workspace",
    "evaluation_tests": "reverse_hr.services.evaluation.domain.evaluation_tests",
    "assessment_selection": "reverse_hr.services.assessment.domain.assessment_selection",
    "workspace_runner": "reverse_hr.services.coding_workspace.domain.workspace_runner",
    "integration": "reverse_hr.services.integration.domain.integration",
    "matching": "reverse_hr.services.matching.domain.matching",
    "hiring_ats": "reverse_hr.services.hiring.domain.hiring_ats",
    "employer_market": "reverse_hr.services.employer.domain.employer_market",
    "hiring_dialogs": "reverse_hr.services.hiring.domain.hiring_dialogs",
    "privacy_market": "reverse_hr.services.privacy.domain.privacy_market",
    "company_tasks": "reverse_hr.services.assessment.domain.company_tasks",
    "candidate_grades": "reverse_hr.services.candidate.domain.candidate_grades",
    "candidate_preferences": "reverse_hr.services.candidate.domain.candidate_preferences",
    "candidate_resume": "reverse_hr.services.candidate.domain.candidate_resume",
    "assessment_verdicts": "reverse_hr.services.assessment.domain.assessment_verdicts",
    "hiring": "reverse_hr.services.hiring.domain.hiring",
    "demo_sources": "reverse_hr.services.demo_sources.domain.demo_sources",
    "candidate_market": "reverse_hr.services.candidate.domain.candidate_market",
    "achievements": "reverse_hr.services.achievements.domain.achievements",
    "candidate": "reverse_hr.services.candidate.domain.candidate",
    "assessment_tests": "reverse_hr.services.assessment.domain.assessment_tests",
    "workspace_evaluation": "reverse_hr.services.coding_workspace.domain.workspace_evaluation",
    "employer": "reverse_hr.services.employer.domain.employer",
    "company_schedules": "reverse_hr.services.assessment.domain.company_schedules",
    "evaluation_scores": "reverse_hr.services.evaluation.domain.evaluation_scores",
    "assessment_suite_admission": (
        "reverse_hr.services.assessment.domain.assessment_suite_admission"
    ),
    "privacy": "reverse_hr.services.privacy.domain.privacy",
    "hiring_vacancies": "reverse_hr.services.hiring.domain.hiring_vacancies",
    "privacy_requests": "reverse_hr.services.privacy.domain.privacy_requests",
    "assessment_plan_tests": "reverse_hr.services.assessment.domain.assessment_plan_tests",
    "workspace_snapshot": "reverse_hr.services.coding_workspace.domain.workspace_snapshot",
}


def domain_module(name):
    return import_module(DOMAIN_MODULES[name])


def service_app(name):
    from reverse_hr.platform.settings import SIGNING_SERVICES

    if name not in SIGNING_SERVICES:
        raise ValueError("Unknown service")
    return import_module("reverse_hr.services." + name.replace("-", "_") + ".app")


CONSUMER_TYPES = {
    "audit": "reverse_hr.services.audit.consumer:AuditConsumer",
    "achievements": "reverse_hr.services.achievements.consumer:AchievementsConsumer",
    "integration": "reverse_hr.services.integration.consumer:IntegrationConsumer",
    "privacy": "reverse_hr.services.privacy.consumer:PrivacyConsumer",
    "proctoring": "reverse_hr.services.proctoring.consumer:ProctoringConsumer",
    "candidate": "reverse_hr.services.candidate.consumer:CandidateConsumer",
    "employer": "reverse_hr.services.employer.consumer:EmployerConsumer",
    "assessment": "reverse_hr.services.assessment.consumer:AssessmentConsumer",
    "coding-workspace": "reverse_hr.services.coding_workspace.consumer:WorkspaceConsumer",
    "code-runner": "reverse_hr.services.code_runner.consumer:RunnerConsumer",
    "evaluation": "reverse_hr.services.evaluation.consumer:EvaluationConsumer",
    "matching": "reverse_hr.services.matching.consumer:MatchingConsumer",
    "hiring": "reverse_hr.services.hiring.consumer:HiringConsumer",
    "notification": "reverse_hr.services.notification.consumer:NotificationConsumer",
    "media": "reverse_hr.services.media.consumer:MediaConsumer",
    "whiteboard": "reverse_hr.services.whiteboard.consumer:WhiteboardConsumer",
}


def consumer_type(name):
    module, symbol = CONSUMER_TYPES[name].split(":")
    return getattr(import_module(module), symbol)
