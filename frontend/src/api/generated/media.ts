export interface paths {
    "/v1/environment.js": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Practical Ui */
        get: operations["practical_ui_v1_environment_js_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/internal/v1/practical-receipt": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Snapshot Receipt */
        post: operations["snapshot_receipt_internal_v1_practical_receipt_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/internal/v1/evaluation-artifact": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Artifact */
        post: operations["artifact_internal_v1_evaluation_artifact_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/recordings/{recording_id}/transcription": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Transcription */
        get: operations["get_transcription_v1_recordings__recording_id__transcription_get"];
        put?: never;
        /** Request Transcription */
        post: operations["request_transcription_v1_recordings__recording_id__transcription_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/recordings/{recording_id}/transcription/{attempt_id}/interrupt": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Interrupt */
        post: operations["interrupt_v1_recordings__recording_id__transcription__attempt_id__interrupt_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/internal/v1/recording-playback": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Playback */
        post: operations["playback_internal_v1_recording_playback_post"];
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
    "/v1/recordings/admission": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Recording Admission */
        post: operations["recording_admission_v1_recordings_admission_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/recordings": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Create */
        post: operations["create_v1_recordings_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/recordings/{recording_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Recording */
        get: operations["get_recording_v1_recordings__recording_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/recordings/{recording_id}/chunks/{number}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        /** Upload */
        put: operations["upload_v1_recordings__recording_id__chunks__number__put"];
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/recordings/{recording_id}/restart": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Restart */
        post: operations["restart_v1_recordings__recording_id__restart_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/recordings/{recording_id}/finalize": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Finalize */
        post: operations["finalize_v1_recordings__recording_id__finalize_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/recordings/{recording_id}/content": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Content */
        get: operations["content_v1_recordings__recording_id__content_get"];
        put?: never;
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
        /** AntivirusReport */
        AntivirusReport: {
            /** Engine */
            engine: string;
            /** Signature Version */
            signature_version: number;
            /**
             * Signatures At
             * Format: date-time
             */
            signatures_at: string;
            /**
             * Scanned At
             * Format: date-time
             */
            scanned_at: string;
            /** Digest */
            digest: string;
            /**
             * Verdict
             * @default clean
             * @constant
             */
            verdict: "clean";
        };
        /** ArtifactReceipt */
        ArtifactReceipt: {
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
            requester: "evaluation";
            /**
             * Issued At
             * Format: date-time
             */
            issued_at: string;
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
            /**
             * Purpose
             * @default rubric-evidence
             * @constant
             */
            purpose: "rubric-evidence";
            /**
             * Format
             * @enum {string}
             */
            format: "code" | "sql" | "voice" | "vcv" | "whiteboard";
            /** Snapshot Version */
            snapshot_version: number;
            /** Digest */
            digest: string;
            /** Allowed */
            allowed: boolean;
            /** Manifest */
            manifest?: components["schemas"]["FilesCommand"] | components["schemas"]["PracticalSource"] | null;
        };
        /** ArtifactRequest */
        ArtifactRequest: {
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
            requester: "evaluation";
            /**
             * Issued At
             * Format: date-time
             */
            issued_at: string;
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
            /**
             * Purpose
             * @default rubric-evidence
             * @constant
             */
            purpose: "rubric-evidence";
            /**
             * Format
             * @enum {string}
             */
            format: "code" | "sql" | "voice" | "vcv" | "whiteboard";
            /** Snapshot Version */
            snapshot_version: number;
            /** Digest */
            digest: string;
        };
        /** BoardDocument */
        BoardDocument: {
            /** State */
            state: components["schemas"]["Shape"][];
        };
        /** ChunkCommand */
        ChunkCommand: {
            /** Data Base64 */
            data_base64: string;
            /** Digest */
            digest: string;
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
        /** MediaValidation */
        MediaValidation: {
            /**
             * Validator
             * @default ffmpeg-full-decode-v1
             */
            validator: string;
            antivirus?: components["schemas"]["AntivirusReport"] | null;
            /** Duration Ms */
            duration_ms: number;
            /** Audio Codec */
            audio_codec: string;
            /** Sample Rate */
            sample_rate: number;
            /** Channels */
            channels: number;
            /** Video Codec */
            video_codec?: string | null;
            /** Width */
            width?: number | null;
            /** Height */
            height?: number | null;
        };
        /** PlaybackReply */
        PlaybackReply: {
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
            requester: "evaluation";
            /**
             * Issued At
             * Format: date-time
             */
            issued_at: string;
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
            /**
             * Purpose
             * @default rubric-evidence
             * @constant
             */
            purpose: "rubric-evidence";
            /**
             * Format
             * @enum {string}
             */
            format: "code" | "sql" | "voice" | "vcv" | "whiteboard";
            /** Snapshot Version */
            snapshot_version: number;
            /** Digest */
            digest: string;
            /** Number */
            number: number;
            /** Allowed */
            allowed: boolean;
            /** Data Base64 */
            data_base64?: string | null;
            /** Chunk Digest */
            chunk_digest?: string | null;
            /** Total Size */
            total_size?: number | null;
        };
        /** PlaybackRequest */
        PlaybackRequest: {
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
            requester: "evaluation";
            /**
             * Issued At
             * Format: date-time
             */
            issued_at: string;
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
            /**
             * Purpose
             * @default rubric-evidence
             * @constant
             */
            purpose: "rubric-evidence";
            /**
             * Format
             * @enum {string}
             */
            format: "code" | "sql" | "voice" | "vcv" | "whiteboard";
            /** Snapshot Version */
            snapshot_version: number;
            /** Digest */
            digest: string;
            /** Number */
            number: number;
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
        /** RecordingAdmission */
        RecordingAdmission: {
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
             * Recording Consent Id
             * Format: uuid
             */
            recording_consent_id: string;
        };
        /** RecordingCreate */
        RecordingCreate: {
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
             * Recording Consent Id
             * Format: uuid
             */
            recording_consent_id: string;
            /**
             * Mime
             * @enum {string}
             */
            mime: "audio/webm" | "video/webm" | "audio/ogg" | "video/mp4";
            /** Size */
            size: number;
            /** Digest */
            digest: string;
            /** Client Duration Ms */
            client_duration_ms: number;
        };
        /** RecordingView */
        RecordingView: {
            /**
             * Recording Id
             * Format: uuid
             */
            recording_id: string;
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
             * Format
             * @enum {string}
             */
            format: "voice" | "vcv";
            /** Mime */
            mime: string;
            /** Size */
            size: number;
            /** Digest */
            digest: string;
            /**
             * Chunk Bytes
             * @default 262144
             */
            chunk_bytes: number;
            /** Received Chunks */
            received_chunks: number[];
            /**
             * Status
             * @enum {string}
             */
            status: "uploading" | "finalized";
            /** Version */
            version: number;
            /** Snapshot Id */
            snapshot_id: string | null;
            /** Client Duration Ms */
            client_duration_ms: number;
            validation?: components["schemas"]["MediaValidation"] | null;
            /**
             * Timestamps Trusted
             * @default false
             * @constant
             */
            timestamps_trusted: false;
            /**
             * Created At
             * Format: date-time
             */
            created_at: string;
            /** Finalized At */
            finalized_at: string | null;
            /**
             * Demo
             * @default true
             * @constant
             */
            demo: true;
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
        /** SnapshotReceipt */
        SnapshotReceipt: {
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
            requester: "assessment";
            /**
             * Issued At
             * Format: date-time
             */
            issued_at: string;
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
            /** Format */
            format?: ("code" | "sql" | "voice" | "vcv" | "whiteboard") | null;
            /** Snapshot Version */
            snapshot_version?: number | null;
            /** Digest */
            digest?: string | null;
        };
        /** SnapshotRequest */
        SnapshotRequest: {
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
            requester: "assessment";
            /**
             * Issued At
             * Format: date-time
             */
            issued_at: string;
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
        /** TranscriptDocument */
        TranscriptDocument: {
            /** Duration Ms */
            duration_ms: number;
            /** Language */
            language: string;
            /** Segments */
            segments: components["schemas"]["Segment"][];
        };
        /** TranscriptionView */
        TranscriptionView: {
            /**
             * Attempt Id
             * Format: uuid
             */
            attempt_id: string;
            /** Number */
            number: number;
            /**
             * Status
             * @enum {string}
             */
            status: "pending" | "running" | "ready" | "technical_failure" | "interrupted" | "blocked";
            /** Model */
            model: string | null;
            /** Cost Microusd */
            cost_microusd: number | null;
            /** Transcript Id */
            transcript_id: string | null;
            /** Transcript Digest */
            transcript_digest: string | null;
            document: components["schemas"]["TranscriptDocument"] | null;
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
    practical_ui_v1_environment_js_get: {
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
                content?: never;
            };
        };
    };
    snapshot_receipt_internal_v1_practical_receipt_post: {
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
                "application/json": components["schemas"]["SnapshotRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SnapshotReceipt"];
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
    artifact_internal_v1_evaluation_artifact_post: {
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
                "application/json": components["schemas"]["ArtifactRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ArtifactReceipt"];
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
    get_transcription_v1_recordings__recording_id__transcription_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                recording_id: string;
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
                    "application/json": components["schemas"]["TranscriptionView"];
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
    request_transcription_v1_recordings__recording_id__transcription_post: {
        parameters: {
            query?: never;
            header: {
                "Idempotency-Key": string;
            };
            path: {
                recording_id: string;
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
                    "application/json": components["schemas"]["TranscriptionView"];
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
    interrupt_v1_recordings__recording_id__transcription__attempt_id__interrupt_post: {
        parameters: {
            query?: never;
            header: {
                "Idempotency-Key": string;
            };
            path: {
                recording_id: string;
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
                    "application/json": components["schemas"]["TranscriptionView"];
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
    playback_internal_v1_recording_playback_post: {
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
                "application/json": components["schemas"]["PlaybackRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PlaybackReply"];
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
    recording_admission_v1_recordings_admission_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["RecordingAdmission"];
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
    create_v1_recordings_post: {
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
                "application/json": components["schemas"]["RecordingCreate"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["RecordingView"];
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
    get_recording_v1_recordings__recording_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                recording_id: string;
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
                    "application/json": components["schemas"]["RecordingView"];
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
    upload_v1_recordings__recording_id__chunks__number__put: {
        parameters: {
            query?: never;
            header: {
                "Idempotency-Key": string;
                "If-Match": string;
            };
            path: {
                recording_id: string;
                number: number;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ChunkCommand"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["RecordingView"];
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
    restart_v1_recordings__recording_id__restart_post: {
        parameters: {
            query?: never;
            header: {
                "Idempotency-Key": string;
                "If-Match": string;
            };
            path: {
                recording_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["RecordingCreate"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["RecordingView"];
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
    finalize_v1_recordings__recording_id__finalize_post: {
        parameters: {
            query?: never;
            header: {
                "Idempotency-Key": string;
                "If-Match": string;
            };
            path: {
                recording_id: string;
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
                    "application/json": components["schemas"]["RecordingView"];
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
    content_v1_recordings__recording_id__content_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                recording_id: string;
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
