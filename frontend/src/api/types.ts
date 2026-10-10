import type { components as Candidate } from "./generated/candidate";
import type { components as Privacy } from "./generated/privacy";
import type { components as Employer } from "./generated/employer";

export type Profile = Candidate["schemas"]["Profile"];
export type ProfileUpdate = Candidate["schemas"]["ProfileUpdate"];
export type Grade = Candidate["schemas"]["Grade"];
export type Consent = Privacy["schemas"]["Consent"];
export type ConsentCommand = Privacy["schemas"]["ConsentCommand"];
export type Purpose = ConsentCommand["purpose"];
export type ContactGrant = Privacy["schemas"]["ContactGrantView"];
export type Deletion = Privacy["schemas"]["DeletionView"];
export type Organization = Employer["schemas"]["OrganizationView"];
export type OrganizationCommand = Employer["schemas"]["OrganizationCommand"];
export type Membership = Employer["schemas"]["MembershipView"];
export type MembershipCommand = Employer["schemas"]["MembershipCommand"];

import type { components as Hiring } from "./generated/hiring";
export type Invitation = Hiring["schemas"]["InvitationView"];
export type Acceptance = Hiring["schemas"]["Acceptance"];
