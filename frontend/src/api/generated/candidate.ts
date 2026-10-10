export interface paths {
    "/v1/candidates/me/resume-imports": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Imports */
        get: operations["imports_v1_candidates_me_resume_imports_get"];
        put?: never;
        /** Upload */
        post: operations["upload_v1_candidates_me_resume_imports_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/candidates/me/resume-imports/{import_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Import */
        get: operations["get_import_v1_candidates_me_resume_imports__import_id__get"];
        put?: never;
        post?: never;
        /** Remove Import */
        delete: operations["remove_import_v1_candidates_me_resume_imports__import_id__delete"];
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/candidates/me/resume-imports/{import_id}/source.pdf": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Original */
        get: operations["original_v1_candidates_me_resume_imports__import_id__source_pdf_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/candidates/me/resume-imports/{import_id}/confirm": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Confirm */
        post: operations["confirm_v1_candidates_me_resume_imports__import_id__confirm_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/candidates/me/resume": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Resume */
        get: operations["get_resume_v1_candidates_me_resume_get"];
        /** Edit */
        put: operations["edit_v1_candidates_me_resume_put"];
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/candidates/me/resume/publication": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        /** Publication */
        put: operations["publication_v1_candidates_me_resume_publication_put"];
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/candidates/me/resume-imports/{import_id}/retry": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Retry */
        post: operations["retry_v1_candidates_me_resume_imports__import_id__retry_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/candidates/{candidate_id}/resume.pdf": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Pdf */
        get: operations["pdf_v1_candidates__candidate_id__resume_pdf_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/internal/v1/market/profile": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Profile Card */
        post: operations["profile_card_internal_v1_market_profile_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/internal/v1/market/contacts": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Disclose */
        post: operations["disclose_internal_v1_market_contacts_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
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
    "/v1/candidates/me": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Profile */
        get: operations["get_profile_v1_candidates_me_get"];
        /** Update Profile */
        put: operations["update_profile_v1_candidates_me_put"];
        /** Create Profile */
        post: operations["create_profile_v1_candidates_me_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/candidates/me/grade-history": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** History */
        get: operations["history_v1_candidates_me_grade_history_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/candidates/me/qualification": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Qualification Report */
        get: operations["qualification_report_v1_candidates_me_qualification_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/candidates/me/preferences": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Preferences */
        get: operations["get_preferences_v1_candidates_me_preferences_get"];
        /** Update Preferences */
        put: operations["update_preferences_v1_candidates_me_preferences_put"];
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/candidates/me/publication": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        /** Publish */
        put: operations["publish_v1_candidates_me_publication_put"];
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/candidates/me/contacts": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        /** Update Contacts */
        put: operations["update_contacts_v1_candidates_me_contacts_put"];
        post?: never;
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
        /** CandidatePreferenceCommand */
        CandidatePreferenceCommand: {
            salary?: components["schemas"]["MonthlySalary"] | null;
            /** Work Formats */
            work_formats?: ("remote" | "hybrid" | "onsite")[];
            start_window?: components["schemas"]["StartWindow"] | null;
            /**
             * Salary Tolerance Percent
             * @default 0
             */
            salary_tolerance_percent: number;
            /**
             * Share In Matching
             * @default false
             */
            share_in_matching: boolean;
            /**
             * Confirmed
             * @constant
             */
            confirmed: true;
        };
        /** ContactsCommand */
        ContactsCommand: {
            /** Email */
            email: string;
            /** Phone */
            phone?: string | null;
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
        /** ExtractedPDF */
        ExtractedPDF: {
            /** Text */
            text: string;
            /** Pages */
            pages: number;
            /** Ocr Pages */
            ocr_pages?: number[];
            /**
             * Extractor
             * @default isolated-pdf-v1
             * @constant
             */
            extractor: "isolated-pdf-v1";
        };
        /**
         * Grade
         * @enum {string}
         */
        Grade: "junior" | "middle" | "senior" | "lead";
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
        /** HistoryItem */
        HistoryItem: {
            /** Specialization */
            specialization: string;
            target_grade: components["schemas"]["Grade"];
            /**
             * Status
             * @enum {string}
             */
            status: "confirmed" | "rejected" | "technical_failure";
            /**
             * Decided At
             * Format: date-time
             */
            decided_at: string;
            /**
             * Decision Revision
             * @default 1
             */
            decision_revision: number;
            /** Supersedes Decision Id */
            supersedes_decision_id?: string | null;
            /**
             * Demo
             * @default true
             * @constant
             */
            demo: true;
            qualification?: components["schemas"]["QualificationEvidence"] | null;
            /**
             * Decision Id
             * Format: uuid
             */
            decision_id: string;
            /**
             * Session Id
             * Format: uuid
             */
            session_id: string;
        };
        /** ImportRemoved */
        ImportRemoved: {
            /**
             * Import Id
             * Format: uuid
             */
            import_id: string;
            /**
             * Deleted
             * @default true
             * @constant
             */
            deleted: true;
        };
        /** ImportView */
        ImportView: {
            /**
             * Import Id
             * Format: uuid
             */
            import_id: string;
            /**
             * Status
             * @enum {string}
             */
            status: "pending" | "processing" | "review_ready" | "confirmed" | "failed";
            /** Digest */
            digest: string;
            /** Size */
            size: number;
            /** Version */
            version: number;
            /** Attempts */
            attempts: number;
            /** Error */
            error: string | null;
            extraction: components["schemas"]["ExtractedPDF"] | null;
            /** Requires Confirmation */
            requires_confirmation: boolean;
            proposal: components["schemas"]["ResumeFields"] | null;
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
            /**
             * Purpose
             * @enum {string}
             */
            purpose: "profile" | "membership" | "affiliation" | "content-membership" | "need" | "purpose-permission" | "contact-permission" | "resume-permission" | "company-result-permission" | "company-notice" | "appeal-notice" | "contacts" | "notice";
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
            consent_purpose?: ("achievement_import" | "achievement_publication" | "ats_export" | "profile_publication" | "contact_disclosure" | "company_task_subscription" | "resume_publication" | "external_service_notifications" | "external_marketing_notifications") | null;
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
            /**
             * Purpose
             * @enum {string}
             */
            purpose: "profile" | "membership" | "affiliation" | "content-membership" | "need" | "purpose-permission" | "contact-permission" | "resume-permission" | "company-result-permission" | "company-notice" | "appeal-notice" | "contacts" | "notice";
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
            consent_purpose?: ("achievement_import" | "achievement_publication" | "ats_export" | "profile_publication" | "contact_disclosure" | "company_task_subscription" | "resume_publication" | "external_service_notifications" | "external_marketing_notifications") | null;
        };
        /** MonthlySalary */
        MonthlySalary: {
            /**
             * Currency
             * @default RUB
             * @constant
             */
            currency: "RUB";
            /**
             * Period
             * @default month
             * @constant
             */
            period: "month";
            /**
             * Tax Basis
             * @enum {string}
             */
            tax_basis: "gross" | "net";
            /** Minimum */
            minimum: number;
            /** Maximum */
            maximum: number;
        };
        /** Profile */
        Profile: {
            /** Display Name */
            display_name: string;
            /** Specialization */
            specialization: string;
            declared_grade: components["schemas"]["Grade"];
            /**
             * Candidate Id
             * Format: uuid
             */
            candidate_id: string;
            confirmed_grade?: components["schemas"]["Grade"] | null;
            /** Version */
            version: number;
        };
        /** ProfileUpdate */
        ProfileUpdate: {
            /** Display Name */
            display_name: string;
            /** Specialization */
            specialization: string;
            declared_grade: components["schemas"]["Grade"];
        };
        /** PublicationCommand */
        PublicationCommand: {
            /** Declared Skills */
            declared_skills?: string[];
            /** Published */
            published: boolean;
            /** Consent Id */
            consent_id?: string | null;
        };
        /** QualificationAdvice */
        QualificationAdvice: {
            /**
             * Decision Id
             * Format: uuid
             */
            decision_id: string;
            /** Specialization */
            specialization: string;
            /**
             * Assessed At
             * Format: date-time
             */
            assessed_at: string;
            current_grade: components["schemas"]["Grade"] | null;
            /**
             * Freshness
             * @enum {string}
             */
            freshness: "current" | "aging" | "expired";
            /** Repeat Recommended */
            repeat_recommended: boolean;
            /** Retry Available */
            retry_available: boolean;
            /**
             * Next Attempt At
             * Format: date-time
             */
            next_attempt_at: string;
            /**
             * Grade Change Available At
             * Format: date-time
             */
            grade_change_available_at: string;
            recommended_next_grade: components["schemas"]["Grade"] | null;
            /** Feedback */
            feedback: string[];
            /**
             * Policy Version
             * @default qualification-advice-demo-v1
             */
            policy_version: string;
            /**
             * Calibrated
             * @default false
             */
            calibrated: boolean;
            /**
             * Demo
             * @default true
             */
            demo: boolean;
        };
        /** QualificationEvidence */
        QualificationEvidence: {
            /**
             * Policy Id
             * Format: uuid
             */
            policy_id: string;
            /** Evidence Digest */
            evidence_digest: string;
            /**
             * Assessed At
             * Format: date-time
             */
            assessed_at: string;
            /** Score */
            score: number;
            /** Competency Scores */
            competency_scores: {
                [key: string]: number;
            };
            /** Competency Minimums */
            competency_minimums?: {
                [key: string]: number;
            };
            /**
             * Next Attempt At
             * Format: date-time
             */
            next_attempt_at: string;
            /**
             * Grade Change Available At
             * Format: date-time
             */
            grade_change_available_at: string;
            /**
             * Demo
             * @default true
             * @constant
             */
            demo: true;
        };
        /** ResumeConfirmation */
        ResumeConfirmation: {
            /** Declared Skills */
            declared_skills?: string[];
            /** Display Name */
            display_name: string;
            /** Specialization */
            specialization: string;
            declared_grade: components["schemas"]["Grade"];
            /**
             * Summary
             * @default
             */
            summary: string;
            /** Experience */
            experience?: string[];
            /** Education */
            education?: string[];
            contacts?: components["schemas"]["ContactsCommand"] | null;
            /** Profile Version */
            profile_version: number;
        };
        /** ResumeFields */
        ResumeFields: {
            /** Declared Skills */
            declared_skills?: string[];
            /** Display Name */
            display_name: string;
            /** Specialization */
            specialization: string;
            declared_grade: components["schemas"]["Grade"];
            /**
             * Summary
             * @default
             */
            summary: string;
            /** Experience */
            experience?: string[];
            /** Education */
            education?: string[];
            contacts?: components["schemas"]["ContactsCommand"] | null;
        };
        /** ResumePublication */
        ResumePublication: {
            /** Published */
            published: boolean;
            /** Consent Id */
            consent_id?: string | null;
        };
        /** ResumeView */
        ResumeView: {
            fields: components["schemas"]["ResumeFields"];
            /** Version */
            version: number;
            /** Published */
            published: boolean;
            /** Consent Id */
            consent_id: string | null;
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
        /** StartWindow */
        StartWindow: {
            /**
             * Earliest
             * Format: date
             */
            earliest: string;
            /**
             * Latest
             * Format: date
             */
            latest: string;
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
    imports_v1_candidates_me_resume_imports_get: {
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
                    "application/json": components["schemas"]["ImportView"][];
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
    upload_v1_candidates_me_resume_imports_post: {
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
                "application/pdf": string;
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ImportView"];
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
    get_import_v1_candidates_me_resume_imports__import_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                import_id: string;
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
                    "application/json": components["schemas"]["ImportView"];
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
    remove_import_v1_candidates_me_resume_imports__import_id__delete: {
        parameters: {
            query?: never;
            header: {
                "Idempotency-Key": string;
                "If-Match": string;
            };
            path: {
                import_id: string;
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
                    "application/json": components["schemas"]["ImportRemoved"];
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
    original_v1_candidates_me_resume_imports__import_id__source_pdf_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                import_id: string;
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
                    "application/pdf": string;
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
    confirm_v1_candidates_me_resume_imports__import_id__confirm_post: {
        parameters: {
            query?: never;
            header: {
                "Idempotency-Key": string;
                "If-Match": string;
            };
            path: {
                import_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ResumeConfirmation"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ResumeView"];
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
    get_resume_v1_candidates_me_resume_get: {
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
                    "application/json": components["schemas"]["ResumeView"];
                };
            };
        };
    };
    edit_v1_candidates_me_resume_put: {
        parameters: {
            query?: never;
            header: {
                "Idempotency-Key": string;
                "If-Match": string;
            };
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ResumeConfirmation"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ResumeView"];
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
    publication_v1_candidates_me_resume_publication_put: {
        parameters: {
            query?: never;
            header: {
                "Idempotency-Key": string;
                "If-Match": string;
            };
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ResumePublication"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ResumeView"];
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
    retry_v1_candidates_me_resume_imports__import_id__retry_post: {
        parameters: {
            query?: never;
            header: {
                "Idempotency-Key": string;
                "If-Match": string;
            };
            path: {
                import_id: string;
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
                    "application/json": components["schemas"]["ImportView"];
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
    pdf_v1_candidates__candidate_id__resume_pdf_get: {
        parameters: {
            query?: {
                variant?: "full" | "anonymous";
                organization_id?: string | null;
                invitation_id?: string | null;
            };
            header?: never;
            path: {
                candidate_id: string;
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
                    "application/pdf": string;
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
    profile_card_internal_v1_market_profile_post: {
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
    disclose_internal_v1_market_contacts_post: {
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
    get_profile_v1_candidates_me_get: {
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
                    "application/json": components["schemas"]["Profile"];
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
    update_profile_v1_candidates_me_put: {
        parameters: {
            query?: never;
            header: {
                "Idempotency-Key": string;
                "If-Match": string;
            };
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ProfileUpdate"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["Profile"];
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
    create_profile_v1_candidates_me_post: {
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
                "application/json": components["schemas"]["ProfileUpdate"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["Profile"];
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
    history_v1_candidates_me_grade_history_get: {
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
                    "application/json": components["schemas"]["HistoryItem"][];
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
    qualification_report_v1_candidates_me_qualification_get: {
        parameters: {
            query?: {
                policy_id?: string | null;
                policy_mode?: "demo" | "production";
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
                    "application/json": components["schemas"]["QualificationAdvice"][];
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
    get_preferences_v1_candidates_me_preferences_get: {
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
                    "application/json": unknown;
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
    update_preferences_v1_candidates_me_preferences_put: {
        parameters: {
            query?: never;
            header: {
                "Idempotency-Key": string;
                "If-Match": string;
            };
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["CandidatePreferenceCommand"];
            };
        };
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
    publish_v1_candidates_me_publication_put: {
        parameters: {
            query?: never;
            header: {
                "Idempotency-Key": string;
                "If-Match": string;
            };
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["PublicationCommand"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PublicationCommand"];
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
    update_contacts_v1_candidates_me_contacts_put: {
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
                "application/json": components["schemas"]["ContactsCommand"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ContactsCommand"];
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
