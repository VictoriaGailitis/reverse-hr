export interface paths {
    "/v1/evaluations/{stage_id}/integrity": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Evaluation Integrity */
        get: operations["evaluation_integrity_v1_evaluations__stage_id__integrity_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/evaluation-reviews/stages/{stage_id}/recording/chunks/{number}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Reviewer Chunk */
        get: operations["reviewer_chunk_v1_evaluation_reviews_stages__stage_id__recording_chunks__number__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/evaluation-reviews/stages/{stage_id}/collection-retry": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Retry */
        post: operations["retry_v1_evaluation_reviews_stages__stage_id__collection_retry_post"];
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
    "/v1/evaluations/stages/{stage_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Intake */
        get: operations["get_intake_v1_evaluations_stages__stage_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/evaluation-automatic/configuration": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Configuration */
        get: operations["configuration_v1_evaluation_automatic_configuration_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/evaluation-automatic/queue": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Queue */
        get: operations["queue_v1_evaluation_automatic_queue_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/evaluation-risks/me": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Mine */
        get: operations["mine_v1_evaluation_risks_me_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/evaluation-risks/queue": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Queue */
        get: operations["queue_v1_evaluation_risks_queue_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/evaluation-risks/{stage_id}/decision": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Decide */
        post: operations["decide_v1_evaluation_risks__stage_id__decision_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/evaluation-reviews/stages/{stage_id}/model-attempts": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Attempts */
        get: operations["attempts_v1_evaluation_reviews_stages__stage_id__model_attempts_get"];
        put?: never;
        /** Request Model */
        post: operations["request_model_v1_evaluation_reviews_stages__stage_id__model_attempts_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/evaluation-reviews/stages/{stage_id}/model-attempts/{attempt_id}/interrupt": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Interrupt Attempt */
        post: operations["interrupt_attempt_v1_evaluation_reviews_stages__stage_id__model_attempts__attempt_id__interrupt_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/internal/v1/stage-score": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Stage Score */
        post: operations["stage_score_internal_v1_stage_score_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/internal/v1/submitted-test-result": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Receive Result */
        post: operations["receive_result_internal_v1_submitted_test_result_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/evaluation-reviews/stages/{stage_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Workspace */
        get: operations["get_workspace_v1_evaluation_reviews_stages__stage_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/evaluation-reviews/stages/{stage_id}/history": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** History */
        get: operations["history_v1_evaluation_reviews_stages__stage_id__history_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/evaluation-reviews/stages/{stage_id}/reviews": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Record Review */
        post: operations["record_review_v1_evaluation_reviews_stages__stage_id__reviews_post"];
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
        /** BoardCitation */
        BoardCitation: {
            /**
             * Snapshot Id
             * Format: uuid
             */
            snapshot_id: string;
            /** Snapshot Digest */
            snapshot_digest: string;
            /**
             * Object Id
             * Format: uuid
             */
            object_id: string;
            /** Object Digest */
            object_digest: string;
        };
        /** BoardDocument */
        BoardDocument: {
            /** State */
            state: components["schemas"]["Shape"][];
        };
        /** Citation */
        Citation: {
            /** Path */
            path: string;
            /** File Digest */
            file_digest: string;
            /** Start Line */
            start_line: number;
            /** End Line */
            end_line: number;
        };
        /** Competency */
        Competency: {
            /** Key */
            key: string;
            /** Description */
            description: string;
        };
        /** Criterion */
        Criterion: {
            /** Key */
            key: string;
            /** Competency */
            competency: string;
            /** Description */
            description: string;
            /** Points */
            points: number;
            /**
             * Evidence
             * @enum {string}
             */
            evidence: "test_result" | "artifact" | "timestamped_recording" | "board_snapshot";
        };
        /** CriterionDecision */
        CriterionDecision: {
            /** Criterion Key */
            criterion_key: string;
            /** Points */
            points?: number | null;
            /** Reason */
            reason: string;
            /** Test Proof Digest */
            test_proof_digest?: string | null;
            /** Citations */
            citations?: components["schemas"]["Citation"][];
            /** Recording Citations */
            recording_citations?: components["schemas"]["RecordingCitation"][];
            /** Board Citations */
            board_citations?: components["schemas"]["BoardCitation"][];
        };
        /** CriterionScore */
        CriterionScore: {
            /** Criterion Key */
            criterion_key: string;
            /** Competency */
            competency: string;
            /** Max Points */
            max_points: number;
            /** Points */
            points?: number | null;
            /**
             * Evidence Type
             * @enum {string}
             */
            evidence_type: "artifact" | "test_result" | "timestamped_recording" | "board_snapshot";
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
        /** File */
        File: {
            /** Path */
            path: string;
            /** Content */
            content: string;
        };
        /** FilesCommand */
        FilesCommand: {
            /** Files */
            files: components["schemas"]["File"][];
        };
        /** GatewayConfiguration */
        GatewayConfiguration: {
            /** Origin */
            origin: string;
            /**
             * Max Request Bytes
             * @default 65536
             */
            max_request_bytes: number;
            /** Max Input Tokens */
            max_input_tokens: number;
            /** Max Output Tokens */
            max_output_tokens: number;
            /** Input Microusd Per Million Tokens */
            input_microusd_per_million_tokens: number;
            /** Output Microusd Per Million Tokens */
            output_microusd_per_million_tokens: number;
            /** Stage Budget Microusd */
            stage_budget_microusd: number;
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
        /** IntakeView */
        IntakeView: {
            /**
             * Stage Id
             * Format: uuid
             */
            stage_id: string;
            /**
             * Session Id
             * Format: uuid
             */
            session_id: string;
            /**
             * Status
             * @enum {string}
             */
            status: "awaiting_material" | "material_retry" | "material_ready" | "material_blocked" | "material_unavailable" | "artifact_ready" | "artifact_retry" | "artifact_blocked" | "artifact_unavailable" | "needs_evidence" | "reviewed";
            /** Version */
            version: number;
            /**
             * Received At
             * Format: date-time
             */
            received_at: string;
            /** Score */
            score?: number | null;
            /** Confirmed Grade */
            confirmed_grade?: null;
            /**
             * Demo
             * @default true
             * @constant
             */
            demo: true;
        };
        /** IntegritySummary */
        IntegritySummary: {
            /** Track Id */
            track_id: string | null;
            /**
             * Candidate Id
             * Format: uuid
             */
            candidate_id: string;
            /**
             * Session Id
             * Format: uuid
             */
            session_id: string;
            /**
             * Stage Id
             * Format: uuid
             */
            stage_id: string;
            /** Version */
            version: number;
            /** Timeline Version */
            timeline_version: number;
            /**
             * Status
             * @enum {string}
             */
            status: "no_material" | "needs_review" | "clear" | "inconclusive" | "concern";
            /** Evidence Digest */
            evidence_digest: string;
            /** Flags */
            flags: string[];
            /** Gaps */
            gaps: {
                [key: string]: number[][];
            };
            /** Streams */
            streams: components["schemas"]["StreamTiming"][];
            latest_review: components["schemas"]["reverse_hr__domains__proctoring__ReviewView"] | null;
            /**
             * Client Telemetry Trusted
             * @default false
             * @constant
             */
            client_telemetry_trusted: false;
        };
        /** ModelAttemptView */
        ModelAttemptView: {
            /**
             * Attempt Id
             * Format: uuid
             */
            attempt_id: string;
            /**
             * Stage Id
             * Format: uuid
             */
            stage_id: string;
            /** Number */
            number: number;
            /** Model */
            model: string;
            /** Prompt Version */
            prompt_version: string;
            /**
             * Status
             * @enum {string}
             */
            status: "pending" | "running" | "ready" | "technical_failure" | "interrupted" | "blocked";
            gateway_configuration?: components["schemas"]["GatewayConfiguration"] | null;
            proposal?: components["schemas"]["ReviewCommand"] | null;
            /** Duration Ms */
            duration_ms: number | null;
            /** Input Tokens */
            input_tokens: number | null;
            /** Output Tokens */
            output_tokens: number | null;
            /** Cost Microusd */
            cost_microusd: number | null;
        };
        /** PinnedMaterial */
        PinnedMaterial: {
            /** Company Organization Id */
            company_organization_id?: string | null;
            /**
             * Consent Id
             * Format: uuid
             */
            consent_id: string;
            /**
             * Plan Version Id
             * Format: uuid
             */
            plan_version_id: string;
            /**
             * Revision Id
             * Format: uuid
             */
            revision_id: string;
            /** Content Digest */
            content_digest: string;
            task: components["schemas"]["Task"];
            /** Competencies */
            competencies: components["schemas"]["Competency"][];
            /** Snapshot Version */
            snapshot_version: number;
            /** Snapshot Digest */
            snapshot_digest: string;
            test_suite?: components["schemas"]["SessionSuitePin"] | null;
            /** Test Cases */
            test_cases?: components["schemas"]["TestCaseMetadata"][];
            /**
             * Demo
             * @default true
             * @constant
             */
            demo: true;
        };
        /** Point */
        Point: {
            /** X */
            x: number;
            /** Y */
            y: number;
        };
        /** PracticalSource */
        PracticalSource: {
            /**
             * Snapshot Id
             * Format: uuid
             */
            snapshot_id: string;
            /**
             * Format
             * @enum {string}
             */
            format: "voice" | "vcv" | "whiteboard";
            /** Digest */
            digest: string;
            board?: components["schemas"]["BoardDocument"] | null;
            /** Transcript Id */
            transcript_id?: string | null;
            /** Transcript Digest */
            transcript_digest?: string | null;
            transcript?: components["schemas"]["TranscriptDocument"] | null;
        };
        /** ProbeRecord */
        ProbeRecord: {
            /**
             * Version
             * @default 1
             */
            version: number;
            /**
             * Node Id
             * Format: uuid
             */
            node_id: string;
            /**
             * Checked At
             * Format: date-time
             */
            checked_at: string;
            /** Fingerprint */
            fingerprint: string;
            /** Passed */
            passed: number;
        };
        /** RecordingCitation */
        RecordingCitation: {
            /**
             * Snapshot Id
             * Format: uuid
             */
            snapshot_id: string;
            /** Recording Digest */
            recording_digest: string;
            /**
             * Transcript Id
             * Format: uuid
             */
            transcript_id: string;
            /** Transcript Digest */
            transcript_digest: string;
            /** Segment Key */
            segment_key: string;
            /** Start Ms */
            start_ms: number;
            /** End Ms */
            end_ms: number;
        };
        /** ResultDelivery */
        ResultDelivery: {
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
             * @default code-runner
             * @constant
             */
            requester: "code-runner";
            /**
             * Issued At
             * Format: date-time
             */
            issued_at: string;
            /**
             * Purpose
             * @default submitted-test-delivery
             * @constant
             */
            purpose: "submitted-test-delivery";
            proof: components["schemas"]["TestProof"];
            /** Proof Signature */
            proof_signature: string;
        };
        /** ResultReceipt */
        ResultReceipt: {
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
             * @default code-runner
             * @constant
             */
            requester: "code-runner";
            /**
             * Issued At
             * Format: date-time
             */
            issued_at: string;
            /**
             * Purpose
             * @default submitted-test-delivery
             * @constant
             */
            purpose: "submitted-test-delivery";
            /**
             * Stage Id
             * Format: uuid
             */
            stage_id: string;
            /** Proof Digest */
            proof_digest: string;
            /** Allowed */
            allowed: boolean;
        };
        /** RetryView */
        RetryView: {
            /**
             * Stage Id
             * Format: uuid
             */
            stage_id: string;
            /** Status */
            status: string;
            /** Version */
            version: number;
        };
        /** ReviewCommand */
        ReviewCommand: {
            /** Model Attempt Id */
            model_attempt_id?: string | null;
            /** Decisions */
            decisions: components["schemas"]["CriterionDecision"][];
            /** Reason */
            reason: string;
        };
        /** ReviewResult */
        ReviewResult: {
            /**
             * Stage Id
             * Format: uuid
             */
            stage_id: string;
            /** Version */
            version: number;
            /**
             * Status
             * @enum {string}
             */
            status: "artifact_ready" | "needs_evidence" | "reviewed";
            /** Score */
            score: number | null;
            /** Confirmed Grade */
            confirmed_grade?: null;
            latest: components["schemas"]["reverse_hr__domains__evaluation_review__ReviewView"] | null;
            /**
             * Demo
             * @default true
             * @constant
             */
            demo: true;
        };
        /** ReviewWorkspace */
        ReviewWorkspace: {
            /**
             * Stage Id
             * Format: uuid
             */
            stage_id: string;
            /** Version */
            version: number;
            /**
             * Status
             * @enum {string}
             */
            status: "artifact_ready" | "needs_evidence" | "reviewed";
            /** Score */
            score: number | null;
            /** Confirmed Grade */
            confirmed_grade?: null;
            latest: components["schemas"]["reverse_hr__domains__evaluation_review__ReviewView"] | null;
            /**
             * Demo
             * @default true
             * @constant
             */
            demo: true;
            material: components["schemas"]["PinnedMaterial"];
            /** Source */
            source: components["schemas"]["FilesCommand"] | components["schemas"]["PracticalSource"];
            /** Trusted Test Points */
            trusted_test_points?: {
                [key: string]: number | null;
            };
            /** Test Proof Digest */
            test_proof_digest?: string | null;
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
        /** RiskDecision */
        RiskDecision: {
            /**
             * Action
             * @enum {string}
             */
            action: "dismiss" | "require_verification" | "complete_verification";
            /** Reason */
            reason: string;
            /** Verification Stage Id */
            verification_stage_id?: string | null;
        };
        /** ScoreReceipt */
        ScoreReceipt: {
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
             * @default assessment
             * @constant
             */
            requester: "assessment";
            /**
             * Issued At
             * Format: date-time
             */
            issued_at: string;
            /**
             * Purpose
             * @default session-score
             * @constant
             */
            purpose: "session-score";
            /**
             * Session Id
             * Format: uuid
             */
            session_id: string;
            /**
             * Stage Id
             * Format: uuid
             */
            stage_id: string;
            /**
             * Workspace Id
             * Format: uuid
             */
            workspace_id: string;
            /**
             * Snapshot Id
             * Format: uuid
             */
            snapshot_id: string;
            /** Allowed */
            allowed: boolean;
            stage?: components["schemas"]["StageScore"] | null;
        };
        /** ScoreRequest */
        ScoreRequest: {
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
             * @default assessment
             * @constant
             */
            requester: "assessment";
            /**
             * Issued At
             * Format: date-time
             */
            issued_at: string;
            /**
             * Purpose
             * @default session-score
             * @constant
             */
            purpose: "session-score";
            /**
             * Session Id
             * Format: uuid
             */
            session_id: string;
            /**
             * Stage Id
             * Format: uuid
             */
            stage_id: string;
            /**
             * Workspace Id
             * Format: uuid
             */
            workspace_id: string;
            /**
             * Snapshot Id
             * Format: uuid
             */
            snapshot_id: string;
        };
        /** Segment */
        Segment: {
            /** Key */
            key: string;
            /** Start Ms */
            start_ms: number;
            /** End Ms */
            end_ms: number;
            /** Text */
            text: string;
        };
        /** SessionSuitePin */
        SessionSuitePin: {
            /** Position */
            position: number;
            /**
             * Revision Id
             * Format: uuid
             */
            revision_id: string;
            /** Task Key */
            task_key: string;
            pin: components["schemas"]["SuitePin"];
            /**
             * Validation Id
             * Format: uuid
             */
            validation_id: string;
            /** Verdict Digest */
            verdict_digest: string;
            /** Attestation Digest */
            attestation_digest: string;
            /**
             * Node Id
             * Format: uuid
             */
            node_id: string;
            /**
             * Policy Id
             * Format: uuid
             */
            policy_id: string;
            /**
             * Stage Id
             * Format: uuid
             */
            stage_id: string;
        };
        /** Shape */
        Shape: {
            /**
             * Id
             * Format: uuid
             */
            id: string;
            /**
             * Kind
             * @enum {string}
             */
            kind: "stroke" | "rectangle" | "ellipse" | "text";
            /** Points */
            points: components["schemas"]["Point"][];
            /**
             * Text
             * @default
             */
            text: string;
            /**
             * Color
             * @default #000000
             */
            color: string;
            /**
             * Width
             * @default 2
             */
            width: number;
        };
        /** StageScore */
        StageScore: {
            /**
             * Additional Verification Required
             * @default false
             */
            additional_verification_required: boolean;
            /**
             * Origin
             * @default human
             * @enum {string}
             */
            origin: "human" | "automatic";
            /** Model Attempt Id */
            model_attempt_id?: string | null;
            /** Llm Model */
            llm_model?: string | null;
            /** Llm Prompt Digest */
            llm_prompt_digest?: string | null;
            /** Snapshot Version */
            snapshot_version: number;
            /** Snapshot Digest */
            snapshot_digest: string;
            /**
             * Revision Id
             * Format: uuid
             */
            revision_id: string;
            /** Content Digest */
            content_digest: string;
            /** Task Key */
            task_key: string;
            /** Review Id */
            review_id: string | null;
            /** Reviewer Id */
            reviewer_id: string | null;
            /** Criteria */
            criteria: components["schemas"]["CriterionScore"][];
            /** Score */
            score?: number | null;
            /** Evidence Digest */
            evidence_digest: string;
        };
        /** StreamTiming */
        StreamTiming: {
            /**
             * Stream Id
             * Format: uuid
             */
            stream_id: string;
            /**
             * Client Started At
             * Format: date-time
             */
            client_started_at: string;
            /**
             * Server Received At
             * Format: date-time
             */
            server_received_at: string;
            /** Clock Or Delivery Offset Ms */
            clock_or_delivery_offset_ms: number;
        };
        /** SuitePin */
        SuitePin: {
            /**
             * Suite Id
             * Format: uuid
             */
            suite_id: string;
            /**
             * Revision Id
             * Format: uuid
             */
            revision_id: string;
            /** Content Digest */
            content_digest: string;
            /** Definition Digest */
            definition_digest: string;
            /** Runtime Fingerprint */
            runtime_fingerprint: string;
        };
        /** Task */
        Task: {
            /** Key */
            key: string;
            /**
             * Format
             * @enum {string}
             */
            format: "code" | "sql" | "vcv" | "voice" | "whiteboard";
            /** Instruction */
            instruction: string;
            /** Duration Seconds */
            duration_seconds: number;
            /** Reference Answer */
            reference_answer: string;
            /** Rubric */
            rubric: components["schemas"]["Criterion"][];
            /** Follows Task Key */
            follows_task_key?: string | null;
        };
        /** TestCaseMetadata */
        TestCaseMetadata: {
            /** Case Key */
            case_key: string;
            /** Criterion Key */
            criterion_key: string;
            /** Case Digest */
            case_digest: string;
        };
        /** TestOutcome */
        TestOutcome: {
            /** Case Key */
            case_key: string;
            /** Criterion Key */
            criterion_key: string;
            /**
             * Attempt Id
             * Format: uuid
             */
            attempt_id: string;
            /** Input Digest */
            input_digest: string;
            /** Case Digest */
            case_digest: string;
            /** Capture Digest */
            capture_digest: string;
            /**
             * Verdict
             * @enum {string}
             */
            verdict: "passed" | "failed" | "inconclusive";
        };
        /** TestProof */
        TestProof: {
            /**
             * Producer
             * @default code-runner
             * @constant
             */
            producer: "code-runner";
            /**
             * Purpose
             * @default submitted-test-result
             * @constant
             */
            purpose: "submitted-test-result";
            /**
             * Candidate Id
             * Format: uuid
             */
            candidate_id: string;
            /**
             * Session Id
             * Format: uuid
             */
            session_id: string;
            /**
             * Stage Id
             * Format: uuid
             */
            stage_id: string;
            /**
             * Workspace Id
             * Format: uuid
             */
            workspace_id: string;
            /**
             * Snapshot Id
             * Format: uuid
             */
            snapshot_id: string;
            /** Snapshot Version */
            snapshot_version: number;
            /** Snapshot Digest */
            snapshot_digest: string;
            binding: components["schemas"]["SessionSuitePin"];
            probe: components["schemas"]["ProbeRecord"];
            /**
             * Completed At
             * Format: date-time
             */
            completed_at: string;
            /** Outcomes */
            outcomes: components["schemas"]["TestOutcome"][];
            /**
             * Demo
             * @default true
             * @constant
             */
            demo: true;
        };
        /** TranscriptDocument */
        TranscriptDocument: {
            /** Duration Ms */
            duration_ms: number;
            /** Language */
            language: string;
            /** Segments */
            segments: components["schemas"]["Segment"][];
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
        /** ReviewView */
        reverse_hr__domains__evaluation_review__ReviewView: {
            /** Model Attempt Id */
            model_attempt_id?: string | null;
            /** Decisions */
            decisions: components["schemas"]["CriterionDecision"][];
            /** Reason */
            reason: string;
            /**
             * Origin
             * @default human
             * @enum {string}
             */
            origin: "human" | "automatic";
            /**
             * Review Id
             * Format: uuid
             */
            review_id: string;
            /**
             * Reviewer Id
             * Format: uuid
             */
            reviewer_id: string;
            /** Number */
            number: number;
            /** Intake Version */
            intake_version: number;
            /** Score */
            score: number | null;
            /**
             * Created At
             * Format: date-time
             */
            created_at: string;
        };
        /** ReviewView */
        reverse_hr__domains__proctoring__ReviewView: {
            /** Timeline Version */
            timeline_version: number;
            /** Evidence Digest */
            evidence_digest: string;
            /**
             * Outcome
             * @enum {string}
             */
            outcome: "clear" | "inconclusive" | "concern";
            /** Reason */
            reason: string;
            /** Evidence Ids */
            evidence_ids: string[];
            /**
             * Review Id
             * Format: uuid
             */
            review_id: string;
            /** Number */
            number: number;
            /**
             * Reviewer Id
             * Format: uuid
             */
            reviewer_id: string;
            /**
             * Created At
             * Format: date-time
             */
            created_at: string;
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
    evaluation_integrity_v1_evaluations__stage_id__integrity_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                stage_id: string;
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
                    "application/json": components["schemas"]["IntegritySummary"];
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
    reviewer_chunk_v1_evaluation_reviews_stages__stage_id__recording_chunks__number__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                stage_id: string;
                number: number;
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
    retry_v1_evaluation_reviews_stages__stage_id__collection_retry_post: {
        parameters: {
            query?: never;
            header: {
                "Idempotency-Key": string;
                "If-Match": string;
            };
            path: {
                stage_id: string;
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
                    "application/json": components["schemas"]["RetryView"];
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
    get_intake_v1_evaluations_stages__stage_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                stage_id: string;
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
                    "application/json": components["schemas"]["IntakeView"];
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
    configuration_v1_evaluation_automatic_configuration_get: {
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
        };
    };
    queue_v1_evaluation_automatic_queue_get: {
        parameters: {
            query?: {
                limit?: number;
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
    mine_v1_evaluation_risks_me_get: {
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
        };
    };
    queue_v1_evaluation_risks_queue_get: {
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
    decide_v1_evaluation_risks__stage_id__decision_post: {
        parameters: {
            query?: never;
            header: {
                "Idempotency-Key": string;
                "If-Match": string;
            };
            path: {
                stage_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["RiskDecision"];
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
    attempts_v1_evaluation_reviews_stages__stage_id__model_attempts_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                stage_id: string;
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
                    "application/json": components["schemas"]["ModelAttemptView"][];
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
    request_model_v1_evaluation_reviews_stages__stage_id__model_attempts_post: {
        parameters: {
            query?: never;
            header: {
                "Idempotency-Key": string;
            };
            path: {
                stage_id: string;
            };
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
                    "application/json": components["schemas"]["ModelAttemptView"];
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
    interrupt_attempt_v1_evaluation_reviews_stages__stage_id__model_attempts__attempt_id__interrupt_post: {
        parameters: {
            query?: never;
            header: {
                "Idempotency-Key": string;
            };
            path: {
                stage_id: string;
                attempt_id: string;
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
                    "application/json": components["schemas"]["ModelAttemptView"];
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
    stage_score_internal_v1_stage_score_post: {
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
                "application/json": components["schemas"]["ScoreRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ScoreReceipt"];
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
    receive_result_internal_v1_submitted_test_result_post: {
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
                "application/json": components["schemas"]["ResultDelivery"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ResultReceipt"];
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
    get_workspace_v1_evaluation_reviews_stages__stage_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                stage_id: string;
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
                    "application/json": components["schemas"]["ReviewWorkspace"];
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
    history_v1_evaluation_reviews_stages__stage_id__history_get: {
        parameters: {
            query?: {
                before?: number | null;
            };
            header?: never;
            path: {
                stage_id: string;
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
                    "application/json": components["schemas"]["reverse_hr__domains__evaluation_review__ReviewView"][];
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
    record_review_v1_evaluation_reviews_stages__stage_id__reviews_post: {
        parameters: {
            query?: never;
            header: {
                "Idempotency-Key": string;
                "If-Match": string;
            };
            path: {
                stage_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ReviewCommand"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ReviewResult"];
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
