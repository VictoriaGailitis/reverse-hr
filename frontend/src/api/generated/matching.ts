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
    "/v1/matches": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Find */
        post: operations["find_v1_matches_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/matches/{snapshot_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Snapshot */
        get: operations["get_snapshot_v1_matches__snapshot_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/matches/query-preview": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Query Preview
         * @description Bounded deterministic fallback. The existing confirmed need remains authoritative.
         */
        post: operations["query_preview_v1_matches_query_preview_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/matches/{snapshot_id}/comparison": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Comparison */
        post: operations["comparison_v1_matches__snapshot_id__comparison_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/matches/{snapshot_id}/refinements": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Refine
         * @description A reviewed refinement creates a new snapshot; the prior calculation is immutable.
         */
        post: operations["refine_v1_matches__snapshot_id__refinements_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/matches/governance/catalogs": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Create Catalog */
        post: operations["create_catalog_v1_matches_governance_catalogs_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/matches/governance/policies": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Create Policy */
        post: operations["create_policy_v1_matches_governance_policies_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/matches/governance/versions/{version_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Version */
        get: operations["get_version_v1_matches_governance_versions__version_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/matches/governance/versions/{version_id}/decisions": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Approve */
        post: operations["approve_v1_matches_governance_versions__version_id__decisions_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/matches/intent-previews": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Preview */
        post: operations["preview_v1_matches_intent_previews_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/matches/intent-previews/{preview_id}/confirmation": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Confirm */
        post: operations["confirm_v1_matches_intent_previews__preview_id__confirmation_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/matches/governance/policies/{policy_id}/calibration": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Import Calibration */
        post: operations["import_calibration_v1_matches_governance_policies__policy_id__calibration_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/internal/v1/qualification-policy": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Policy Receipt */
        post: operations["policy_receipt_internal_v1_qualification_policy_post"];
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
        /** AchievementEvidence */
        AchievementEvidence: {
            /**
             * Achievement Id
             * Format: uuid
             */
            achievement_id: string;
            /**
             * Source Id
             * Format: uuid
             */
            source_id: string;
            /** Version */
            version: number;
            /** Demo */
            demo: boolean;
            /** Specialization */
            specialization: string | null;
            /**
             * Format
             * @enum {string}
             */
            format: "individual" | "team";
        };
        /** Approval */
        Approval: {
            /** Expected Revision */
            expected_revision: number;
            /**
             * Decision
             * @enum {string}
             */
            decision: "approved" | "revoked";
            /** Reason */
            reason: string;
        };
        /** Calibration */
        Calibration: {
            /** Dataset Digest */
            dataset_digest: string;
            /** Report Digest */
            report_digest: string;
            /** Labeled Pairs */
            labeled_pairs: number;
            /** Precision At K */
            precision_at_k: number;
            /** Minimum Precision */
            minimum_precision: number;
            /** K */
            k: number;
        };
        /** CalibrationImport */
        CalibrationImport: {
            /** Expected Revision */
            expected_revision: number;
            report: components["schemas"]["Calibration"];
        };
        /** CandidatePreferences */
        CandidatePreferences: {
            salary?: components["schemas"]["MonthlySalary"] | null;
            /** Work Formats */
            work_formats?: ("remote" | "hybrid" | "onsite")[];
            start_window?: components["schemas"]["StartWindow"] | null;
            /**
             * Salary Tolerance Percent
             * @default 0
             */
            salary_tolerance_percent: number;
            /** Version */
            version: number;
            /**
             * Confirmed At
             * Format: date-time
             */
            confirmed_at: string;
            /**
             * Provenance
             * @default candidate_confirmed_self_description
             * @constant
             */
            provenance: "candidate_confirmed_self_description";
        };
        /** ComparisonCommand */
        ComparisonCommand: {
            /** Candidate Ids */
            candidate_ids: string[];
        };
        /** ConditionComparison */
        ConditionComparison: {
            /** Eligible */
            eligible: boolean;
            /**
             * Salary
             * @enum {string}
             */
            salary: "not_required" | "compatible" | "incompatible" | "unknown";
            /**
             * Work Format
             * @enum {string}
             */
            work_format: "not_required" | "compatible" | "incompatible" | "unknown";
            /**
             * Availability
             * @enum {string}
             */
            availability: "not_required" | "compatible" | "incompatible" | "unknown";
            /** Preference Version */
            preference_version?: number | null;
            /** Provenance */
            provenance?: "candidate_confirmed_self_description" | null;
            /** Explanations */
            explanations: string[];
        };
        /** EmploymentConditions */
        EmploymentConditions: {
            salary?: components["schemas"]["MonthlySalary"] | null;
            /** Work Formats */
            work_formats?: ("remote" | "hybrid" | "onsite")[];
            start_window?: components["schemas"]["StartWindow"] | null;
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
        /** MatchQuery */
        MatchQuery: {
            /**
             * Organization Id
             * Format: uuid
             */
            organization_id: string;
            /**
             * Need Id
             * Format: uuid
             */
            need_id: string;
            /**
             * Mode
             * @default production
             * @enum {string}
             */
            mode: "production" | "demo";
            /** After */
            after?: string | null;
            /**
             * Ranking Policy
             * @default legacy
             * @enum {string}
             */
            ranking_policy: "legacy" | "verified-demo-v1" | "governed-v1";
            /** Policy Id */
            policy_id?: string | null;
            /** Intent Preview Id */
            intent_preview_id?: string | null;
            /** Desired Competencies */
            desired_competencies?: string[];
            /**
             * Minimum Competency Score
             * @default 70
             */
            minimum_competency_score: number;
            /**
             * Maximum Evidence Age Days
             * @default 365
             */
            maximum_evidence_age_days: number;
        };
        /** MatchResult */
        MatchResult: {
            /**
             * Snapshot Id
             * Format: uuid
             */
            snapshot_id: string;
            /**
             * Mode
             * @enum {string}
             */
            mode: "production" | "demo";
            /** Matches */
            matches: components["schemas"]["MatchedCandidate"][];
            /** Next Cursor */
            next_cursor: string | null;
        };
        /** MatchedCandidate */
        MatchedCandidate: {
            /** Declared Skills */
            declared_skills?: string[];
            /**
             * Candidate Id
             * Format: uuid
             */
            candidate_id: string;
            /** Display Name */
            display_name: string;
            /** Specialization */
            specialization: string;
            confirmed_grade: components["schemas"]["Grade"] | null;
            /** Decision Id */
            decision_id: string | null;
            /** Version */
            version: number;
            /**
             * Demo
             * @default true
             * @constant
             */
            demo: true;
            qualification?: components["schemas"]["QualificationEvidence"] | null;
            preferences?: components["schemas"]["CandidatePreferences"] | null;
            /** Explanation */
            explanation: string;
            /** Score */
            score: number;
            /**
             * Ranking Version
             * @default confirmed-grade-declared-skills-v1
             * @enum {string}
             */
            ranking_version: "confirmed-grade-declared-skills-v1" | "confirmed-grade-achievements-v2" | "verified-competencies-demo-v1" | "governed-v1";
            /** Policy Id */
            policy_id?: string | null;
            /** Catalog Id */
            catalog_id?: string | null;
            /** Policy Version */
            policy_version?: string | null;
            condition_comparison?: components["schemas"]["ConditionComparison"] | null;
            /** Score Components */
            score_components?: {
                [key: string]: number;
            };
            /** Evaluated On */
            evaluated_on?: string | null;
            /**
             * Calibrated
             * @default false
             */
            calibrated: boolean;
            /** Achievement Evidence */
            achievement_evidence?: components["schemas"]["AchievementEvidence"][];
            /**
             * Achievement Bonus
             * @default 0
             */
            achievement_bonus: number;
            /** Achievement Ids */
            achievement_ids?: string[];
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
        /** NeedView */
        NeedView: {
            conditions?: components["schemas"]["EmploymentConditions"] | null;
            /**
             * Organization Id
             * Format: uuid
             */
            organization_id: string;
            /** Specialization */
            specialization: string;
            confirmed_grade: components["schemas"]["Grade"];
            /** Required Skills */
            required_skills?: string[];
            /**
             * Status
             * @default draft
             * @enum {string}
             */
            status: "draft" | "published" | "closed";
            /**
             * Need Id
             * Format: uuid
             */
            need_id: string;
            /**
             * Created By
             * Format: uuid
             */
            created_by: string;
            /** Version */
            version: number;
        };
        /** ParsedIntent */
        ParsedIntent: {
            /** Specialization */
            specialization?: string | null;
            grade?: components["schemas"]["Grade"] | null;
            /** Mandatory */
            mandatory?: string[];
            /** Desired */
            desired?: string[];
            employment_conditions?: components["schemas"]["EmploymentConditions"] | null;
            /** Conditions */
            conditions?: string[];
            /** Unknowns */
            unknowns?: string[];
            /** Citations */
            citations?: {
                [key: string]: string;
            };
        };
        /** PreviewRequest */
        PreviewRequest: {
            /**
             * Organization Id
             * Format: uuid
             */
            organization_id: string;
            /**
             * Need Id
             * Format: uuid
             */
            need_id: string;
            /**
             * Catalog Id
             * Format: uuid
             */
            catalog_id: string;
            /** Text */
            text: string;
            /**
             * Parser
             * @default llm
             * @enum {string}
             */
            parser: "llm" | "explicit";
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
        /** QueryPreview */
        QueryPreview: {
            proposed_query: components["schemas"]["MatchQuery"];
            confirmed_requirements: components["schemas"]["NeedView"];
            /** Unparsed Text */
            unparsed_text: string;
            /**
             * Requires Employer Confirmation
             * @default true
             * @constant
             */
            requires_employer_confirmation: true;
            /**
             * Parser Version
             * @default explicit-competency-demo-v1
             * @constant
             */
            parser_version: "explicit-competency-demo-v1";
            /** Warnings */
            warnings: string[];
        };
        /** QueryPreviewCommand */
        QueryPreviewCommand: {
            /**
             * Organization Id
             * Format: uuid
             */
            organization_id: string;
            /**
             * Need Id
             * Format: uuid
             */
            need_id: string;
            /** Text */
            text: string;
        };
        /** RankingPolicy */
        RankingPolicy: {
            /** Version */
            version: string;
            /**
             * Catalog Id
             * Format: uuid
             */
            catalog_id: string;
            /**
             * Demo
             * @default true
             */
            demo: boolean;
            /**
             * Competency Weight
             * @default 55
             */
            competency_weight: number;
            /**
             * Assessment Weight
             * @default 25
             */
            assessment_weight: number;
            /**
             * Freshness Weight
             * @default 15
             */
            freshness_weight: number;
            /**
             * Achievement Cap
             * @default 5
             */
            achievement_cap: number;
            /**
             * Minimum Competency Score
             * @default 70
             */
            minimum_competency_score: number;
            /**
             * Current Days
             * @default 180
             */
            current_days: number;
            /**
             * Expiry Days
             * @default 365
             */
            expiry_days: number;
            /**
             * Maximum Preference Age Days
             * @default 90
             */
            maximum_preference_age_days: number;
            /**
             * Advice Target
             * @default 70
             */
            advice_target: number;
            /**
             * Next Grade Score
             * @default 90
             */
            next_grade_score: number;
            /**
             * Next Grade Competency
             * @default 80
             */
            next_grade_competency: number;
            /**
             * Calibration Minimum Precision
             * @default 0.8
             */
            calibration_minimum_precision: number;
            /** Calibration */
            calibration?: {
                [key: string]: unknown;
            } | null;
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
        /** Vocabulary */
        Vocabulary: {
            /** Version */
            version: string;
            /** Entries */
            entries: components["schemas"]["VocabularyEntry"][];
            /** Specializations */
            specializations: string[];
            /**
             * Demo
             * @default true
             */
            demo: boolean;
        };
        /** VocabularyEntry */
        VocabularyEntry: {
            /** Key */
            key: string;
            /** Aliases */
            aliases?: string[];
            /** Evidence Keys */
            evidence_keys: string[];
            /**
             * Kind
             * @default competency
             * @enum {string}
             */
            kind: "competency" | "technology";
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
    find_v1_matches_post: {
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
                "application/json": components["schemas"]["MatchQuery"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["MatchResult"];
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
    get_snapshot_v1_matches__snapshot_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                snapshot_id: string;
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
                    "application/json": components["schemas"]["MatchResult"];
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
    query_preview_v1_matches_query_preview_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["QueryPreviewCommand"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["QueryPreview"];
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
    comparison_v1_matches__snapshot_id__comparison_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                snapshot_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ComparisonCommand"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["MatchResult"];
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
    refine_v1_matches__snapshot_id__refinements_post: {
        parameters: {
            query?: never;
            header: {
                "Idempotency-Key": string;
            };
            path: {
                snapshot_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["MatchQuery"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["MatchResult"];
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
    create_catalog_v1_matches_governance_catalogs_post: {
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
                "application/json": components["schemas"]["Vocabulary"];
            };
        };
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
    create_policy_v1_matches_governance_policies_post: {
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
                "application/json": components["schemas"]["RankingPolicy"];
            };
        };
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
    get_version_v1_matches_governance_versions__version_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                version_id: string;
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
    approve_v1_matches_governance_versions__version_id__decisions_post: {
        parameters: {
            query?: never;
            header: {
                "Idempotency-Key": string;
            };
            path: {
                version_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["Approval"];
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
    preview_v1_matches_intent_previews_post: {
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
                "application/json": components["schemas"]["PreviewRequest"];
            };
        };
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
    confirm_v1_matches_intent_previews__preview_id__confirmation_post: {
        parameters: {
            query?: never;
            header: {
                "Idempotency-Key": string;
            };
            path: {
                preview_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ParsedIntent"];
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
    import_calibration_v1_matches_governance_policies__policy_id__calibration_post: {
        parameters: {
            query?: never;
            header: {
                "Idempotency-Key": string;
            };
            path: {
                policy_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["CalibrationImport"];
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
    policy_receipt_internal_v1_qualification_policy_post: {
        parameters: {
            query?: never;
            header?: {
                "X-HR-Signature"?: string | null;
            };
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
