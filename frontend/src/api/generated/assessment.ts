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
    "/v1/content-families": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Create Family */
        post: operations["create_family_v1_content_families_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/content-families/{family_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Family */
        get: operations["get_family_v1_content_families__family_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/content-families/{family_id}/versions": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** New Version */
        post: operations["new_version_v1_content_families__family_id__versions_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/content-versions/{revision_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Revision */
        get: operations["get_revision_v1_content_versions__revision_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/content-versions/{revision_id}/publish": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Publish */
        post: operations["publish_v1_content_versions__revision_id__publish_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/content-versions/{revision_id}/retire": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Retire */
        post: operations["retire_v1_content_versions__revision_id__retire_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/assessment-selection-policies": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Selection Offers */
        get: operations["selection_offers_v1_assessment_selection_policies_get"];
        put?: never;
        /** Create Policy */
        post: operations["create_policy_v1_assessment_selection_policies_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/assessment-selection-policies/{policy_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Selection Policy */
        get: operations["get_selection_policy_v1_assessment_selection_policies__policy_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/assessment-variant-templates/{template_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Variant Template */
        get: operations["get_variant_template_v1_assessment_variant_templates__template_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/assessment-selection-policies/{policy_id}/publish": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Publish Policy */
        post: operations["publish_policy_v1_assessment_selection_policies__policy_id__publish_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/assessment-selection-policies/{policy_id}/retire": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Retire Policy */
        post: operations["retire_policy_v1_assessment_selection_policies__policy_id__retire_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/assessment-variant-templates": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Create Template */
        post: operations["create_template_v1_assessment_variant_templates_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/assessment-variant-templates/{template_id}/publish": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Publish Template */
        post: operations["publish_template_v1_assessment_variant_templates__template_id__publish_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/assessment-variant-templates/{template_id}/retire": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Retire Template */
        post: operations["retire_template_v1_assessment_variant_templates__template_id__retire_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/assessment-variant-templates/{template_id}/generate": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Generate */
        post: operations["generate_v1_assessment_variant_templates__template_id__generate_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/assessment-selected-sessions": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Selected Session */
        post: operations["selected_session_v1_assessment_selected_sessions_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/assessment-task-history": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Task History */
        get: operations["task_history_v1_assessment_task_history_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/company-task-proposals": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Proposals */
        get: operations["list_proposals_v1_company_task_proposals_get"];
        put?: never;
        /** Create */
        post: operations["create_v1_company_task_proposals_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/company-task-proposals/{proposal_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Proposal */
        get: operations["get_proposal_v1_company_task_proposals__proposal_id__get"];
        /** Update Proposal */
        put: operations["update_proposal_v1_company_task_proposals__proposal_id__put"];
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/company-task-proposals/{proposal_id}/submit": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Submit */
        post: operations["submit_v1_company_task_proposals__proposal_id__submit_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/company-task-proposals/{proposal_id}/review": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Review */
        post: operations["review_v1_company_task_proposals__proposal_id__review_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/company-task-proposals/{proposal_id}/withdraw": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Withdraw */
        post: operations["withdraw_v1_company_task_proposals__proposal_id__withdraw_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/company-assignments": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Assignments */
        get: operations["list_assignments_v1_company_assignments_get"];
        put?: never;
        /** Assign */
        post: operations["assign_v1_company_assignments_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/company-assignments/{assignment_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Assignment */
        get: operations["get_assignment_v1_company_assignments__assignment_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/company-assignments/{assignment_id}/accept": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Accept */
        post: operations["accept_v1_company_assignments__assignment_id__accept_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/company-assignments/{assignment_id}/decline": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Decline */
        post: operations["decline_v1_company_assignments__assignment_id__decline_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/company-assignments/{assignment_id}/revoke": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Revoke */
        post: operations["revoke_v1_company_assignments__assignment_id__revoke_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/company-assignments/{assignment_id}/result": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Result */
        get: operations["result_v1_company_assignments__assignment_id__result_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/company-assignments/{assignment_id}/complete": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Complete */
        post: operations["complete_v1_company_assignments__assignment_id__complete_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/company-task-subscriptions": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Subscriptions */
        get: operations["list_subscriptions_v1_company_task_subscriptions_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/company-task-subscriptions/{organization_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Subscription */
        get: operations["get_subscription_v1_company_task_subscriptions__organization_id__get"];
        /** Set Subscription */
        put: operations["set_subscription_v1_company_task_subscriptions__organization_id__put"];
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/company-task-schedules": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Schedules */
        get: operations["list_schedules_v1_company_task_schedules_get"];
        put?: never;
        /** Create Schedule */
        post: operations["create_schedule_v1_company_task_schedules_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/company-task-schedules/{schedule_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Schedule */
        get: operations["get_schedule_v1_company_task_schedules__schedule_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/company-task-schedules/{schedule_id}/cancel": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Cancel Schedule */
        post: operations["cancel_schedule_v1_company_task_schedules__schedule_id__cancel_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/company-task-schedules/{schedule_id}/jobs": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Jobs */
        get: operations["jobs_v1_company_task_schedules__schedule_id__jobs_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/internal/v1/market/company-notice": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Company Notice */
        post: operations["company_notice_internal_v1_market_company_notice_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/assessment-plans": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Plans */
        get: operations["list_plans_v1_assessment_plans_get"];
        put?: never;
        /** Create Plan */
        post: operations["create_plan_v1_assessment_plans_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/assessment-plans/{plan_version_id}/retire": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Retire Plan */
        post: operations["retire_plan_v1_assessment_plans__plan_version_id__retire_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/assessment-sessions": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Create Session */
        post: operations["create_session_v1_assessment_sessions_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/assessment-sessions/{session_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Session */
        get: operations["get_session_v1_assessment_sessions__session_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/assessment-sessions/{session_id}/cancel": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Cancel Session */
        post: operations["cancel_session_v1_assessment_sessions__session_id__cancel_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/review-sla/availability": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        /** Available */
        put: operations["available_v1_review_sla_availability_put"];
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/review-sla/inbox": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Inbox */
        get: operations["inbox_v1_review_sla_inbox_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/grade-policies": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Create Policy */
        post: operations["create_policy_v1_grade_policies_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/grade-policies/{policy_id}/approve": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Approve Policy */
        post: operations["approve_policy_v1_grade_policies__policy_id__approve_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/assessment-sessions/{session_id}/evaluation": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Evaluation */
        get: operations["get_evaluation_v1_assessment_sessions__session_id__evaluation_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/assessment-grade-reviews/{session_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Grade Review */
        get: operations["grade_review_v1_assessment_grade_reviews__session_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/assessment-grade-reviews/{session_id}/decisions": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Decide Grade */
        post: operations["decide_grade_v1_assessment_grade_reviews__session_id__decisions_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/grade-policies/{policy_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Policy */
        get: operations["get_policy_v1_grade_policies__policy_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/grade-policies/{policy_id}/retire": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Retire Policy */
        post: operations["retire_policy_v1_grade_policies__policy_id__retire_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/internal/v1/market/appeal-notice": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Notice Permission */
        post: operations["notice_permission_internal_v1_market_appeal_notice_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/assessment-appeals": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Own List */
        get: operations["own_list_v1_assessment_appeals_get"];
        put?: never;
        /** Submit */
        post: operations["submit_v1_assessment_appeals_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/assessment-appeals/queue": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Queue */
        get: operations["queue_v1_assessment_appeals_queue_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/assessment-appeals/{appeal_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get */
        get: operations["get_v1_assessment_appeals__appeal_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/assessment-appeals/{appeal_id}/claim": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Claim */
        post: operations["claim_v1_assessment_appeals__appeal_id__claim_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/assessment-appeals/{appeal_id}/withdraw": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Withdraw */
        post: operations["withdraw_v1_assessment_appeals__appeal_id__withdraw_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/assessment-appeals/{appeal_id}/evidence": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Workspace */
        get: operations["workspace_v1_assessment_appeals__appeal_id__evidence_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/assessment-appeals/{appeal_id}/resolve": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Resolve */
        post: operations["resolve_v1_assessment_appeals__appeal_id__resolve_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/assessment-appeals/{appeal_id}/history": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** History */
        get: operations["history_v1_assessment_appeals__appeal_id__history_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/internal/v1/confirmed-grade": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Confirmed Grade */
        post: operations["confirmed_grade_internal_v1_confirmed_grade_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/internal/v1/submitted-tests": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Submitted Tests */
        post: operations["submitted_tests_internal_v1_submitted_tests_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/internal/v1/suite-validation-verdict": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Receive */
        post: operations["receive_internal_v1_suite_validation_verdict_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/test-suites/{suite_id}/validations/{validation_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get */
        get: operations["get_v1_test_suites__suite_id__validations__validation_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/test-suites/{suite_id}/validations/{validation_id}/runtime-admission": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Runtime Admission */
        get: operations["runtime_admission_v1_test_suites__suite_id__validations__validation_id__runtime_admission_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/internal/v1/suite-validation-admission": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Admit */
        post: operations["admit_internal_v1_suite_validation_admission_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/internal/v1/suite-validation-material": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Material */
        post: operations["material_internal_v1_suite_validation_material_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/content-versions/{revision_id}/tasks/{task_key}/test-suites": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Create */
        post: operations["create_v1_content_versions__revision_id__tasks__task_key__test_suites_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/test-suites/{suite_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get */
        get: operations["get_v1_test_suites__suite_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/test-suites/{suite_id}/review": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Review */
        post: operations["review_v1_test_suites__suite_id__review_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/test-suites/{suite_id}/retire": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Retire */
        post: operations["retire_v1_test_suites__suite_id__retire_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/internal/v1/evaluation-material": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Evaluation Material */
        post: operations["evaluation_material_internal_v1_evaluation_material_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/internal/v1/evaluation-artifact-admission": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Artifact Admission */
        post: operations["artifact_admission_internal_v1_evaluation_artifact_admission_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/assessment-sessions/{session_id}/start": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Start Session */
        post: operations["start_session_v1_assessment_sessions__session_id__start_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/assessment-sessions/{session_id}/stages/{stage_id}/start": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Start Stage */
        post: operations["start_stage_v1_assessment_sessions__session_id__stages__stage_id__start_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/assessment-sessions/{session_id}/stages/{stage_id}/submit": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Submit Stage */
        post: operations["submit_stage_v1_assessment_sessions__session_id__stages__stage_id__submit_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/internal/v1/workspace-stage": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Workspace Stage */
        post: operations["workspace_stage_internal_v1_workspace_stage_post"];
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
        /** Acceptance */
        Acceptance: {
            /**
             * Assessment Consent Id
             * Format: uuid
             */
            assessment_consent_id: string;
            /**
             * Result Grant Id
             * Format: uuid
             */
            result_grant_id: string;
        };
        /** AppealCreate */
        AppealCreate: {
            /**
             * Decision Id
             * Format: uuid
             */
            decision_id: string;
            /** Reason */
            reason: string;
        };
        /** AppealEvidence */
        AppealEvidence: {
            /**
             * Appeal Id
             * Format: uuid
             */
            appeal_id: string;
            original: components["schemas"]["SessionEvidence"];
            current: components["schemas"]["SessionEvidence"];
            /** Evidence Digest */
            evidence_digest: string;
            /** Score */
            score: number | null;
            /** Competency Scores */
            competency_scores: {
                [key: string]: number;
            };
            /**
             * Recommended Status
             * @enum {string}
             */
            recommended_status: "confirmed" | "rejected" | "technical_failure";
            /** Repeated Review Complete */
            repeated_review_complete: boolean;
        };
        /** AppealResolution */
        AppealResolution: {
            /**
             * Action
             * @enum {string}
             */
            action: "uphold" | "change";
            /**
             * Status
             * @enum {string}
             */
            status: "confirmed" | "rejected" | "technical_failure";
            /** Evidence Digest */
            evidence_digest: string;
            /** Reason */
            reason: string;
        };
        /** AppealView */
        AppealView: {
            /**
             * Appeal Id
             * Format: uuid
             */
            appeal_id: string;
            /**
             * Session Id
             * Format: uuid
             */
            session_id: string;
            /**
             * Decision Id
             * Format: uuid
             */
            decision_id: string;
            /**
             * Candidate Id
             * Format: uuid
             */
            candidate_id: string;
            /** Reason */
            reason: string;
            /**
             * Status
             * @enum {string}
             */
            status: "submitted" | "in_review" | "resolved" | "withdrawn";
            /** Version */
            version: number;
            /** Reviewer Id */
            reviewer_id: string | null;
            /**
             * Submitted At
             * Format: date-time
             */
            submitted_at: string;
            /**
             * Filing Deadline
             * Format: date-time
             */
            filing_deadline: string;
            /**
             * Review Due At
             * Format: date-time
             */
            review_due_at: string;
            /** Overdue */
            overdue: boolean;
            /** Resolution */
            resolution: {
                [key: string]: unknown;
            } | null;
        };
        /** ArtifactPermit */
        ArtifactPermit: {
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
            requester: "coding-workspace" | "media" | "whiteboard";
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
        };
        /** ArtifactPermitRequest */
        ArtifactPermitRequest: {
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
            requester: "coding-workspace" | "media" | "whiteboard";
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
        /** AssignmentCommand */
        AssignmentCommand: {
            /**
             * Organization Id
             * Format: uuid
             */
            organization_id: string;
            /**
             * Candidate Id
             * Format: uuid
             */
            candidate_id: string;
            /**
             * Proposal Id
             * Format: uuid
             */
            proposal_id: string;
            /**
             * Plan Version Id
             * Format: uuid
             */
            plan_version_id: string;
            /**
             * Expires In Days
             * @default 14
             */
            expires_in_days: number;
        };
        /** AssignmentResult */
        AssignmentResult: {
            /**
             * Assignment Id
             * Format: uuid
             */
            assignment_id: string;
            /**
             * Session Id
             * Format: uuid
             */
            session_id: string;
            /**
             * Organization Id
             * Format: uuid
             */
            organization_id: string;
            /**
             * Status
             * @enum {string}
             */
            status: "review_pending" | "reviewed";
            /** Stages */
            stages: components["schemas"]["ResultStage"][];
            /**
             * Affects General Grade
             * @default false
             * @constant
             */
            affects_general_grade: false;
        };
        /** AssignmentView */
        AssignmentView: {
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
             * Candidate Id
             * Format: uuid
             */
            candidate_id: string;
            /**
             * Proposal Id
             * Format: uuid
             */
            proposal_id: string;
            /**
             * Plan Version Id
             * Format: uuid
             */
            plan_version_id: string;
            /** Session Id */
            session_id: string | null;
            /**
             * Status
             * @enum {string}
             */
            status: "assigned" | "accepted" | "declined" | "revoked" | "expired" | "cancelled" | "in_progress" | "submitted" | "completed";
            /** Version */
            version: number;
            /**
             * Expires At
             * Format: date-time
             */
            expires_at: string;
            /** Formats */
            formats: ("code" | "sql" | "voice" | "vcv" | "whiteboard")[];
            /** Duration Seconds */
            duration_seconds: number;
            /**
             * Result Recipient
             * Format: uuid
             */
            result_recipient: string;
            /**
             * Result Scope
             * @default reviewed_scores_only
             * @constant
             */
            result_scope: "reviewed_scores_only";
            /**
             * Affects General Grade
             * @default false
             * @constant
             */
            affects_general_grade: false;
            /**
             * Reveals Contacts
             * @default false
             * @constant
             */
            reveals_contacts: false;
        };
        /** CalibrationCase */
        CalibrationCase: {
            /**
             * Case Id
             * Format: uuid
             */
            case_id: string;
            /** Scores */
            scores: {
                [key: string]: number;
            };
            /** Labels */
            labels: components["schemas"]["ExpertLabel"][];
            /**
             * Holdout
             * @constant
             */
            holdout: true;
        };
        /** CalibrationData */
        CalibrationData: {
            /** Source Digest */
            source_digest: string;
            /**
             * Scoring Version
             * @constant
             */
            scoring_version: "competency-weighted-v1";
            /** Cases */
            cases: components["schemas"]["CalibrationCase"][];
            /** Reason */
            reason: string;
        };
        /** Competency */
        Competency: {
            /** Key */
            key: string;
            /** Description */
            description: string;
        };
        /** ContentPackage */
        ContentPackage: {
            /** Specialization */
            specialization: string;
            grade: components["schemas"]["Grade"];
            /** Source Dataset */
            source_dataset: string;
            /** Source Version */
            source_version: string;
            /**
             * Demo
             * @default true
             * @constant
             */
            demo: true;
            /** Competencies */
            competencies: components["schemas"]["Competency"][];
            /** Tasks */
            tasks: components["schemas"]["Task"][];
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
        /** DecisionCommand */
        DecisionCommand: {
            /**
             * Action
             * @enum {string}
             */
            action: "confirm" | "reject" | "technical_failure";
            /** Evidence Digest */
            evidence_digest?: string | null;
            /** Reason */
            reason: string;
        };
        /** DecisionReceipt */
        DecisionReceipt: {
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
             * @default candidate
             * @constant
             */
            requester: "candidate";
            /**
             * Issued At
             * Format: date-time
             */
            issued_at: string;
            /**
             * Purpose
             * @default confirmed-grade
             * @constant
             */
            purpose: "confirmed-grade";
            /**
             * Session Id
             * Format: uuid
             */
            session_id: string;
            /**
             * Decision Id
             * Format: uuid
             */
            decision_id: string;
            /**
             * Reviewer Id
             * Format: uuid
             */
            reviewer_id: string;
            /** Session Version */
            session_version: number;
            /** Allowed */
            allowed: boolean;
            decision?: components["schemas"]["DecisionSummary"] | null;
        };
        /** DecisionRequest */
        DecisionRequest: {
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
             * @default candidate
             * @constant
             */
            requester: "candidate";
            /**
             * Issued At
             * Format: date-time
             */
            issued_at: string;
            /**
             * Purpose
             * @default confirmed-grade
             * @constant
             */
            purpose: "confirmed-grade";
            /**
             * Session Id
             * Format: uuid
             */
            session_id: string;
            /**
             * Decision Id
             * Format: uuid
             */
            decision_id: string;
            /**
             * Reviewer Id
             * Format: uuid
             */
            reviewer_id: string;
            /** Session Version */
            session_version: number;
        };
        /** DecisionSummary */
        DecisionSummary: {
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
        /** ExpertLabel */
        ExpertLabel: {
            /**
             * Expert Id
             * Format: uuid
             */
            expert_id: string;
            /** Passed */
            passed: boolean;
        };
        /** FamilyCommand */
        FamilyCommand: {
            /** Name */
            name: string;
            content: components["schemas"]["ContentPackage"];
        };
        /** FamilyView */
        FamilyView: {
            /**
             * Family Id
             * Format: uuid
             */
            family_id: string;
            /** Name */
            name: string;
            /** Specialization */
            specialization: string;
            grade: components["schemas"]["Grade"];
            /** Version */
            version: number;
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
        /** FollowupLink */
        FollowupLink: {
            /**
             * Stage Id
             * Format: uuid
             */
            stage_id: string;
            /**
             * Parent Stage Id
             * Format: uuid
             */
            parent_stage_id: string;
            /** Available */
            available: boolean;
        };
        /** GenerateCommand */
        GenerateCommand: {
            /** Parameters */
            parameters: {
                [key: string]: string;
            };
            /** Family Version */
            family_version: number;
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
            /**
             * Session Id
             * Format: uuid
             */
            session_id: string;
            /**
             * Plan Version Id
             * Format: uuid
             */
            plan_version_id: string;
            /** Family Ids */
            family_ids: string[];
            /** Revision Ids */
            revision_ids: string[];
            /**
             * Issued At
             * Format: date-time
             */
            issued_at: string;
            /** Status */
            status: string;
        };
        /** IntakeView */
        IntakeView: {
            /**
             * Validation Id
             * Format: uuid
             */
            validation_id: string;
            /**
             * Suite Id
             * Format: uuid
             */
            suite_id: string;
            /**
             * Verdict
             * @enum {string}
             */
            verdict: "accepted" | "rejected";
            proof: components["schemas"]["SuiteVerdict"];
            /**
             * Received At
             * Format: date-time
             */
            received_at: string;
            /**
             * Signature Verified
             * @default true
             * @constant
             */
            signature_verified: true;
            /**
             * Runtime Validated
             * @default false
             * @constant
             */
            runtime_validated: false;
            /**
             * Scoring Enabled
             * @default false
             * @constant
             */
            scoring_enabled: false;
        };
        /** JobView */
        JobView: {
            /**
             * Job Id
             * Format: uuid
             */
            job_id: string;
            /** Kind */
            kind: string;
            /**
             * Status
             * @enum {string}
             */
            status: "pending" | "done" | "cancelled";
            /** Attempts */
            attempts: number;
            /**
             * Next At
             * Format: date-time
             */
            next_at: string;
            /** Error */
            error: ("permission_unavailable" | "evidence_pending" | "rate_limited") | null;
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
        /** MaterialReceipt */
        MaterialReceipt: {
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
            /** Allowed */
            allowed: boolean;
            material?: components["schemas"]["PinnedMaterial"] | null;
        };
        /** MaterialRequest */
        MaterialRequest: {
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
        };
        /** Mutant */
        Mutant: {
            /** Key */
            key: string;
            /** Description */
            description: string;
            source: components["schemas"]["FilesCommand"];
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
        /** PlanCommand */
        PlanCommand: {
            /** Name */
            name: string;
            /** Revision Ids */
            revision_ids: string[];
            /** Reason */
            reason: string;
            /** Test Suite Selections */
            test_suite_selections?: components["schemas"]["TaskSuiteSelection"][];
        };
        /** PlanView */
        PlanView: {
            /**
             * Plan Version Id
             * Format: uuid
             */
            plan_version_id: string;
            /** Name */
            name: string;
            /** Specialization */
            specialization: string;
            grade: components["schemas"]["Grade"];
            /** Duration Seconds */
            duration_seconds: number;
            /** Formats */
            formats: string[];
            /**
             * Demo
             * @default true
             * @constant
             */
            demo: true;
            /**
             * Status
             * @enum {string}
             */
            status: "published" | "retired";
            /** Version */
            version: number;
        };
        /** PolicyView */
        PolicyView: {
            /**
             * Plan Version Id
             * Format: uuid
             */
            plan_version_id: string;
            rules: components["schemas"]["Rules"];
            /**
             * Policy Id
             * Format: uuid
             */
            policy_id: string;
            /**
             * Status
             * @enum {string}
             */
            status: "draft" | "approved" | "retired";
            /** Version */
            version: number;
            /** Calibrated */
            calibrated: boolean;
            calibration?: components["schemas"]["CalibrationData"] | null;
            /** Retirement Reason */
            retirement_reason?: string | null;
            /**
             * Demo
             * @default true
             * @constant
             */
            demo: true;
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
        /** ProposalCommand */
        ProposalCommand: {
            /**
             * Organization Id
             * Format: uuid
             */
            organization_id: string;
            /** Name */
            name: string;
            content: components["schemas"]["ContentPackage"];
        };
        /** ProposalReview */
        ProposalReview: {
            /**
             * Outcome
             * @enum {string}
             */
            outcome: "approve" | "reject";
            /** Digest */
            digest: string;
            /** Reason */
            reason: string;
        };
        /** ProposalSummary */
        ProposalSummary: {
            /**
             * Proposal Id
             * Format: uuid
             */
            proposal_id: string;
            /**
             * Organization Id
             * Format: uuid
             */
            organization_id: string;
            /** Name */
            name: string;
            /**
             * Status
             * @enum {string}
             */
            status: "draft" | "submitted" | "approved" | "rejected" | "withdrawn";
            /** Version */
            version: number;
            /** Digest */
            digest: string;
        };
        /** ProposalView */
        ProposalView: {
            /**
             * Organization Id
             * Format: uuid
             */
            organization_id: string;
            /** Name */
            name: string;
            content: components["schemas"]["ContentPackage"];
            /**
             * Proposal Id
             * Format: uuid
             */
            proposal_id: string;
            /** Digest */
            digest: string;
            /**
             * Status
             * @enum {string}
             */
            status: "draft" | "submitted" | "approved" | "rejected" | "withdrawn";
            /** Version */
            version: number;
            /** Revision Id */
            revision_id: string | null;
            /** Bank Status */
            bank_status: ("draft" | "published" | "retired") | null;
            /** Review Reason */
            review_reason: string | null;
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
        /** ReasonCommand */
        ReasonCommand: {
            /** Reason */
            reason: string;
        };
        /** ResultCriterion */
        ResultCriterion: {
            /** Criterion Key */
            criterion_key: string;
            /** Competency */
            competency: string;
            /** Points */
            points: number;
            /** Max Points */
            max_points: number;
        };
        /** ResultStage */
        ResultStage: {
            /**
             * Stage Id
             * Format: uuid
             */
            stage_id: string;
            /**
             * Format
             * @enum {string}
             */
            format: "code" | "sql" | "voice" | "vcv" | "whiteboard";
            /** Score */
            score: number;
            /**
             * Review Id
             * Format: uuid
             */
            review_id: string;
            /** Criteria */
            criteria: components["schemas"]["ResultCriterion"][];
        };
        /** RetirementCommand */
        RetirementCommand: {
            /** Reason */
            reason: string;
        };
        /** ReviewCommand */
        ReviewCommand: {
            /** Reason */
            reason: string;
        };
        /** ReviewView */
        ReviewView: {
            /**
             * Id
             * Format: uuid
             */
            id: string;
            /** Status */
            status: string;
            /** Version */
            version: number;
            /** Data */
            data: {
                [key: string]: unknown;
            };
        };
        /** RevisionView */
        RevisionView: {
            /**
             * Revision Id
             * Format: uuid
             */
            revision_id: string;
            /**
             * Family Id
             * Format: uuid
             */
            family_id: string;
            /** Number */
            number: number;
            content: components["schemas"]["ContentPackage"];
            /**
             * Status
             * @enum {string}
             */
            status: "draft" | "published" | "retired";
            /** Version */
            version: number;
            /**
             * Created At
             * Format: date-time
             */
            created_at: string;
            /** Published At */
            published_at: string | null;
            /** Retired At */
            retired_at: string | null;
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
        /** Rules */
        Rules: {
            /** Required Llm Model */
            required_llm_model?: string | null;
            /** Required Llm Prompt Digest */
            required_llm_prompt_digest?: string | null;
            /** Weights */
            weights: {
                [key: string]: number;
            };
            /** Minimums */
            minimums?: {
                [key: string]: number;
            };
            /** Pass Score */
            pass_score: number;
            /** Retry Seconds */
            retry_seconds: number;
            /**
             * Grade Change Seconds
             * @default 7776000
             */
            grade_change_seconds: number;
            /**
             * Minimum Validation Cases
             * @default 20
             */
            minimum_validation_cases: number;
            /**
             * Minimum Accuracy Percent
             * @default 80
             */
            minimum_accuracy_percent: number;
        };
        /** RuntimeAttestation */
        RuntimeAttestation: {
            /**
             * Version
             * @default 1
             * @constant
             */
            version: 1;
            /**
             * Producer
             * @default code-runner
             * @constant
             */
            producer: "code-runner";
            /**
             * Purpose
             * @default suite-runtime-attestation
             * @constant
             */
            purpose: "suite-runtime-attestation";
            /**
             * Validation Id
             * Format: uuid
             */
            validation_id: string;
            /**
             * Owner Id
             * Format: uuid
             */
            owner_id: string;
            /** Proof Digest */
            proof_digest: string;
            probe: components["schemas"]["ProbeRecord"];
            /**
             * Issued At
             * Format: date-time
             */
            issued_at: string;
        };
        /** RuntimeDecision */
        RuntimeDecision: {
            /**
             * Validation Id
             * Format: uuid
             */
            validation_id: string;
            /** Runtime Admitted */
            runtime_admitted: boolean;
            /**
             * Reason
             * @enum {string}
             */
            reason: "admitted" | "policy_missing" | "policy_expired" | "policy_not_yet_active" | "attestation_missing" | "attestation_expired" | "verdict_rejected" | "suite_inactive";
            /** Policy Id */
            policy_id?: string | null;
            /**
             * Demo
             * @default true
             * @constant
             */
            demo: true;
            /**
             * Scoring Enabled
             * @default false
             * @constant
             */
            scoring_enabled: false;
        };
        /** ScheduleCommand */
        ScheduleCommand: {
            /**
             * Organization Id
             * Format: uuid
             */
            organization_id: string;
            /**
             * Candidate Id
             * Format: uuid
             */
            candidate_id: string;
            /**
             * Proposal Id
             * Format: uuid
             */
            proposal_id: string;
            /**
             * Plan Version Id
             * Format: uuid
             */
            plan_version_id: string;
            /**
             * Expires In Days
             * @default 14
             */
            expires_in_days: number;
            /**
             * Starts At
             * Format: date-time
             */
            starts_at: string;
            /** Interval Seconds */
            interval_seconds?: number | null;
            /**
             * Max Occurrences
             * @default 1
             */
            max_occurrences: number;
        };
        /** ScheduleView */
        ScheduleView: {
            /**
             * Organization Id
             * Format: uuid
             */
            organization_id: string;
            /**
             * Candidate Id
             * Format: uuid
             */
            candidate_id: string;
            /**
             * Proposal Id
             * Format: uuid
             */
            proposal_id: string;
            /**
             * Plan Version Id
             * Format: uuid
             */
            plan_version_id: string;
            /**
             * Expires In Days
             * @default 14
             */
            expires_in_days: number;
            /**
             * Starts At
             * Format: date-time
             */
            starts_at: string;
            /** Interval Seconds */
            interval_seconds?: number | null;
            /**
             * Max Occurrences
             * @default 1
             */
            max_occurrences: number;
            /**
             * Schedule Id
             * Format: uuid
             */
            schedule_id: string;
            /**
             * Status
             * @enum {string}
             */
            status: "active" | "cancelled" | "completed";
            /** Issued Count */
            issued_count: number;
            /** Subscription Version */
            subscription_version: number;
            /** Version */
            version: number;
        };
        /** SelectedSessionCommand */
        SelectedSessionCommand: {
            /**
             * Selection Policy Id
             * Format: uuid
             */
            selection_policy_id: string;
            /**
             * Assessment Consent Id
             * Format: uuid
             */
            assessment_consent_id: string;
            /** Grade Policy Id */
            grade_policy_id?: string | null;
        };
        /** SelectionOffer */
        SelectionOffer: {
            /**
             * Policy Id
             * Format: uuid
             */
            policy_id: string;
            /** Name */
            name: string;
            /** Specialization */
            specialization: string;
            /** Grade */
            grade: string;
            /**
             * Demo
             * @default true
             */
            demo: boolean;
        };
        /** SelectionReceipt */
        SelectionReceipt: {
            /**
             * Policy Id
             * Format: uuid
             */
            policy_id: string;
            /** Policy Digest */
            policy_digest: string;
        };
        /** SessionCommand */
        SessionCommand: {
            /**
             * Plan Version Id
             * Format: uuid
             */
            plan_version_id: string;
            /**
             * Assessment Consent Id
             * Format: uuid
             */
            assessment_consent_id: string;
            /** Grade Policy Id */
            grade_policy_id?: string | null;
        };
        /** SessionEvaluation */
        SessionEvaluation: {
            /**
             * Session Id
             * Format: uuid
             */
            session_id: string;
            /** Policy Id */
            policy_id: string | null;
            /**
             * Status
             * @enum {string}
             */
            status: "awaiting_calibration" | "awaiting_evidence" | "review_pending" | "confirmed" | "rejected" | "technical_failure";
            /** Score */
            score?: number | null;
            /** Competency Scores */
            competency_scores?: {
                [key: string]: number;
            };
            recommended_grade?: components["schemas"]["Grade"] | null;
            confirmed_grade?: components["schemas"]["Grade"] | null;
            /** Evidence Digest */
            evidence_digest?: string | null;
            /** Decision Id */
            decision_id?: string | null;
            /** Next Attempt At */
            next_attempt_at?: string | null;
            /** Grade Change Available At */
            grade_change_available_at?: string | null;
            /**
             * Demo
             * @default true
             * @constant
             */
            demo: true;
        };
        /** SessionEvidence */
        SessionEvidence: {
            /**
             * Session Id
             * Format: uuid
             */
            session_id: string;
            /**
             * Policy Id
             * Format: uuid
             */
            policy_id: string;
            /** Stages */
            stages: components["schemas"]["StageScore"][];
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
        /** SessionSummary */
        SessionSummary: {
            /**
             * Session Id
             * Format: uuid
             */
            session_id: string;
            /**
             * Plan Version Id
             * Format: uuid
             */
            plan_version_id: string;
            /**
             * Status
             * @enum {string}
             */
            status: "preflight" | "in_progress" | "submitted" | "cancelled" | "completed";
            /** Current Stage Id */
            current_stage_id?: string | null;
            /** Version */
            version: number;
            /**
             * Demo
             * @default true
             * @constant
             */
            demo: true;
        };
        /** SessionView */
        SessionView: {
            /**
             * Session Id
             * Format: uuid
             */
            session_id: string;
            /**
             * Plan Version Id
             * Format: uuid
             */
            plan_version_id: string;
            /**
             * Status
             * @enum {string}
             */
            status: "preflight" | "in_progress" | "submitted" | "cancelled" | "completed";
            /** Current Stage Id */
            current_stage_id?: string | null;
            /** Version */
            version: number;
            /**
             * Demo
             * @default true
             * @constant
             */
            demo: true;
            /** Stages */
            stages: components["schemas"]["StageView"][];
            /** Progress */
            progress?: components["schemas"]["StageProgress"][];
            /** Followups */
            followups?: components["schemas"]["FollowupLink"][];
            selection?: components["schemas"]["SelectionReceipt"] | null;
        };
        /** StageProgress */
        StageProgress: {
            /**
             * Stage Id
             * Format: uuid
             */
            stage_id: string;
            /**
             * Status
             * @enum {string}
             */
            status: "pending" | "active" | "submitted" | "cancelled";
            /** Version */
            version: number;
            /** Started At */
            started_at: string | null;
            /** Deadline */
            deadline: string | null;
            /** Submitted At */
            submitted_at: string | null;
            /** Workspace Id */
            workspace_id: string | null;
            /** Snapshot Id */
            snapshot_id: string | null;
            /** Snapshot Version */
            snapshot_version: number | null;
            /** Digest */
            digest: string | null;
        };
        /** StageRequest */
        StageRequest: {
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
            requester: "coding-workspace" | "media" | "whiteboard" | "proctoring";
            /**
             * Issued At
             * Format: date-time
             */
            issued_at: string;
            /**
             * Purpose
             * @default write
             * @enum {string}
             */
            purpose: "write" | "read";
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
        };
        /** StageScore */
        StageScore: {
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
        /** StageStatus */
        StageStatus: {
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
            requester: "coding-workspace" | "media" | "whiteboard" | "proctoring";
            /**
             * Issued At
             * Format: date-time
             */
            issued_at: string;
            /**
             * Purpose
             * @default write
             * @enum {string}
             */
            purpose: "write" | "read";
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
            /** Allowed */
            allowed: boolean;
            /** Format */
            format: ("code" | "sql" | "voice" | "vcv" | "whiteboard") | null;
        };
        /** StageView */
        StageView: {
            /**
             * Stage Id
             * Format: uuid
             */
            stage_id: string;
            /**
             * Revision Id
             * Format: uuid
             */
            revision_id: string;
            /** Task Key */
            task_key: string;
            /**
             * Format
             * @enum {string}
             */
            format: "code" | "sql" | "vcv" | "voice" | "whiteboard";
            /** Instruction */
            instruction: string;
            /** Duration Seconds */
            duration_seconds: number;
        };
        /** SubmissionCommand */
        SubmissionCommand: {
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
        /** SubmittedMaterial */
        SubmittedMaterial: {
            /**
             * Consent Id
             * Format: uuid
             */
            consent_id: string;
            /** Snapshot Version */
            snapshot_version: number;
            /** Snapshot Digest */
            snapshot_digest: string;
            binding: components["schemas"]["SessionSuitePin"];
            definition: components["schemas"]["SuiteDefinition"];
        };
        /** SubmittedReceipt */
        SubmittedReceipt: {
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
            requester: "code-runner" | "coding-workspace";
            /**
             * Issued At
             * Format: date-time
             */
            issued_at: string;
            /**
             * Purpose
             * @default submitted-tests
             * @constant
             */
            purpose: "submitted-tests";
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
             * Node Id
             * Format: uuid
             */
            node_id: string;
            /** Runtime Fingerprint */
            runtime_fingerprint: string;
            /** Allowed */
            allowed: boolean;
            material?: components["schemas"]["SubmittedMaterial"] | null;
        };
        /** SubmittedRequest */
        SubmittedRequest: {
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
            requester: "code-runner" | "coding-workspace";
            /**
             * Issued At
             * Format: date-time
             */
            issued_at: string;
            /**
             * Purpose
             * @default submitted-tests
             * @constant
             */
            purpose: "submitted-tests";
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
             * Node Id
             * Format: uuid
             */
            node_id: string;
            /** Runtime Fingerprint */
            runtime_fingerprint: string;
        };
        /** SubscriptionCommand */
        SubscriptionCommand: {
            /**
             * Status
             * @enum {string}
             */
            status: "active" | "declined" | "cancelled";
            /** Consent Id */
            consent_id?: string | null;
            /**
             * Min Interval Seconds
             * @default 604800
             */
            min_interval_seconds: number;
        };
        /** SubscriptionView */
        SubscriptionView: {
            /**
             * Status
             * @enum {string}
             */
            status: "active" | "declined" | "cancelled";
            /** Consent Id */
            consent_id?: string | null;
            /**
             * Min Interval Seconds
             * @default 604800
             */
            min_interval_seconds: number;
            /**
             * Organization Id
             * Format: uuid
             */
            organization_id: string;
            /** Version */
            version: number;
        };
        /** SuiteAdmissionRequest */
        SuiteAdmissionRequest: {
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
            requester: "code-runner";
            /**
             * Issued At
             * Format: date-time
             */
            issued_at: string;
            /**
             * Purpose
             * @constant
             */
            purpose: "suite-validation";
            /**
             * Validation Id
             * Format: uuid
             */
            validation_id: string;
            pin: components["schemas"]["SuitePin"];
            /** Plan Digest */
            plan_digest: string;
        };
        /** SuiteDefinition */
        SuiteDefinition: {
            /**
             * Format
             * @enum {string}
             */
            format: "code" | "sql";
            /**
             * Runtime Contract
             * @constant
             */
            runtime_contract: "python-3.12-sqlite-demo-v1";
            /**
             * Comparison Policy
             * @constant
             */
            comparison_policy: "utf8-exact-v1";
            /** Cases */
            cases: components["schemas"]["TestCase"][];
            reference: components["schemas"]["FilesCommand"];
            /** Mutants */
            mutants: components["schemas"]["Mutant"][];
        };
        /** SuiteMaterial */
        SuiteMaterial: {
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
            requester: "code-runner";
            /**
             * Issued At
             * Format: date-time
             */
            issued_at: string;
            /**
             * Purpose
             * @constant
             */
            purpose: "suite-validation-material";
            /**
             * Validation Id
             * Format: uuid
             */
            validation_id: string;
            pin: components["schemas"]["SuitePin"];
            /** Plan Digest */
            plan_digest: string;
            /** Allowed */
            allowed: boolean;
            definition?: components["schemas"]["SuiteDefinition"] | null;
        };
        /** SuiteMaterialRequest */
        SuiteMaterialRequest: {
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
            requester: "code-runner";
            /**
             * Issued At
             * Format: date-time
             */
            issued_at: string;
            /**
             * Purpose
             * @constant
             */
            purpose: "suite-validation-material";
            /**
             * Validation Id
             * Format: uuid
             */
            validation_id: string;
            pin: components["schemas"]["SuitePin"];
            /** Plan Digest */
            plan_digest: string;
        };
        /** SuitePermit */
        SuitePermit: {
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
            requester: "code-runner";
            /**
             * Issued At
             * Format: date-time
             */
            issued_at: string;
            /**
             * Purpose
             * @constant
             */
            purpose: "suite-validation";
            /**
             * Validation Id
             * Format: uuid
             */
            validation_id: string;
            pin: components["schemas"]["SuitePin"];
            /** Plan Digest */
            plan_digest: string;
            /** Allowed */
            allowed: boolean;
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
        /** SuiteVerdict */
        SuiteVerdict: {
            /**
             * Version
             * @default 1
             * @constant
             */
            version: 1;
            /**
             * Producer
             * @default code-runner
             * @constant
             */
            producer: "code-runner";
            /**
             * Purpose
             * @default suite-validation-verdict
             * @constant
             */
            purpose: "suite-validation-verdict";
            /**
             * Validation Id
             * Format: uuid
             */
            validation_id: string;
            /**
             * Owner Id
             * Format: uuid
             */
            owner_id: string;
            pin: components["schemas"]["SuitePin"];
            /** Plan Digest */
            plan_digest: string;
            /** Captures Digest */
            captures_digest: string;
            /** Captures Count */
            captures_count: number;
            /**
             * Verdict
             * @enum {string}
             */
            verdict: "accepted" | "rejected";
            /**
             * Completed At
             * Format: date-time
             */
            completed_at: string;
            /**
             * Demo
             * @default true
             * @constant
             */
            demo: true;
            /**
             * Scoring Enabled
             * @default false
             * @constant
             */
            scoring_enabled: false;
        };
        /** SuiteView */
        SuiteView: {
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
            /** Task Key */
            task_key: string;
            /** Number */
            number: number;
            definition: components["schemas"]["SuiteDefinition"];
            /** Definition Digest */
            definition_digest: string;
            /** Content Digest */
            content_digest: string;
            /** Source Dataset */
            source_dataset: string;
            /** Source Version */
            source_version: string;
            /**
             * Status
             * @enum {string}
             */
            status: "draft" | "reviewed" | "retired";
            /** Version */
            version: number;
            /**
             * Created At
             * Format: date-time
             */
            created_at: string;
            /**
             * Demo
             * @default true
             * @constant
             */
            demo: true;
            /**
             * Runtime Validated
             * @default false
             * @constant
             */
            runtime_validated: false;
            /**
             * Scoring Enabled
             * @default false
             * @constant
             */
            scoring_enabled: false;
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
        /** TaskSuiteSelection */
        TaskSuiteSelection: {
            /**
             * Revision Id
             * Format: uuid
             */
            revision_id: string;
            /** Task Key */
            task_key: string;
            /**
             * Suite Id
             * Format: uuid
             */
            suite_id: string;
            /**
             * Validation Id
             * Format: uuid
             */
            validation_id: string;
        };
        /** TemplateCommand */
        TemplateCommand: {
            /**
             * Base Revision Id
             * Format: uuid
             */
            base_revision_id: string;
            /** Allowed Parameters */
            allowed_parameters: {
                [key: string]: string[];
            };
        };
        /** TestCase */
        TestCase: {
            /** Key */
            key: string;
            /** Criterion Key */
            criterion_key: string;
            /** Fixtures */
            fixtures?: components["schemas"]["File"][];
            /** Expected Stdout */
            expected_stdout: string;
            /**
             * Expected Stderr
             * @default
             */
            expected_stderr: string;
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
        /** VerdictDelivery */
        VerdictDelivery: {
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
            requester: "code-runner";
            /**
             * Issued At
             * Format: date-time
             */
            issued_at: string;
            /**
             * Purpose
             * @constant
             */
            purpose: "suite-verdict-intake";
            proof: components["schemas"]["SuiteVerdict"];
            /** Proof Signature */
            proof_signature: string;
            attestation?: components["schemas"]["RuntimeAttestation"] | null;
            /** Attestation Signature */
            attestation_signature?: string | null;
        };
        /** VerdictReceipt */
        VerdictReceipt: {
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
            requester: "code-runner";
            /**
             * Issued At
             * Format: date-time
             */
            issued_at: string;
            /**
             * Purpose
             * @constant
             */
            purpose: "suite-verdict-intake";
            /**
             * Validation Id
             * Format: uuid
             */
            validation_id: string;
            /** Proof Digest */
            proof_digest: string;
            /** Attestation Digest */
            attestation_digest?: string | null;
            /** Allowed */
            allowed: boolean;
            /** Verdict */
            verdict?: ("accepted" | "rejected") | null;
            /**
             * Runtime Validated
             * @default false
             * @constant
             */
            runtime_validated: false;
            /**
             * Scoring Enabled
             * @default false
             * @constant
             */
            scoring_enabled: false;
        };
        /** WithdrawCommand */
        WithdrawCommand: {
            /** Reason */
            reason: string;
        };
        /** PolicyCommand */
        reverse_hr__domains__assessment_grades__PolicyCommand: {
            /**
             * Plan Version Id
             * Format: uuid
             */
            plan_version_id: string;
            rules: components["schemas"]["Rules"];
        };
        /** PolicyCommand */
        reverse_hr__domains__assessment_selection__PolicyCommand: {
            /** Name */
            name: string;
            /** Plan Version Ids */
            plan_version_ids: string[];
            /** Grade Policy Ids */
            grade_policy_ids?: {
                [key: string]: string;
            };
            /**
             * Family Cooldown Seconds
             * @default 86400
             */
            family_cooldown_seconds: number;
            /**
             * Variant Cooldown Seconds
             * @default 2592000
             */
            variant_cooldown_seconds: number;
            /**
             * Window Seconds
             * @default 2592000
             */
            window_seconds: number;
            /**
             * Family Candidate Limit
             * @default 2
             */
            family_candidate_limit: number;
            /**
             * Family Global Limit
             * @default 1000
             */
            family_global_limit: number;
            /**
             * Candidate Session Limit
             * @default 10
             */
            candidate_session_limit: number;
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
    create_family_v1_content_families_post: {
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
                "application/json": components["schemas"]["FamilyCommand"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["RevisionView"];
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
    get_family_v1_content_families__family_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                family_id: string;
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
                    "application/json": components["schemas"]["FamilyView"];
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
    new_version_v1_content_families__family_id__versions_post: {
        parameters: {
            query?: never;
            header: {
                "Idempotency-Key": string;
                "If-Match": string;
            };
            path: {
                family_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ContentPackage"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["RevisionView"];
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
    get_revision_v1_content_versions__revision_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                revision_id: string;
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
                    "application/json": components["schemas"]["RevisionView"];
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
    publish_v1_content_versions__revision_id__publish_post: {
        parameters: {
            query?: never;
            header: {
                "Idempotency-Key": string;
                "If-Match": string;
            };
            path: {
                revision_id: string;
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
                    "application/json": components["schemas"]["RevisionView"];
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
    retire_v1_content_versions__revision_id__retire_post: {
        parameters: {
            query?: never;
            header: {
                "Idempotency-Key": string;
                "If-Match": string;
            };
            path: {
                revision_id: string;
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
                    "application/json": components["schemas"]["RevisionView"];
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
    selection_offers_v1_assessment_selection_policies_get: {
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
                    "application/json": components["schemas"]["SelectionOffer"][];
                };
            };
        };
    };
    create_policy_v1_assessment_selection_policies_post: {
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
                "application/json": components["schemas"]["reverse_hr__domains__assessment_selection__PolicyCommand"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ReviewView"];
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
    get_selection_policy_v1_assessment_selection_policies__policy_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                policy_id: string;
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
                    "application/json": components["schemas"]["ReviewView"];
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
    get_variant_template_v1_assessment_variant_templates__template_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                template_id: string;
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
                    "application/json": components["schemas"]["ReviewView"];
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
    publish_policy_v1_assessment_selection_policies__policy_id__publish_post: {
        parameters: {
            query?: never;
            header: {
                "Idempotency-Key": string;
                "If-Match": string;
            };
            path: {
                policy_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ReasonCommand"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ReviewView"];
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
    retire_policy_v1_assessment_selection_policies__policy_id__retire_post: {
        parameters: {
            query?: never;
            header: {
                "Idempotency-Key": string;
                "If-Match": string;
            };
            path: {
                policy_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ReasonCommand"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ReviewView"];
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
    create_template_v1_assessment_variant_templates_post: {
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
                "application/json": components["schemas"]["TemplateCommand"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ReviewView"];
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
    publish_template_v1_assessment_variant_templates__template_id__publish_post: {
        parameters: {
            query?: never;
            header: {
                "Idempotency-Key": string;
                "If-Match": string;
            };
            path: {
                template_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ReasonCommand"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ReviewView"];
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
    retire_template_v1_assessment_variant_templates__template_id__retire_post: {
        parameters: {
            query?: never;
            header: {
                "Idempotency-Key": string;
                "If-Match": string;
            };
            path: {
                template_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ReasonCommand"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ReviewView"];
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
    generate_v1_assessment_variant_templates__template_id__generate_post: {
        parameters: {
            query?: never;
            header: {
                "Idempotency-Key": string;
            };
            path: {
                template_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["GenerateCommand"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["RevisionView"];
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
    selected_session_v1_assessment_selected_sessions_post: {
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
                "application/json": components["schemas"]["SelectedSessionCommand"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SessionView"];
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
    task_history_v1_assessment_task_history_get: {
        parameters: {
            query?: {
                after?: string | null;
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
                    "application/json": components["schemas"]["HistoryItem"][];
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
    list_proposals_v1_company_task_proposals_get: {
        parameters: {
            query?: {
                organization_id?: string | null;
                status?: ("draft" | "submitted" | "approved" | "rejected" | "withdrawn") | null;
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
                    "application/json": components["schemas"]["ProposalSummary"][];
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
    create_v1_company_task_proposals_post: {
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
                "application/json": components["schemas"]["ProposalCommand"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProposalView"];
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
    get_proposal_v1_company_task_proposals__proposal_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                proposal_id: string;
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
                    "application/json": components["schemas"]["ProposalView"];
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
    update_proposal_v1_company_task_proposals__proposal_id__put: {
        parameters: {
            query?: never;
            header: {
                "Idempotency-Key": string;
                "If-Match": string;
            };
            path: {
                proposal_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ProposalCommand"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProposalView"];
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
    submit_v1_company_task_proposals__proposal_id__submit_post: {
        parameters: {
            query?: never;
            header: {
                "Idempotency-Key": string;
                "If-Match": string;
            };
            path: {
                proposal_id: string;
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
                    "application/json": components["schemas"]["ProposalView"];
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
    review_v1_company_task_proposals__proposal_id__review_post: {
        parameters: {
            query?: never;
            header: {
                "Idempotency-Key": string;
                "If-Match": string;
            };
            path: {
                proposal_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ProposalReview"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProposalView"];
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
    withdraw_v1_company_task_proposals__proposal_id__withdraw_post: {
        parameters: {
            query?: never;
            header: {
                "Idempotency-Key": string;
                "If-Match": string;
            };
            path: {
                proposal_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["WithdrawCommand"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProposalView"];
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
    list_assignments_v1_company_assignments_get: {
        parameters: {
            query?: {
                organization_id?: string | null;
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
                    "application/json": components["schemas"]["AssignmentView"][];
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
    assign_v1_company_assignments_post: {
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
                "application/json": components["schemas"]["AssignmentCommand"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AssignmentView"];
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
    get_assignment_v1_company_assignments__assignment_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                assignment_id: string;
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
                    "application/json": components["schemas"]["AssignmentView"];
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
    accept_v1_company_assignments__assignment_id__accept_post: {
        parameters: {
            query?: never;
            header: {
                "Idempotency-Key": string;
                "If-Match": string;
            };
            path: {
                assignment_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["Acceptance"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SessionView"];
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
    decline_v1_company_assignments__assignment_id__decline_post: {
        parameters: {
            query?: never;
            header: {
                "Idempotency-Key": string;
                "If-Match": string;
            };
            path: {
                assignment_id: string;
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
                    "application/json": components["schemas"]["AssignmentView"];
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
    revoke_v1_company_assignments__assignment_id__revoke_post: {
        parameters: {
            query?: never;
            header: {
                "Idempotency-Key": string;
                "If-Match": string;
            };
            path: {
                assignment_id: string;
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
                    "application/json": components["schemas"]["AssignmentView"];
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
    result_v1_company_assignments__assignment_id__result_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                assignment_id: string;
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
                    "application/json": components["schemas"]["AssignmentResult"];
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
    complete_v1_company_assignments__assignment_id__complete_post: {
        parameters: {
            query?: never;
            header: {
                "Idempotency-Key": string;
                "If-Match": string;
            };
            path: {
                assignment_id: string;
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
                    "application/json": components["schemas"]["AssignmentView"];
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
    list_subscriptions_v1_company_task_subscriptions_get: {
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
                    "application/json": components["schemas"]["SubscriptionView"][];
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
    get_subscription_v1_company_task_subscriptions__organization_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                organization_id: string;
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
                    "application/json": components["schemas"]["SubscriptionView"];
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
    set_subscription_v1_company_task_subscriptions__organization_id__put: {
        parameters: {
            query?: never;
            header: {
                "Idempotency-Key": string;
                "If-Match": string;
            };
            path: {
                organization_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["SubscriptionCommand"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SubscriptionView"];
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
    list_schedules_v1_company_task_schedules_get: {
        parameters: {
            query?: {
                organization_id?: string | null;
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
                    "application/json": components["schemas"]["ScheduleView"][];
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
    create_schedule_v1_company_task_schedules_post: {
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
                "application/json": components["schemas"]["ScheduleCommand"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ScheduleView"];
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
    get_schedule_v1_company_task_schedules__schedule_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                schedule_id: string;
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
                    "application/json": components["schemas"]["ScheduleView"];
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
    cancel_schedule_v1_company_task_schedules__schedule_id__cancel_post: {
        parameters: {
            query?: never;
            header: {
                "Idempotency-Key": string;
                "If-Match": string;
            };
            path: {
                schedule_id: string;
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
                    "application/json": components["schemas"]["ScheduleView"];
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
    jobs_v1_company_task_schedules__schedule_id__jobs_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                schedule_id: string;
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
                    "application/json": components["schemas"]["JobView"][];
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
    company_notice_internal_v1_market_company_notice_post: {
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
    list_plans_v1_assessment_plans_get: {
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
                    "application/json": components["schemas"]["PlanView"][];
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
    create_plan_v1_assessment_plans_post: {
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
                "application/json": components["schemas"]["PlanCommand"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PlanView"];
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
    retire_plan_v1_assessment_plans__plan_version_id__retire_post: {
        parameters: {
            query?: never;
            header: {
                "Idempotency-Key": string;
                "If-Match": string;
            };
            path: {
                plan_version_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ReasonCommand"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PlanView"];
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
    create_session_v1_assessment_sessions_post: {
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
                "application/json": components["schemas"]["SessionCommand"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SessionView"];
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
    get_session_v1_assessment_sessions__session_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                session_id: string;
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
                    "application/json": components["schemas"]["SessionView"];
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
    cancel_session_v1_assessment_sessions__session_id__cancel_post: {
        parameters: {
            query?: never;
            header: {
                "Idempotency-Key": string;
                "If-Match": string;
            };
            path: {
                session_id: string;
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
                    "application/json": components["schemas"]["SessionSummary"];
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
    available_v1_review_sla_availability_put: {
        parameters: {
            query?: {
                enabled?: boolean;
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
    inbox_v1_review_sla_inbox_get: {
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
                    /** @description Next page UUID; advances past hidden actions */
                    "X-HR-Next-Cursor"?: string;
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
    create_policy_v1_grade_policies_post: {
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
                "application/json": components["schemas"]["reverse_hr__domains__assessment_grades__PolicyCommand"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PolicyView"];
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
    approve_policy_v1_grade_policies__policy_id__approve_post: {
        parameters: {
            query?: never;
            header: {
                "Idempotency-Key": string;
                "If-Match": string;
            };
            path: {
                policy_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["CalibrationData"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PolicyView"];
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
    get_evaluation_v1_assessment_sessions__session_id__evaluation_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                session_id: string;
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
                    "application/json": components["schemas"]["SessionEvaluation"];
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
    grade_review_v1_assessment_grade_reviews__session_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                session_id: string;
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
                    "application/json": components["schemas"]["SessionEvaluation"];
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
    decide_grade_v1_assessment_grade_reviews__session_id__decisions_post: {
        parameters: {
            query?: never;
            header: {
                "Idempotency-Key": string;
            };
            path: {
                session_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["DecisionCommand"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SessionEvaluation"];
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
    get_policy_v1_grade_policies__policy_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                policy_id: string;
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
                    "application/json": components["schemas"]["PolicyView"];
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
    retire_policy_v1_grade_policies__policy_id__retire_post: {
        parameters: {
            query?: never;
            header: {
                "Idempotency-Key": string;
                "If-Match": string;
            };
            path: {
                policy_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["RetirementCommand"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PolicyView"];
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
    notice_permission_internal_v1_market_appeal_notice_post: {
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
    own_list_v1_assessment_appeals_get: {
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
                    "application/json": components["schemas"]["AppealView"][];
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
    submit_v1_assessment_appeals_post: {
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
                "application/json": components["schemas"]["AppealCreate"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppealView"];
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
    queue_v1_assessment_appeals_queue_get: {
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
                    "application/json": components["schemas"]["AppealView"][];
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
    get_v1_assessment_appeals__appeal_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                appeal_id: string;
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
                    "application/json": components["schemas"]["AppealView"];
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
    claim_v1_assessment_appeals__appeal_id__claim_post: {
        parameters: {
            query?: never;
            header: {
                "Idempotency-Key": string;
                "If-Match": string;
            };
            path: {
                appeal_id: string;
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
                    "application/json": components["schemas"]["AppealView"];
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
    withdraw_v1_assessment_appeals__appeal_id__withdraw_post: {
        parameters: {
            query?: never;
            header: {
                "Idempotency-Key": string;
                "If-Match": string;
            };
            path: {
                appeal_id: string;
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
                    "application/json": components["schemas"]["AppealView"];
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
    workspace_v1_assessment_appeals__appeal_id__evidence_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                appeal_id: string;
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
                    "application/json": components["schemas"]["AppealEvidence"];
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
    resolve_v1_assessment_appeals__appeal_id__resolve_post: {
        parameters: {
            query?: never;
            header: {
                "Idempotency-Key": string;
                "If-Match": string;
            };
            path: {
                appeal_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["AppealResolution"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppealView"];
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
    history_v1_assessment_appeals__appeal_id__history_get: {
        parameters: {
            query?: {
                after?: number;
            };
            header?: never;
            path: {
                appeal_id: string;
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
                    "application/json": {
                        [key: string]: unknown;
                    }[];
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
    confirmed_grade_internal_v1_confirmed_grade_post: {
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
                "application/json": components["schemas"]["DecisionRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["DecisionReceipt"];
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
    submitted_tests_internal_v1_submitted_tests_post: {
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
                "application/json": components["schemas"]["SubmittedRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SubmittedReceipt"];
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
    receive_internal_v1_suite_validation_verdict_post: {
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
                "application/json": components["schemas"]["VerdictDelivery"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["VerdictReceipt"];
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
    get_v1_test_suites__suite_id__validations__validation_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                suite_id: string;
                validation_id: string;
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
    runtime_admission_v1_test_suites__suite_id__validations__validation_id__runtime_admission_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                suite_id: string;
                validation_id: string;
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
                    "application/json": components["schemas"]["RuntimeDecision"];
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
    admit_internal_v1_suite_validation_admission_post: {
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
                "application/json": components["schemas"]["SuiteAdmissionRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SuitePermit"];
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
    material_internal_v1_suite_validation_material_post: {
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
                "application/json": components["schemas"]["SuiteMaterialRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SuiteMaterial"];
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
    create_v1_content_versions__revision_id__tasks__task_key__test_suites_post: {
        parameters: {
            query?: never;
            header: {
                "Idempotency-Key": string;
            };
            path: {
                revision_id: string;
                task_key: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["SuiteDefinition"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SuiteView"];
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
    get_v1_test_suites__suite_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                suite_id: string;
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
                    "application/json": components["schemas"]["SuiteView"];
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
    review_v1_test_suites__suite_id__review_post: {
        parameters: {
            query?: never;
            header: {
                "Idempotency-Key": string;
                "If-Match": string;
            };
            path: {
                suite_id: string;
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
                    "application/json": components["schemas"]["SuiteView"];
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
    retire_v1_test_suites__suite_id__retire_post: {
        parameters: {
            query?: never;
            header: {
                "Idempotency-Key": string;
                "If-Match": string;
            };
            path: {
                suite_id: string;
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
                    "application/json": components["schemas"]["SuiteView"];
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
    evaluation_material_internal_v1_evaluation_material_post: {
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
                "application/json": components["schemas"]["MaterialRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["MaterialReceipt"];
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
    artifact_admission_internal_v1_evaluation_artifact_admission_post: {
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
                "application/json": components["schemas"]["ArtifactPermitRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ArtifactPermit"];
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
    start_session_v1_assessment_sessions__session_id__start_post: {
        parameters: {
            query?: never;
            header: {
                "Idempotency-Key": string;
                "If-Match": string;
            };
            path: {
                session_id: string;
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
                    "application/json": components["schemas"]["SessionView"];
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
    start_stage_v1_assessment_sessions__session_id__stages__stage_id__start_post: {
        parameters: {
            query?: never;
            header: {
                "Idempotency-Key": string;
                "If-Match": string;
            };
            path: {
                session_id: string;
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
                    "application/json": components["schemas"]["SessionView"];
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
    submit_stage_v1_assessment_sessions__session_id__stages__stage_id__submit_post: {
        parameters: {
            query?: never;
            header: {
                "Idempotency-Key": string;
                "If-Match": string;
            };
            path: {
                session_id: string;
                stage_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["SubmissionCommand"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SessionView"];
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
    workspace_stage_internal_v1_workspace_stage_post: {
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
                "application/json": components["schemas"]["StageRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["StageStatus"];
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
