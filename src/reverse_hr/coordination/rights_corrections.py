"""Owner-side CAS correction of declarations; verified evidence is never editable."""

from fastapi import HTTPException


def validate(target, domain, changes, profile_version, target_id=None):
    from reverse_hr.contracts.core import ProfileUpdate
    from reverse_hr.contracts.market_contracts import ContactsCommand
    from reverse_hr.contracts.matching_conditions import CandidatePreferenceCommand
    from reverse_hr.contracts.resume_contracts import ResumeFields

    contracts = {
        "profile": ProfileUpdate,
        "contacts": ContactsCommand,
        "resume": ResumeFields,
        "preferences": CandidatePreferenceCommand,
    }
    if target == "declared_achievement" and domain == "achievements":
        from reverse_hr.services.achievements.domain.achievements import AchievementFields

        AchievementFields.model_validate(changes)
        if target_id is None:
            raise ValueError("Achievement identifier required")
        return
    if target == "notification_preferences" and domain == "notification":
        from reverse_hr.services.notification.domain.notification import PreferenceCommand

        PreferenceCommand.model_validate(changes)
        return
    if domain != "candidate" or target not in contracts:
        raise ValueError("Unsupported owner correction target")
    contracts[target].model_validate(changes)
    if target in {"resume", "preferences"} and profile_version is None:
        raise ValueError("Correction requires the current candidate profile version")


def apply(session, request, subject, permission):
    from reverse_hr.contracts.market_contracts import ContactsCommand
    from reverse_hr.contracts.resume_contracts import ResumeFields
    from reverse_hr.services.candidate.domain.candidate import CandidateProfile
    from reverse_hr.services.candidate.domain.candidate_market import (
        Contacts,
        Publication,
        emit_profile,
    )
    from reverse_hr.services.candidate.domain.candidate_resume import Resume

    target = permission.get("target", "profile")
    if target == "declared_achievement":
        from reverse_hr.services.achievements.domain.achievements import (
            AchievementFields,
            AchievementRow,
            SourceRow,
            history,
        )

        row = session.get(AchievementRow, permission["target_id"])
        if row is None or row.candidate_id != str(subject):
            raise HTTPException(404)
        source = session.get(SourceRow, row.source_id)
        if (
            not source
            or source.key != "self"
            or row.status != "declared"
            or row.version != permission["source_version"]
        ):
            raise HTTPException(409, "Only current self-declared achievements can be corrected")
        fields = AchievementFields.model_validate(permission["changes"])
        row.data = row.data | fields.model_dump(mode="json")
        row.version += 1
        history(session, request, row, subject, "corrected", "Approved subject correction")
        return dict(candidate_id=str(subject), target=target, version=row.version)
    if target == "notification_preferences":
        from reverse_hr.services.notification.domain.notification import (
            Preference,
            PreferenceCommand,
        )

        row = session.get(Preference, str(subject))
        if row is None or row.version != permission["source_version"]:
            raise HTTPException(409, "Notification preferences changed")
        fields = PreferenceCommand.model_validate(permission["changes"])
        row.in_app = fields.in_app
        if fields.marketing_in_app is not None:
            row.marketing_in_app = fields.marketing_in_app
        row.version += 1
        return dict(candidate_id=str(subject), target=target, version=row.version)
    expected = permission["source_version"]
    profile = session.get(CandidateProfile, str(subject))
    if profile is None:
        raise HTTPException(404)
    if (
        permission.get("source_profile_version") is not None
        and profile.version != permission["source_profile_version"]
    ):
        raise HTTPException(409, "Source profile changed")
    if target == "preferences":
        from reverse_hr.services.candidate.domain.candidate_preferences import (
            apply_preferences_correction,
        )

        result = apply_preferences_correction(
            session,
            subject,
            permission["changes"],
            expected,
            request.state.trace_id,
            permission.get("source_profile_version"),
        )
        return dict(
            candidate_id=str(subject),
            target=target,
            version=result["version"],
            profile_version=profile.version,
        )
    if target == "contacts":
        row = session.get(Contacts, str(subject))
        if row is None or row.version != expected:
            raise HTTPException(409, "Source contacts changed")
        fields = ContactsCommand.model_validate(permission["changes"])
        row.email, row.phone, row.version = fields.email, fields.phone, row.version + 1
        # Keep a confirmed resume declaration consistent with the corrected contacts.
        resume = session.get(Resume, str(subject))
        if resume and resume.fields.get("contacts") is not None:
            resume.fields = resume.fields | {"contacts": fields.model_dump(mode="json")}
            resume.version += 1
        return dict(candidate_id=str(subject), target=target, version=row.version)
    if target == "resume":
        row = session.get(Resume, str(subject))
        if row is None or row.version != expected:
            raise HTTPException(409, "Source resume changed")
        fields = ResumeFields.model_validate(permission["changes"])
        # Contact edits are a separate CAS target, preventing a stale resume from
        # overwriting freshly changed contact information.
        current = row.fields.get("contacts")
        if fields.model_dump(mode="json")["contacts"] != current:
            raise HTTPException(409, "Correct contacts in a separately versioned request")
        row.fields, row.version = fields.model_dump(mode="json"), row.version + 1
        profile.display_name, profile.specialization, profile.declared_grade = (
            fields.display_name,
            fields.specialization,
            fields.declared_grade.value,
        )
        publication = session.get(Publication, str(subject))
        if publication:
            publication.declared_skills = fields.declared_skills
        if "additional_specializations" in permission["changes"]:
            profile.additional_specializations = [
                item.model_dump(mode="json") for item in fields.additional_specializations
            ]
        profile.additional_specializations = [
            item
            for item in (profile.additional_specializations or [])
            if item["specialization"].casefold() != fields.specialization.strip().casefold()
        ]
        profile.version += 1
        emit_profile(session, profile, request.state.trace_id)
        return dict(
            candidate_id=str(subject),
            target=target,
            version=row.version,
            profile_version=profile.version,
        )
    raise HTTPException(409, "Unsupported correction target")
