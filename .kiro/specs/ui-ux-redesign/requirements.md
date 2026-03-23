# Requirements Document: UI/UX Redesign

## Introduction

This document specifies the requirements for a comprehensive visual and functional redesign of the DSA Loan Management System. The system serves Admin, SubAdmin, Employee, and Agent roles through a Django-based multi-panel application. The redesign encompasses both UI/UX improvements and significant backend functionality expansions including employee agent creation, real-time data synchronization, enhanced loan views, and signature status management.

## Glossary

- **System**: The DSA Loan Management System
- **Admin**: User with administrative privileges who can view and edit all data
- **Employee**: User who can create agents and manage assigned loans
- **Agent**: User who submits loan applications
- **SubAdmin**: User with limited administrative privileges
- **Design_Token_System**: CSS custom properties defining visual variables (colors, spacing, shadows, radii)
- **Compact_Card**: Small, 1-row gradient dashboard card component
- **All_Loans_View**: Comprehensive master database table showing complete loan data
- **Loan_Detail_Page**: Full-page view with 9 sections of loan information
- **Loan_Edit_Page**: Admin interface for editing all loan fields
- **Signature_Status**: Yes/No radio selection for disbursement confirmation
- **Real_Time_Update**: Data synchronization without page reload
- **Agent_Creation_Form**: Employee interface for creating new agents
- **Audit_Trail**: Historical record of data changes with user and timestamp

## Requirements

### Requirement 1: Design Token System

**User Story:** As a developer, I want a centralized design token system, so that visual consistency is maintained across all panels and components.

#### Acceptance Criteria

1. THE System SHALL define all visual variables in a single CSS file (design-system.css)
2. THE Design_Token_System SHALL include color tokens for primary, accent, surface, background, border, text, success, warning, danger, and info
3. THE Design_Token_System SHALL include spacing tokens from 4px to 32px
4. THE Design_Token_System SHALL include shadow tokens (sm, md, lg, card)
5. THE Design_Token_System SHALL include radius tokens (sm, md, lg, xl)
6. THE Design_Token_System SHALL include font-size tokens (xs, sm, base, lg, xl, 2xl)
7. WHEN any template uses visual styling, THE System SHALL reference design tokens instead of inline values

### Requirement 2: Employee Agent Creation

**User Story:** As an employee, I want to create and manage my own agents, so that I can build my team and track their performance.

#### Acceptance Criteria

1. WHEN an employee submits the agent creation form, THE System SHALL create a new agent record linked to that employee
2. WHEN creating an agent, THE System SHALL require photo, agent_id, full_name, password, phone, and email fields
3. WHEN an agent_id already exists, THE System SHALL reject the creation and return error "Agent ID already exists"
4. WHEN an email already exists, THE System SHALL reject the creation and return error "Email already registered"
5. WHEN a phone number already exists, THE System SHALL reject the creation and return error "Phone already registered"
6. WHEN a photo exceeds 5MB, THE System SHALL reject the upload and return error "Photo must be less than 5MB"
7. WHEN an agent is successfully created, THE System SHALL set created_by_employee to the current employee user
8. WHEN an agent is successfully created, THE System SHALL return JSON response with agent data
9. WHEN an agent is successfully created, THE System SHALL update the agent table in real-time without page reload

### Requirement 3: Agent Table Filtering

**User Story:** As an employee, I want to see only agents I created, so that I can manage my team without confusion from other employees' agents.

#### Acceptance Criteria

1. WHEN an employee views the agent table, THE System SHALL display only agents where created_by_employee equals the current employee
2. WHEN an admin views the agent table, THE System SHALL display all agents with creator information
3. THE Agent_Table SHALL include columns for Photo, Agent ID, Name, Phone, Email, Created By, Status, Total Loans, and Actions
4. WHEN displaying the Created By column, THE System SHALL show the creator's role and full name
5. WHEN displaying agent status, THE System SHALL show a badge with "Active" in green or "Inactive" in gray

### Requirement 4: Real-Time Data Synchronization

**User Story:** As an admin, I want employee panels to update automatically when I assign loans, so that employees see new assignments immediately without refreshing.

#### Acceptance Criteria

1. WHEN an admin assigns a loan to an employee, THE System SHALL update the employee dashboard within 5 seconds
2. WHEN an employee performs an action on a loan, THE System SHALL update the admin dashboard within 5 seconds
3. WHEN an agent resubmits a loan, THE System SHALL update the processing queue within 5 seconds
4. THE Real_Time_Update mechanism SHALL use AJAX polling with 5-second intervals
5. WHEN real-time updates occur, THE System SHALL not require full page reload
6. WHEN a real-time API call fails, THE System SHALL continue polling and log the error

### Requirement 5: Compact Dashboard Cards

**User Story:** As a user, I want compact dashboard cards that display key metrics efficiently, so that I can see important information at a glance without scrolling.

#### Acceptance Criteria

1. THE Compact_Card SHALL have a minimum height of 80px (1-row design)
2. THE Compact_Card SHALL display an icon, metric value, and label in a single row
3. THE Compact_Card SHALL use gradient backgrounds (teal, blue, green, or red based on metric type)
4. WHEN a user hovers over a Compact_Card, THE System SHALL apply a lift effect (translateY -2px)
5. WHEN a user clicks a Compact_Card, THE System SHALL navigate to the filtered view for that metric
6. THE Compact_Card SHALL include an arrow icon indicating it is clickable

### Requirement 6: All Loans Master View

**User Story:** As an admin, I want a comprehensive table showing all loan data, so that I can review and manage the complete loan database.

#### Acceptance Criteria

1. THE All_Loans_View SHALL display exactly 10 columns: Loan ID, Applicant Name, Phone, Loan Type, Amount, Submitted By, Assigned Employee, Status, Created Date, and Actions
2. WHEN displaying Submitted By, THE System SHALL show the creator's role and full name
3. WHEN displaying Assigned Employee, THE System SHALL show the assignee's role and full name or "-" if unassigned
4. WHEN displaying status, THE System SHALL show a colored badge (green for approved, red for rejected, blue for processing)
5. WHEN an admin applies a status filter, THE System SHALL display only loans matching that status
6. WHEN an admin enters a search query, THE System SHALL filter loans by name, phone, email, or loan ID
7. THE All_Loans_View SHALL order loans by creation date with newest first
8. THE All_Loans_View SHALL paginate results at 25 loans per page

### Requirement 7: Loan Detail Page with 9 Sections

**User Story:** As an admin, I want to view all loan information organized into clear sections, so that I can quickly find specific details without searching through unstructured data.

#### Acceptance Criteria

1. THE Loan_Detail_Page SHALL display exactly 9 sections
2. THE Section 1 SHALL contain Applicant Details: full name, phone, email, DOB, gender, PAN, Aadhaar, CIBIL score
3. THE Section 2 SHALL contain Address Details: permanent and current addresses with city, state, pincode
4. THE Section 3 SHALL contain Occupation & Income Details: occupation, employer, income, experience
5. THE Section 4 SHALL contain Loan Request Details: type, amount, tenure, interest rate, EMI, purpose
6. THE Section 5 SHALL contain Bank Details: bank name, type, account number, IFSC code
7. THE Section 6 SHALL contain All Uploaded Documents with view and download buttons
8. THE Section 7 SHALL contain Remarks History in chronological order
9. THE Section 8 SHALL contain Assignment Details: assigned to, assigned by, date, hours since assignment
10. THE Section 9 SHALL contain SM Details: signature name, phone, email, and signature status
11. WHEN any field has no value, THE System SHALL display "-" as the default
12. WHEN a document is an image, THE System SHALL display a thumbnail preview

### Requirement 8: Loan Edit Page with Pre-filled Form

**User Story:** As an admin, I want to edit all loan fields with pre-filled values, so that I can make corrections efficiently without re-entering unchanged data.

#### Acceptance Criteria

1. WHEN an admin opens the loan edit page, THE System SHALL pre-fill all form fields with current loan data
2. THE Loan_Edit_Page SHALL allow editing of all applicant, address, occupation, loan, bank, and SM details fields
3. WHEN an admin submits the edit form, THE System SHALL validate all required fields
4. WHEN validation passes, THE System SHALL update the loan record with new values
5. WHEN a loan is updated, THE System SHALL set updated_at to the current timestamp
6. WHEN a loan is updated, THE System SHALL create an audit trail entry with edited_by, edited_at, fields_changed, old_values, and new_values
7. WHEN a loan is successfully updated, THE System SHALL redirect to the loan detail page
8. WHEN validation fails, THE System SHALL display error messages and preserve form state

### Requirement 9: Signature Status Yes/No Selection

**User Story:** As an admin, I want to confirm disbursement signature status with a Yes/No selection, so that I can clearly indicate whether the signature has been obtained.

#### Acceptance Criteria

1. THE Loan_Detail_Page SHALL display "Disbursed Signature" as the label (not "SM Name")
2. THE Signature_Status SHALL be displayed as Yes/No radio buttons (not a Sign button)
3. WHEN a loan has is_sm_signed equal to true, THE System SHALL select the "Yes" radio button
4. WHEN a loan has is_sm_signed equal to false, THE System SHALL select the "No" radio button
5. WHEN an admin selects "Yes", THE System SHALL set is_sm_signed to true and sm_signed_at to current timestamp
6. WHEN an admin selects "No", THE System SHALL set is_sm_signed to false and sm_signed_at to NULL
7. WHEN signature status is updated, THE System SHALL display a success toast notification
8. WHEN is_sm_signed is true, THE System SHALL display the signed date below the radio buttons

### Requirement 10: Enhanced Card Component

**User Story:** As a developer, I want a reusable card component with consistent styling, so that all panels have a unified professional appearance.

#### Acceptance Criteria

1. THE Enhanced_Card SHALL use rounded corners defined by --radius-lg token
2. THE Enhanced_Card SHALL use soft shadow defined by --shadow-card token
3. THE Enhanced_Card SHALL have a white background defined by --color-surface token
4. THE Enhanced_Card SHALL include a header section for titles and a body section for content
5. WHEN a card is interactive, THE System SHALL apply a hover lift effect

### Requirement 11: Enhanced Table Component

**User Story:** As a user, I want tables with clear visual hierarchy and responsive behavior, so that I can easily read and interact with tabular data on any device.

#### Acceptance Criteria

1. THE Enhanced_Table SHALL have a teal gradient header row
2. THE Enhanced_Table SHALL apply alternating row colors (striped rows)
3. WHEN a user hovers over a table row, THE System SHALL highlight the row
4. THE Enhanced_Table SHALL be wrapped in a responsive container with horizontal scroll on small screens
5. THE Enhanced_Table SHALL use consistent typography hierarchy for headers and cells

### Requirement 12: Real-Time Table Update

**User Story:** As an employee, I want the agent table to update instantly when I create a new agent, so that I can see my new agent without refreshing the page.

#### Acceptance Criteria

1. WHEN an agent creation API returns success, THE System SHALL insert a new row at the top of the agent table
2. WHEN a new row is inserted, THE System SHALL apply a highlight animation for 2 seconds
3. WHEN a new row is inserted, THE System SHALL increment the total agents count by 1
4. WHEN a new row is inserted, THE System SHALL display a success toast notification
5. WHEN a new row is inserted, THE System SHALL reset the agent creation form

### Requirement 13: Loan Detail Data Aggregation

**User Story:** As a developer, I want efficient data aggregation for loan details, so that the detail page loads quickly with all required information.

#### Acceptance Criteria

1. WHEN fetching loan details, THE System SHALL use select_related for assigned_employee, assigned_agent, and created_by
2. WHEN fetching loan details, THE System SHALL use prefetch_related for documents and status_history
3. WHEN parsing remarks, THE System SHALL extract colon-delimited fields into structured data
4. WHEN aggregating address data, THE System SHALL determine if current address equals permanent address
5. WHEN aggregating documents, THE System SHALL include file URL, file name, upload date, and image indicator for each document

### Requirement 14: Authentication and Authorization

**User Story:** As a system administrator, I want role-based access control, so that users can only access features appropriate to their role.

#### Acceptance Criteria

1. WHEN a non-authenticated user attempts to access any page, THE System SHALL redirect to the login page
2. WHEN a non-admin user attempts to access admin-only pages, THE System SHALL return 403 Forbidden
3. WHEN a non-employee user attempts to access employee-only pages, THE System SHALL return 403 Forbidden
4. WHEN an employee attempts to view agents, THE System SHALL filter to only agents created by that employee
5. WHEN an admin attempts to view agents, THE System SHALL display all agents without filtering

### Requirement 15: Input Validation

**User Story:** As a system administrator, I want comprehensive input validation, so that invalid or malicious data cannot enter the system.

#### Acceptance Criteria

1. WHEN validating agent_id, THE System SHALL ensure it is alphanumeric, max 50 characters, and unique
2. WHEN validating email, THE System SHALL ensure it matches valid email format and is unique
3. WHEN validating phone, THE System SHALL ensure it matches the pattern ^\+?1?\d{9,15}$ and is unique
4. WHEN validating photo upload, THE System SHALL ensure size is max 5MB and format is jpg, jpeg, png, or gif
5. WHEN validating pincode, THE System SHALL ensure it is exactly 6 digits
6. THE System SHALL perform all validation server-side regardless of client-side validation

### Requirement 16: Error Handling

**User Story:** As a user, I want clear error messages and graceful error handling, so that I understand what went wrong and how to fix it.

#### Acceptance Criteria

1. WHEN agent creation fails due to duplicate agent_id, THE System SHALL display "Agent ID already exists"
2. WHEN agent creation fails due to duplicate email, THE System SHALL display "Email already registered"
3. WHEN agent creation fails due to duplicate phone, THE System SHALL display "Phone already registered"
4. WHEN photo upload exceeds 5MB, THE System SHALL display "Photo must be less than 5MB"
5. WHEN a real-time API call fails, THE System SHALL log the error and continue polling
6. WHEN loan detail API fails, THE System SHALL display "Unable to load loan details. Please try again." with a Retry button
7. WHEN loan edit save fails, THE System SHALL display error message and preserve form state
8. WHEN signature status update fails, THE System SHALL revert radio button state and display error toast

### Requirement 17: Performance Optimization

**User Story:** As a user, I want fast page loads and responsive interactions, so that I can work efficiently without waiting.

#### Acceptance Criteria

1. WHEN loading the all loans page with 1000 loans, THE System SHALL complete in less than 2 seconds
2. WHEN loading a loan detail page, THE System SHALL complete in less than 1 second
3. WHEN calling real-time API endpoints, THE System SHALL respond in less than 500ms
4. WHEN creating an agent, THE System SHALL complete in less than 1 second
5. WHEN rendering a table with 25 rows, THE System SHALL complete in less than 100ms
6. THE System SHALL use database indexes on loan.status, loan.assigned_employee_id, loan.assigned_agent_id, and agent.created_by_employee_id

### Requirement 18: Security

**User Story:** As a system administrator, I want comprehensive security measures, so that user data is protected from unauthorized access and attacks.

#### Acceptance Criteria

1. THE System SHALL require CSRF tokens for all POST, PATCH, and DELETE requests
2. THE System SHALL escape all dynamic values in templates to prevent XSS attacks
3. THE System SHALL use parameterized queries to prevent SQL injection
4. THE System SHALL validate file uploads by content (not just extension)
5. THE System SHALL store uploaded files outside the web root with unique generated names
6. THE System SHALL enforce session timeout after 30 minutes of inactivity
7. THE System SHALL use secure session cookies (HttpOnly, Secure, SameSite=Strict)
8. THE System SHALL hash passwords using Django's PBKDF2 algorithm

### Requirement 19: Audit Trail

**User Story:** As a system administrator, I want a complete audit trail of data changes, so that I can track who made what changes and when.

#### Acceptance Criteria

1. WHEN an agent is created, THE System SHALL log the creator user ID and timestamp
2. WHEN a loan is edited, THE System SHALL create an audit entry with editor user ID, timestamp, fields_changed, old_values, and new_values
3. WHEN signature status is changed, THE System SHALL log the user ID and timestamp
4. THE Audit_Trail entries SHALL be immutable (cannot be edited or deleted)
5. THE Audit_Trail SHALL be stored in a separate table from the main data

### Requirement 20: UI Framework Integration

**User Story:** As a developer, I want a hybrid Bootstrap 5 and Tailwind CSS approach, so that I can leverage the strengths of both frameworks.

#### Acceptance Criteria

1. THE System SHALL load Bootstrap 5 for grid system, forms, and JavaScript components
2. THE System SHALL load Tailwind CSS for utility classes (spacing, flexbox, typography, colors)
3. THE System SHALL define hybrid component classes that combine Bootstrap base with Tailwind utilities
4. WHEN using Tailwind in production, THE System SHALL configure PurgeCSS to remove unused classes
5. THE System SHALL maintain backward compatibility with existing Bootstrap-based components

