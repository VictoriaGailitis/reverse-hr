export interface paths {
    "/internal/v1/subject-rights/{operation}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Exchange */
        post: operations["exchange_internal_v1_subject_rights__operation__post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/internal/v1/market/purpose-permission": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Purpose Permission */
        post: operations["purpose_permission_internal_v1_market_purpose_permission_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/internal/v1/market/contact-permission": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Contact Permission */
        post: operations["contact_permission_internal_v1_market_contact_permission_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/company-result-grants": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Create Grant */
        post: operations["create_grant_v1_company_result_grants_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/company-result-grants/{grant_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Grant */
        get: operations["get_grant_v1_company_result_grants__grant_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/company-result-grants/{grant_id}/revoke": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Revoke Grant */
        post: operations["revoke_grant_v1_company_result_grants__grant_id__revoke_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/internal/v1/market/company-result-permission": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Permission */
        post: operations["permission_internal_v1_market_company_result_permission_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/data-subject-requests": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Own Requests */
        get: operations["own_requests_v1_data_subject_requests_get"];
        put?: never;
        /** Submit */
        post: operations["submit_v1_data_subject_requests_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/data-subject-requests/queue": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Queue */
        get: operations["queue_v1_data_subject_requests_queue_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/data-subject-requests/{request_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Read */
        get: operations["read_v1_data_subject_requests__request_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/data-subject-requests/{request_id}/claim": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Claim */
        post: operations["claim_v1_data_subject_requests__request_id__claim_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/data-subject-requests/{request_id}/decision": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Decide */
        post: operations["decide_v1_data_subject_requests__request_id__decision_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/data-subject-requests/{request_id}/withdraw": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Withdraw */
        post: operations["withdraw_v1_data_subject_requests__request_id__withdraw_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/data-subject-requests/{request_id}/history": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** History */
        get: operations["history_v1_data_subject_requests__request_id__history_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/data-subject-requests/{request_id}/export": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Export */
        get: operations["export_v1_data_subject_requests__request_id__export_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/data-subject-requests/{request_id}/execute": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Apply Correction */
        post: operations["apply_correction_v1_data_subject_requests__request_id__execute_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/data-subject-requests/{request_id}/archives": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Create */
        post: operations["create_v1_data_subject_requests__request_id__archives_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/data-subject-requests/{request_id}/archives/{archive_id}/advance": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Advance */
        post: operations["advance_v1_data_subject_requests__request_id__archives__archive_id__advance_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/data-subject-requests/{request_id}/archives/{archive_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Manifest */
        get: operations["manifest_v1_data_subject_requests__request_id__archives__archive_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/data-subject-requests/{request_id}/archives/{archive_id}/pages": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Download */
        get: operations["download_v1_data_subject_requests__request_id__archives__archive_id__pages_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/data-subject-requests/{request_id}/archives/{archive_id}/abandon": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Abandon */
        post: operations["abandon_v1_data_subject_requests__request_id__archives__archive_id__abandon_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/consents/policies": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Policies */
        get: operations["policies_v1_consents_policies_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/consents": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Consents */
        get: operations["list_consents_v1_consents_get"];
        put?: never;
        /** Grant Consent */
        post: operations["grant_consent_v1_consents_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/consents/{consent_id}/revoke": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Revoke Consent */
        post: operations["revoke_consent_v1_consents__consent_id__revoke_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/contact-grants": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Grants */
        get: operations["list_grants_v1_contact_grants_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/contact-grants/{grant_id}/revoke": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Revoke Grant */
        post: operations["revoke_grant_v1_contact_grants__grant_id__revoke_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/deletion-requests": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Request Deletion */
        post: operations["request_deletion_v1_deletion_requests_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/deletion-requests/me": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Deletion */
        get: operations["get_deletion_v1_deletion_requests_me_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/internal/v1/processing-status": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Processing Status */
        post: operations["processing_status_internal_v1_processing_status_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/internal/v1/assessment-permission": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Assessment Permission */
        post: operations["assessment_permission_internal_v1_assessment_permission_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/internal/v1/recording-permission": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Recording Permission */
        post: operations["recording_permission_internal_v1_recording_permission_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/health/live": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Live */
        get: operations["live_health_live_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/health/ready": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Ready */
        get: operations["ready_health_ready_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
}
export type webhooks = Record<string, never>;
export interface components {
    schemas: {
        /** AssessmentPermissionRequest */
        AssessmentPermissionRequest: {
            /**
             * Candidate Id
             * Format: uuid
             */
            candidate_id: string;
            /**
             * Nonce
             * Format: uuid
             */
            nonce: string;
            /**
             * Requester
             * @enum {string}
             */
            requester: "assessment" | "evaluation";
            /**
             * Issued At
             * Format: date-time
             */
            issued_at: string;
            /**
             * Consent Id
             * Format: uuid
             */
            consent_id: string;
        };
        /** AssessmentPermissionStatus */
        AssessmentPermissionStatus: {
            /**
             * Candidate Id
             * Format: uuid
             */
            candidate_id: string;
            /**
             * Nonce
             * Format: uuid
             */
            nonce: string;
            /**
             * Requester
             * @enum {string}
             */
            requester: "assessment" | "evaluation";
            /**
             * Issued At
             * Format: date-time
             */
            issued_at: string;
            /**
             * Consent Id
             * Format: uuid
             */
            consent_id: string;
            /** Allowed */
            allowed: boolean;
        };
        /** Consent */
        Consent: {
            /**
             * Purpose
             * @enum {string}
             */
            purpose: "assessment" | "recording" | "profile_publication" | "ats_export" | "achievement_import" | "achievement_publication" | "contact_disclosure" | "company_result_disclosure" | "company_task_subscription" | "task_recommendations" | "resume_publication" | "external_service_notifications" | "external_marketing_notifications";
            /** Document Version */
            document_version: string;
            /**
             * Consent Id
             * Format: uuid
             */
            consent_id: string;
            /**
             * Status
             * @enum {string}
             */
            status: "active" | "revoked";
            /** Version */
            version: number;
        };
        /** ConsentCommand */
        ConsentCommand: {
            /**
             * Purpose
             * @enum {string}
             */
            purpose: "assessment" | "recording" | "profile_publication" | "ats_export" | "achievement_import" | "achievement_publication" | "contact_disclosure" | "company_result_disclosure" | "company_task_subscription" | "task_recommendations" | "resume_publication" | "external_service_notifications" | "external_marketing_notifications";
            /** Document Version */
            document_version: string;
        };
        /** ContactGrantView */
        ContactGrantView: {
            /**
             * Grant Id
             * Format: uuid
             */
            grant_id: string;
            /**
             * Invitation Id
             * Format: uuid
             */
            invitation_id: string;
            /**
             * Candidate Id
             * Format: uuid
             */
            candidate_id: string;
            /**
             * Organization Id
             * Format: uuid
             */
            organization_id: string;
            /**
             * Consent Id
             * Format: uuid
             */
            consent_id: string;
            /**
             * Status
             * @enum {string}
             */
            status: "active" | "revoked" | "expired";
            /** Version */
            version: number;
            /**
             * Expires At
             * Format: date-time
             */
            expires_at: string;
        };
        /** Decision */
        Decision: {
            /**
             * Outcome
             * @enum {string}
             */
            outcome: "approved" | "rejected";
            /** Reason */
            reason: string;
        };
        /** DeletionView */
        DeletionView: {
            /**
             * Request Id
             * Format: uuid
             */
            request_id: string;
            /**
             * Candidate Id
             * Format: uuid
             */
            candidate_id: string;
            /**
             * Status
             * @enum {string}
             */
            status: "in_progress" | "completed";
            /**
             * Requested At
             * Format: date-time
             */
            requested_at: string;
            /** Completed At */
            completed_at?: string | null;
            /** Services */
            services: {
                [key: string]: "pending" | "restricted" | "deleted";
            };
            /**
             * Backup Attempts
             * @default 0
             */
            backup_attempts: number;
            /** Backup Error */
            backup_error?: "archive_unavailable" | null;
            /** Backup Retry At */
            backup_retry_at?: string | null;
        };
        /** ErrorResponse */
        ErrorResponse: {
            /** Code */
            code: string;
            /** Message */
            message: string;
            /** Fields */
            fields?: string[];
            /**
             * Trace Id
             * Format: uuid
             */
            trace_id: string;
        };
        /** GrantCommand */
        GrantCommand: {
            /**
             * Assignment Id
             * Format: uuid
             */
            assignment_id: string;
            /**
             * Organization Id
             * Format: uuid
             */
            organization_id: string;
            /**
             * Consent Id
             * Format: uuid
             */
            consent_id: string;
            /**
             * Expires In Days
             * @default 30
             */
            expires_in_days: number;
        };
        /** GrantView */
        GrantView: {
            /**
             * Grant Id
             * Format: uuid
             */
            grant_id: string;
            /**
             * Assignment Id
             * Format: uuid
             */
            assignment_id: string;
            /**
             * Organization Id
             * Format: uuid
             */
            organization_id: string;
            /**
             * Consent Id
             * Format: uuid
             */
            consent_id: string;
            /**
             * Status
             * @enum {string}
             */
            status: "active" | "revoked" | "expired";
            /** Version */
            version: number;
            /**
             * Expires At
             * Format: date-time
             */
            expires_at: string;
        };
        /** HTTPValidationError */
        HTTPValidationError: {
            /** Detail */
            detail?: components["schemas"]["ValidationError"][];
        };
        /** HealthResponse */
        HealthResponse: {
            /** Status */
            status: string;
            /** Service */
            service: string;
        };
        /** MarketReceipt */
        MarketReceipt: {
            /**
             * Candidate Id
             * Format: uuid
             */
            candidate_id: string;
            /**
             * Nonce
             * Format: uuid
             */
            nonce: string;
            /**
             * Requester
             * @enum {string}
             */
            requester: "achievements" | "integration" | "demo-ats" | "candidate" | "matching" | "hiring" | "notification" | "assessment" | "evaluation";
            /**
             * Issued At
             * Format: date-time
             */
            issued_at: string;
            /** Specialization */
            specialization?: string | null;
            /**
             * Purpose
             * @enum {string}
             */
            purpose: "profile" | "task-catalog" | "task-notice" | "membership" | "affiliation" | "content-membership" | "need" | "purpose-permission" | "contact-permission" | "resume-permission" | "company-result-permission" | "company-notice" | "appeal-notice" | "contacts" | "notice";
            /** Catalog After */
            catalog_after?: string | null;
            /** Catalog Version Id */
            catalog_version_id?: string | null;
            /** Assignment Id */
            assignment_id?: string | null;
            /** Result Grant Id */
            result_grant_id?: string | null;
            /** Organization Id */
            organization_id?: string | null;
            /** Actor Id */
            actor_id?: string | null;
            /** Notice Id */
            notice_id?: string | null;
            /** Need Id */
            need_id?: string | null;
            /** Invitation Id */
            invitation_id?: string | null;
            /** Consent Id */
            consent_id?: string | null;
            /** Consent Purpose */
            consent_purpose?: ("achievement_import" | "achievement_publication" | "ats_export" | "profile_publication" | "contact_disclosure" | "company_task_subscription" | "task_recommendations" | "resume_publication" | "external_service_notifications" | "external_marketing_notifications") | null;
            /** Allowed */
            allowed: boolean;
            /**
             * Revision
             * @default 0
             */
            revision: number;
            /** Data */
            data?: {
                [key: string]: unknown;
            } | null;
        };
        /** MarketRequest */
        MarketRequest: {
            /**
             * Candidate Id
             * Format: uuid
             */
            candidate_id: string;
            /**
             * Nonce
             * Format: uuid
             */
            nonce: string;
            /**
             * Requester
             * @enum {string}
             */
            requester: "achievements" | "integration" | "demo-ats" | "candidate" | "matching" | "hiring" | "notification" | "assessment" | "evaluation";
            /**
             * Issued At
             * Format: date-time
             */
            issued_at: string;
            /** Specialization */
            specialization?: string | null;
            /**
             * Purpose
             * @enum {string}
             */
            purpose: "profile" | "task-catalog" | "task-notice" | "membership" | "affiliation" | "content-membership" | "need" | "purpose-permission" | "contact-permission" | "resume-permission" | "company-result-permission" | "company-notice" | "appeal-notice" | "contacts" | "notice";
            /** Catalog After */
            catalog_after?: string | null;
            /** Catalog Version Id */
            catalog_version_id?: string | null;
            /** Assignment Id */
            assignment_id?: string | null;
            /** Result Grant Id */
            result_grant_id?: string | null;
            /** Organization Id */
            organization_id?: string | null;
            /** Actor Id */
            actor_id?: string | null;
            /** Notice Id */
            notice_id?: string | null;
            /** Need Id */
            need_id?: string | null;
            /** Invitation Id */
            invitation_id?: string | null;
            /** Consent Id */
            consent_id?: string | null;
            /** Consent Purpose */
            consent_purpose?: ("achievement_import" | "achievement_publication" | "ats_export" | "profile_publication" | "contact_disclosure" | "company_task_subscription" | "task_recommendations" | "resume_publication" | "external_service_notifications" | "external_marketing_notifications") | null;
        };
        /** ProcessingRequest */
        ProcessingRequest: {
            /**
             * Candidate Id
             * Format: uuid
             */
            candidate_id: string;
            /**
             * Nonce
             * Format: uuid
             */
            nonce: string;
            /**
             * Requester
             * @enum {string}
             */
            requester: "audit" | "identity" | "achievements" | "integration" | "demo-ats" | "candidate" | "employer" | "assessment" | "coding-workspace" | "code-runner" | "evaluation" | "matching" | "hiring" | "notification" | "media" | "whiteboard" | "proctoring";
            /**
             * Issued At
             * Format: date-time
             */
            issued_at: string;
        };
        /** ProcessingStatus */
        ProcessingStatus: {
            /**
             * Candidate Id
             * Format: uuid
             */
            candidate_id: string;
            /**
             * Nonce
             * Format: uuid
             */
            nonce: string;
            /**
             * Requester
             * @enum {string}
             */
            requester: "audit" | "identity" | "achievements" | "integration" | "demo-ats" | "candidate" | "employer" | "assessment" | "coding-workspace" | "code-runner" | "evaluation" | "matching" | "hiring" | "notification" | "media" | "whiteboard" | "proctoring";
            /**
             * Issued At
             * Format: date-time
             */
            issued_at: string;
            /** Allowed */
            allowed: boolean;
        };
        /** RecordingRequest */
        RecordingRequest: {
            /**
             * Candidate Id
             * Format: uuid
             */
            candidate_id: string;
            /**
             * Nonce
             * Format: uuid
             */
            nonce: string;
            /**
             * Requester
             * @constant
             */
            requester: "media";
            /**
             * Issued At
             * Format: date-time
             */
            issued_at: string;
            /**
             * Consent Id
             * Format: uuid
             */
            consent_id: string;
        };
        /** RecordingStatus */
        RecordingStatus: {
            /**
             * Candidate Id
             * Format: uuid
             */
            candidate_id: string;
            /**
             * Nonce
             * Format: uuid
             */
            nonce: string;
            /**
             * Requester
             * @constant
             */
            requester: "media";
            /**
             * Issued At
             * Format: date-time
             */
            issued_at: string;
            /**
             * Consent Id
             * Format: uuid
             */
            consent_id: string;
            /** Allowed */
            allowed: boolean;
        };
        /** RequestCommand */
        RequestCommand: {
            /**
             * Kind
             * @enum {string}
             */
            kind: "access" | "correction" | "restriction";
            /** Domain */
            domain?: string | null;
            /** Purpose */
            purpose?: string | null;
            /** Reason */
            reason: string;
            /** Proposed Changes */
            proposed_changes?: {
                [key: string]: unknown;
            };
            /** Source Version */
            source_version?: number | null;
            /**
             * Target
             * @default profile
             * @enum {string}
             */
            target: "profile" | "contacts" | "resume" | "preferences" | "declared_achievement" | "notification_preferences";
            /** Target Id */
            target_id?: string | null;
            /** Source Profile Version */
            source_profile_version?: number | null;
        };
        /** RequestView */
        RequestView: {
            /**
             * Request Id
             * Format: uuid
             */
            request_id: string;
            /**
             * Candidate Id
             * Format: uuid
             */
            candidate_id: string;
            /**
             * Kind
             * @enum {string}
             */
            kind: "access" | "correction" | "restriction";
            /** Domain */
            domain: string | null;
            /** Purpose */
            purpose: string | null;
            /**
             * Status
             * @enum {string}
             */
            status: "submitted" | "in_review" | "approved" | "applying" | "rejected" | "completed" | "withdrawn";
            /** Assignee Id */
            assignee_id: string | null;
            /** Data */
            data: {
                [key: string]: unknown;
            };
            /** Restriction Active */
            restriction_active: boolean;
            /** Version */
            version: number;
            /**
             * Created At
             * Format: date-time
             */
            created_at: string;
            /**
             * Due At
             * Format: date-time
             */
            due_at: string;
            /** Completed At */
            completed_at: string | null;
        };
        /** RightsExchange */
        RightsExchange: {
            /** Requester */
            requester: string;
            /**
             * Operation
             * @enum {string}
             */
            operation: "permission" | "export" | "correct" | "export-page";
            /** Cursor */
            cursor?: string | null;
            /**
             * Candidate Id
             * Format: uuid
             */
            candidate_id: string;
            /**
             * Request Id
             * Format: uuid
             */
            request_id: string;
            /** Revision */
            revision: number;
            /**
             * Nonce
             * Format: uuid
             */
            nonce: string;
            /**
             * Issued At
             * Format: date-time
             */
            issued_at: string;
        };
        /** RightsReceipt */
        RightsReceipt: {
            /** Request Digest */
            request_digest: string;
            /**
             * Issued At
             * Format: date-time
             */
            issued_at: string;
            /** Data */
            data: {
                [key: string]: unknown;
            };
        };
        /** ValidationError */
        ValidationError: {
            /** Location */
            loc: (string | number)[];
            /** Message */
            msg: string;
            /** Error Type */
            type: string;
            /** Input */
            input?: unknown;
            /** Context */
            ctx?: Record<string, never>;
        };
    };
    responses: never;
    parameters: never;
    requestBodies: never;
    headers: never;
    pathItems: never;
}
export type $defs = Record<string, never>;
export interface operations {
    exchange_internal_v1_subject_rights__operation__post: {
        parameters: {
            query?: never;
            header?: {
                "X-HR-Signature"?: string | null;
            };
            path: {
                operation: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["RightsExchange"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["RightsReceipt"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    purpose_permission_internal_v1_market_purpose_permission_post: {
        parameters: {
            query?: never;
            header?: {
                "X-HR-Signature"?: string | null;
            };
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["MarketRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["MarketReceipt"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    contact_permission_internal_v1_market_contact_permission_post: {
        parameters: {
            query?: never;
            header?: {
                "X-HR-Signature"?: string | null;
            };
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["MarketRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["MarketReceipt"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    create_grant_v1_company_result_grants_post: {
        parameters: {
            query?: never;
            header: {
                "Idempotency-Key": string;
            };
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["GrantCommand"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["GrantView"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_grant_v1_company_result_grants__grant_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                grant_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["GrantView"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    revoke_grant_v1_company_result_grants__grant_id__revoke_post: {
        parameters: {
            query?: never;
            header: {
                "Idempotency-Key": string;
                "If-Match": string;
            };
            path: {
                grant_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["GrantView"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    permission_internal_v1_market_company_result_permission_post: {
        parameters: {
            query?: never;
            header?: {
                "X-HR-Signature"?: string | null;
            };
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["MarketRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["MarketReceipt"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    own_requests_v1_data_subject_requests_get: {
        parameters: {
            query?: {
                after?: string | null;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["RequestView"][];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    submit_v1_data_subject_requests_post: {
        parameters: {
            query?: never;
            header: {
                "Idempotency-Key": string;
            };
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["RequestCommand"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["RequestView"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    queue_v1_data_subject_requests_queue_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["RequestView"][];
                };
            };
        };
    };
    read_v1_data_subject_requests__request_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                request_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["RequestView"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    claim_v1_data_subject_requests__request_id__claim_post: {
        parameters: {
            query?: never;
            header: {
                "Idempotency-Key": string;
                "If-Match": string;
            };
            path: {
                request_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["RequestView"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    decide_v1_data_subject_requests__request_id__decision_post: {
        parameters: {
            query?: never;
            header: {
                "Idempotency-Key": string;
                "If-Match": string;
            };
            path: {
                request_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["Decision"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["RequestView"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    withdraw_v1_data_subject_requests__request_id__withdraw_post: {
        parameters: {
            query?: never;
            header: {
                "Idempotency-Key": string;
                "If-Match": string;
            };
            path: {
                request_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["RequestView"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    history_v1_data_subject_requests__request_id__history_get: {
        parameters: {
            query?: {
                after_version?: number;
            };
            header?: never;
            path: {
                request_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    export_v1_data_subject_requests__request_id__export_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                request_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    apply_correction_v1_data_subject_requests__request_id__execute_post: {
        parameters: {
            query?: never;
            header: {
                "Idempotency-Key": string;
                "If-Match": string;
            };
            path: {
                request_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["RequestView"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    create_v1_data_subject_requests__request_id__archives_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                request_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    advance_v1_data_subject_requests__request_id__archives__archive_id__advance_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                request_id: string;
                archive_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    manifest_v1_data_subject_requests__request_id__archives__archive_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                request_id: string;
                archive_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    download_v1_data_subject_requests__request_id__archives__archive_id__pages_get: {
        parameters: {
            query?: {
                cursor?: string | null;
            };
            header?: never;
            path: {
                request_id: string;
                archive_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    abandon_v1_data_subject_requests__request_id__archives__archive_id__abandon_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                request_id: string;
                archive_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            204: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    policies_v1_consents_policies_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: string;
                    };
                };
            };
            /** @description Unauthorized */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Forbidden */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Not Found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Conflict */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Unprocessable Content */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Service Unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
        };
    };
    list_consents_v1_consents_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["Consent"][];
                };
            };
            /** @description Unauthorized */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Forbidden */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Not Found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Conflict */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Unprocessable Content */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Service Unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
        };
    };
    grant_consent_v1_consents_post: {
        parameters: {
            query?: never;
            header: {
                "Idempotency-Key": string;
            };
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ConsentCommand"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["Consent"];
                };
            };
            /** @description Unauthorized */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Forbidden */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Not Found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Conflict */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Unprocessable Content */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Service Unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
        };
    };
    revoke_consent_v1_consents__consent_id__revoke_post: {
        parameters: {
            query?: never;
            header: {
                "Idempotency-Key": string;
                "If-Match": string;
            };
            path: {
                consent_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["Consent"];
                };
            };
            /** @description Unauthorized */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Forbidden */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Not Found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Conflict */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Unprocessable Content */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Service Unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
        };
    };
    list_grants_v1_contact_grants_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ContactGrantView"][];
                };
            };
            /** @description Unauthorized */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Forbidden */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Not Found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Conflict */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Unprocessable Content */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Service Unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
        };
    };
    revoke_grant_v1_contact_grants__grant_id__revoke_post: {
        parameters: {
            query?: never;
            header: {
                "Idempotency-Key": string;
                "If-Match": string;
            };
            path: {
                grant_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ContactGrantView"];
                };
            };
            /** @description Unauthorized */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Forbidden */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Not Found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Conflict */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Unprocessable Content */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Service Unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
        };
    };
    request_deletion_v1_deletion_requests_post: {
        parameters: {
            query?: never;
            header: {
                "Idempotency-Key": string;
            };
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            202: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["DeletionView"];
                };
            };
            /** @description Unauthorized */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Forbidden */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Not Found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Conflict */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Unprocessable Content */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Service Unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
        };
    };
    get_deletion_v1_deletion_requests_me_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["DeletionView"];
                };
            };
            /** @description Unauthorized */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Forbidden */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Not Found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Conflict */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Unprocessable Content */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Service Unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
        };
    };
    processing_status_internal_v1_processing_status_post: {
        parameters: {
            query?: never;
            header?: {
                "X-HR-Signature"?: string | null;
            };
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ProcessingRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProcessingStatus"];
                };
            };
            /** @description Unauthorized */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Forbidden */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Not Found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Conflict */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Unprocessable Content */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Service Unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
        };
    };
    assessment_permission_internal_v1_assessment_permission_post: {
        parameters: {
            query?: never;
            header?: {
                "X-HR-Signature"?: string | null;
            };
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["AssessmentPermissionRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AssessmentPermissionStatus"];
                };
            };
            /** @description Unauthorized */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Forbidden */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Not Found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Conflict */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Unprocessable Content */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Service Unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
        };
    };
    recording_permission_internal_v1_recording_permission_post: {
        parameters: {
            query?: never;
            header?: {
                "X-HR-Signature"?: string | null;
            };
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["RecordingRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["RecordingStatus"];
                };
            };
            /** @description Unauthorized */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Forbidden */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Not Found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Conflict */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Unprocessable Content */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Service Unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
        };
    };
    live_health_live_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HealthResponse"];
                };
            };
        };
    };
    ready_health_ready_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HealthResponse"];
                };
            };
            /** @description Service Unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
        };
    };
}
