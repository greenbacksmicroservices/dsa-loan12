# Implementation Plan: UI/UX Redesign

## Overview

This implementation plan covers a comprehensive visual and functional redesign of the DSA Loan Management System. The redesign includes a centralized design token system, employee agent creation with real-time updates, enhanced loan views with 9-section detail pages, signature status management, and compact dashboard cards. The implementation uses Python/Django with Bootstrap 5 and Tailwind CSS hybrid approach.

## Tasks

- [x] 1. Create design token system and base CSS infrastructure
  - Create `static/css/design-system.css` with CSS custom properties for colors, spacing, shadows, radii, and typography
  - Define all design tokens: primary colors (teal-based), spacing scale (4px-32px), shadow tokens (sm, md, lg, card), radius tokens (sm, md, lg, xl), font-size tokens (xs-2xl)
  - Create reusable CSS classes for cards (ds-card), tables (ds-table), buttons (ds-btn), badges (ds-badge), and compact cards (ds-compact-card)
  - Update all base templates (admin_base.html, employee/base.html, agent/base.html, subadmin_base.html) to load design-system.css
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 10.1, 10.2, 10.3, 10.4, 10.5, 20.1, 20.2, 20.3_

- [ ]* 1.1 Write property test for design token consistency
  - **Property 1: Design token consistency across templates**
  - **Validates: Requirements 1.1, 1.7**
  - Test that all card elements use --shadow-card and --radius-lg tokens
  - Test that all templates reference design tokens instead of inline values

- [x] 2. Implement database migration for agent created_by_employee field
  - Create migration file `0023_agent_created_by_employee.py` to add `created_by_employee` foreign key to Agent model
  - Add field with `on_delete=SET_NULL`, `null=True`, `blank=True`, `limit_choices_to={'role': 'employee'}`
  - Run migration to update database schema
  - _Requirements: 2.7, 3.1, 3.2, 14.4, 19.1_

- [ ] 3. Implement employee agent creation backend
  - [ ] 3.1 Create employee_add_agent_api view in core/employee_views_new.py
    - Implement POST endpoint `/api/employee/add-agent/`
    - Extract and validate form data (photo, agent_id, full_name, password, phone, email, address, city, state, pincode, status)
    - Validate required fields: photo, agent_id, full_name, password, phone, email
    - Check uniqueness constraints: agent_id, email, phone
    - Validate photo size (max 5MB) and format (jpg, jpeg, png, gif)
    - Create User account with role='agent' and hash password
    - Create Agent profile with created_by_employee=request.user
    - Return JSON response with agent data or error message
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 2.8, 15.1, 15.2, 15.3, 15.4, 16.1, 16.2, 16.3, 16.4_

  - [ ]* 3.2 Write property test for agent creation
    - **Property 2: Agent creation links to employee**
    - **Validates: Requirements 2.1, 2.7**
    - Test that for all agents created by employee E, agent.created_by_employee = E
    - Test that agent_id uniqueness is enforced
    - Test that email uniqueness is enforced
    - Test that phone uniqueness is enforced

  - [ ] 3.3 Add URL route for employee_add_agent_api
    - Add route `path('api/employee/add-agent/', employee_add_agent_api, name='employee_add_agent_api')` to core/urls.py
    - Apply @login_required and @require_http_methods(["POST"]) decorators
    - _Requirements: 2.1, 14.3_

- [ ] 4. Implement employee agent creation frontend
  - [ ] 4.1 Create agent creation form template
    - Create form in employee dashboard or separate page with fields: photo (file input), agent_id, full_name, password, phone, email, address, city, state, pincode, status (dropdown)
    - Add client-side validation for required fields and photo size
    - Style form with Bootstrap 5 form components and design tokens
    - _Requirements: 2.2, 15.4_

  - [ ] 4.2 Implement real-time table update JavaScript
    - Create `realTimeTableUpdate(apiResponse)` function to append new agent row to table
    - Insert new row at top of table with highlight animation (2 seconds)
    - Update total agents count by incrementing by 1
    - Show success toast notification
    - Reset form after successful creation
    - Handle error responses with error toast
    - _Requirements: 2.9, 12.1, 12.2, 12.3, 12.4, 12.5, 16.1, 16.2, 16.3, 16.4_

  - [ ]* 4.3 Write property test for real-time table update
    - **Property 3: Real-time table update without page reload**
    - **Validates: Requirements 2.9, 12.1**
    - Test that successful agent creation updates table without page reload
    - Test that new row appears at top of table
    - Test that total count increments by 1

- [ ] 5. Implement agent table filtering
  - [ ] 5.1 Update employee agent list view
    - Filter agents queryset by `created_by_employee=request.user` for employees
    - Use `select_related('created_by_employee')` for efficient queries
    - Display all agents for admins with creator information
    - _Requirements: 3.1, 3.2, 14.4, 17.6_

  - [ ] 5.2 Create agent table template with 8 columns
    - Create table with columns: Photo (thumbnail), Agent ID, Name, Phone, Email, Created By, Status (badge), Total Loans, Actions
    - Apply ds-table and ds-table-wrapper classes for styling
    - Show "Employee - [name]" or "Admin - [name]" in Created By column
    - Display status badge with green for Active, gray for Inactive
    - Add responsive wrapper with horizontal scroll on mobile
    - _Requirements: 3.3, 3.4, 3.5, 11.1, 11.2, 11.3, 11.4, 11.5_

  - [ ]* 5.3 Write property test for agent table filtering
    - **Property 4: Employee sees only their agents**
    - **Validates: Requirements 3.1, 3.2**
    - Test that employee E can only view agents where created_by_employee = E
    - Test that admin A can view all agents with creator information

- [ ] 6. Checkpoint - Ensure agent creation and filtering work correctly
  - Ensure all tests pass, ask the user if questions arise.

- [x] 7. Implement compact dashboard cards
  - [ ] 7.1 Create compact card CSS component
    - Define ds-compact-card class with flexbox layout, min-height 80px
    - Create gradient variants: --gradient-teal, --gradient-blue, --gradient-green, --gradient-red
    - Add hover lift effect (translateY -2px) and shadow transition
    - Style icon, content, and action sections
    - _Requirements: 5.1, 5.2, 5.3, 5.4_

  - [ ] 7.2 Update dashboard templates with compact cards
    - Replace existing stat cards in admin_dashboard.html, employee/dashboard.html with ds-compact-card components
    - Display icon, metric value, and label in single row
    - Add clickable link to filtered view for each card
    - Use appropriate gradient for each metric type (teal=total, blue=processing, green=approved, red=rejected)
    - _Requirements: 5.1, 5.2, 5.3, 5.5, 5.6_

  - [ ]* 7.3 Write property test for compact card design
    - **Property 5: Compact cards have 1-row design**
    - **Validates: Requirements 5.1, 5.2**
    - Test that all compact cards have min-height of 80px
    - Test that cards display icon, value, and label in single row
    - Test that cards have gradient backgrounds

- [ ] 8. Implement admin all loans master view
  - [ ] 8.1 Create admin_all_loans view
    - Build queryset with `select_related('assigned_employee', 'assigned_agent', 'created_by')` and `prefetch_related('documents')`
    - Apply status filter from query parameter
    - Apply search filter for name, phone, email, loan_id
    - Order by `-created_at` (newest first)
    - Enrich each loan with `submitted_by_display` and `assigned_to_display` fields
    - Paginate at 25 loans per page
    - _Requirements: 6.1, 6.2, 6.3, 6.5, 6.6, 6.7, 6.8, 13.1, 17.1, 17.6_

  - [ ] 8.2 Create all_loans.html template with 10 columns
    - Create table with columns: Loan ID, Applicant Name, Phone, Loan Type, Amount, Submitted By, Assigned Employee, Status, Created Date, Actions
    - Display submitted_by_display with role and name
    - Display assigned_to_display with role and name or "-" if unassigned
    - Show colored status badge (green=approved, red=rejected, blue=processing)
    - Add filter controls for status and search input
    - Apply ds-table styling with striped rows and hover effects
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 11.1, 11.2, 11.3_

  - [ ]* 8.3 Write property test for all loans view
    - **Property 6: All loans view displays complete data**
    - **Validates: Requirements 6.1, 6.2, 6.3**
    - Test that all loans have exactly 10 columns displayed
    - Test that submitted_by_display shows creator role and name
    - Test that assigned_to_display shows assignee role and name
    - Test that status filter correctly filters loans

- [ ] 9. Implement loan detail page with 9 sections
  - [ ] 9.1 Create loanDetailDataAggregation function
    - Fetch loan with `select_related` for employee, agent, created_by
    - Use `prefetch_related` for documents and status_history
    - Parse remarks for colon-delimited fields
    - Aggregate data into 9 sections: applicant_data, address_data, occupation_data, loan_data, bank_data, documents, remarks_history, assignment_data, sm_data
    - Set default value "-" for missing fields
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 7.6, 7.7, 7.8, 7.9, 7.10, 7.11, 13.1, 13.2, 13.3, 13.4, 13.5_

  - [ ] 9.2 Create loan_detail.html template with 9 sections
    - Section 1: Applicant Details (name, phone, email, DOB, gender, PAN, Aadhaar, CIBIL)
    - Section 2: Address Details (permanent and current addresses with city, state, pincode)
    - Section 3: Occupation & Income Details (occupation, employer, income, experience)
    - Section 4: Loan Request Details (type, amount, tenure, interest rate, EMI, purpose)
    - Section 5: Bank Details (bank name, type, account number, IFSC)
    - Section 6: Documents (all uploaded documents with view/download buttons, thumbnails for images)
    - Section 7: Remarks History (chronological order with timestamps)
    - Section 8: Assignment Details (assigned to, assigned by, date, hours since assignment)
    - Section 9: SM Details (signature name, phone, email, signature status Yes/No radio)
    - Use ds-card components for each section with consistent spacing
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 7.6, 7.7, 7.8, 7.9, 7.10, 7.11, 7.12_

  - [ ]* 9.3 Write property test for loan detail sections
    - **Property 7: Loan detail page has exactly 9 sections**
    - **Validates: Requirements 7.1, 7.2**
    - Test that all loan detail pages display exactly 9 sections
    - Test that all sections have complete data or default value "-"
    - Test that Section 9 displays "Disbursed Signature" label (not "SM Name")

- [ ] 10. Checkpoint - Ensure all loans view and detail page work correctly
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 11. Implement loan edit page with pre-filled form
  - [ ] 11.1 Create admin_loan_edit view
    - GET: Fetch loan data and pre-fill form fields
    - POST: Extract updated fields from request body
    - Validate all required fields
    - Update loan record with new values
    - Set updated_at to current timestamp
    - Create audit trail entry with edited_by, edited_at, fields_changed, old_values, new_values
    - Return JSON response with success/error and redirect URL
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 8.6, 8.7, 8.8, 19.2_

  - [ ] 11.2 Create loan_edit.html template
    - Create form with all editable fields organized by section (applicant, address, occupation, loan, bank, SM details)
    - Pre-fill all fields with current loan data using Django template variables
    - Add client-side validation for required fields
    - Submit form via AJAX to avoid page reload
    - Show success toast and redirect to detail page on success
    - Show error message and preserve form state on failure
    - _Requirements: 8.1, 8.2, 8.3, 8.7, 8.8_

  - [ ]* 11.3 Write property test for loan edit audit trail
    - **Property 8: Loan edit creates audit trail**
    - **Validates: Requirements 8.6, 19.2**
    - Test that loan edit creates audit log entry with changed fields
    - Test that old_values and new_values are recorded correctly
    - Test that edited_by and edited_at are set

- [ ] 12. Implement signature status Yes/No selection
  - [ ] 12.1 Create api_update_signature_status view
    - Implement PATCH endpoint `/api/loan/<loan_id>/signature-status/`
    - Extract is_sm_signed boolean from request body
    - Update loan.is_sm_signed to provided value
    - If is_sm_signed=true, set sm_signed_at to current timestamp
    - If is_sm_signed=false, set sm_signed_at to NULL
    - Return JSON response with success, is_sm_signed, sm_signed_at
    - _Requirements: 9.5, 9.6, 9.7, 19.3_

  - [ ] 12.2 Update loan detail template with Yes/No radio buttons
    - Replace "SM Name" label with "Disbursed Signature"
    - Replace Sign button with Yes/No radio buttons
    - Pre-select "Yes" if is_sm_signed=true, "No" if false
    - Add onchange handler to call updateSignatureStatus function
    - Display signed date below radio buttons if is_sm_signed=true
    - _Requirements: 9.1, 9.2, 9.3, 9.4, 9.8_

  - [ ] 12.3 Implement updateSignatureStatus JavaScript function
    - Send PATCH request to `/api/loan/<loan_id>/signature-status/`
    - Include CSRF token in request headers
    - On success: show success toast, keep radio selected, update signed date display
    - On failure: revert radio button state, show error toast
    - _Requirements: 9.5, 9.6, 9.7, 16.8_

  - [ ]* 12.4 Write property test for signature status
    - **Property 9: Signature status radio selection consistency**
    - **Validates: Requirements 9.3, 9.4, 9.5, 9.6**
    - Test that loans with is_sm_signed=true have "Yes" radio selected
    - Test that loans with is_sm_signed=false have "No" radio selected
    - Test that selecting "Yes" sets sm_signed_at to current timestamp
    - Test that selecting "No" clears sm_signed_at

- [ ] 13. Implement real-time data synchronization
  - [ ] 13.1 Create real-time API endpoints
    - Create `/api/employee/dashboard-stats/` endpoint returning updated counts (total_loans, processing, approved, rejected)
    - Create `/api/admin/recent-assignments/` endpoint returning new assignments since last poll
    - Create `/api/employee/new-loans/` endpoint returning loans assigned since last check
    - Use efficient queries with select_related and filters
    - Return only changed data (delta updates)
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 17.3_

  - [ ] 13.2 Implement RealTimeUpdater JavaScript class
    - Create base class with start(), stop(), fetchUpdates(), handleUpdate() methods
    - Set polling interval to 5 seconds
    - Implement error handling to continue polling on failure
    - Stop polling when user navigates away from page
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 16.5_

  - [ ] 13.3 Implement EmployeeDashboardUpdater subclass
    - Override handleUpdate() to update loan counts in DOM
    - Append new loans to table if new_loans array is not empty
    - Show toast notification for new assignments
    - _Requirements: 4.1, 4.2, 4.5_

  - [ ]* 13.4 Write property test for real-time updates
    - **Property 10: Real-time updates within 5 seconds**
    - **Validates: Requirements 4.1, 4.2, 4.3**
    - Test that admin loan assignment updates employee panel within 5 seconds
    - Test that employee actions update admin dashboard within 5 seconds
    - Test that updates occur without full page reload

- [ ] 14. Checkpoint - Ensure real-time updates and signature status work correctly
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 15. Apply design tokens to all existing templates
  - [ ] 15.1 Update admin templates
    - Replace inline styles with design token classes in admin_dashboard.html, admin_all_loans.html, admin_loan_detail.html
    - Apply ds-card to all card components
    - Apply ds-table to all table components
    - Ensure consistent spacing using --space-* tokens
    - _Requirements: 1.7, 10.1, 10.2, 10.3_

  - [ ] 15.2 Update employee templates
    - Replace inline styles with design token classes in employee/dashboard.html, employee/agents.html
    - Apply ds-card to all card components
    - Apply ds-table to all table components
    - Ensure consistent spacing using --space-* tokens
    - _Requirements: 1.7, 10.1, 10.2, 10.3_

  - [ ] 15.3 Update agent templates
    - Replace inline styles with design token classes in agent/dashboard.html, agent/my_applications.html
    - Apply ds-card to all card components
    - Apply ds-table to all table components
    - Ensure consistent spacing using --space-* tokens
    - _Requirements: 1.7, 10.1, 10.2, 10.3_

- [ ] 16. Implement enhanced table component styling
  - Update all table templates to use ds-table-wrapper and ds-table classes
  - Add teal gradient header row using design tokens
  - Apply alternating row colors (striped rows) with nth-child(even)
  - Add hover highlight effect on table rows
  - Ensure responsive wrapper with overflow-x: auto on small screens
  - _Requirements: 11.1, 11.2, 11.3, 11.4, 11.5_

- [ ] 17. Add URL routes for all new endpoints
  - Add route for `/api/employee/add-agent/` (employee_add_agent_api)
  - Add route for `/api/loan/<loan_id>/signature-status/` (api_update_signature_status)
  - Add route for `/api/employee/dashboard-stats/` (employee_dashboard_stats_api)
  - Add route for `/api/admin/recent-assignments/` (admin_recent_assignments_api)
  - Add route for `/api/employee/new-loans/` (employee_new_loans_api)
  - Add route for `/admin/all-loans/` (admin_all_loans)
  - Add route for `/admin/loan/<loan_id>/detail/` (admin_loan_detail)
  - Add route for `/admin/loan/<loan_id>/edit/` (admin_loan_edit)
  - _Requirements: 2.1, 9.5, 4.1, 6.1, 7.1, 8.1_

- [ ] 18. Implement authentication and authorization decorators
  - Ensure all admin-only views use @admin_required decorator
  - Ensure all employee-only views use @employee_required decorator (create if not exists)
  - Ensure all API endpoints use @login_required decorator
  - Add role checks in view logic for additional security
  - Return 403 Forbidden for unauthorized access attempts
  - _Requirements: 14.1, 14.2, 14.3, 14.4, 14.5, 16.8_

- [ ] 19. Implement input validation and error handling
  - Add server-side validation for all form inputs (agent creation, loan edit)
  - Validate agent_id format (alphanumeric, max 50 chars) and uniqueness
  - Validate email format and uniqueness
  - Validate phone format (regex: ^\+?1?\d{9,15}$) and uniqueness
  - Validate photo size (max 5MB) and format (jpg, jpeg, png, gif)
  - Validate pincode format (exactly 6 digits)
  - Return specific error messages for each validation failure
  - _Requirements: 15.1, 15.2, 15.3, 15.4, 15.5, 15.6, 16.1, 16.2, 16.3, 16.4, 16.5, 16.6, 16.7, 16.8_

- [ ] 20. Add database indexes for performance optimization
  - Create index on `loan.status` for status filtering
  - Create index on `loan.assigned_employee_id` for employee loan queries
  - Create index on `loan.assigned_agent_id` for agent loan queries
  - Create index on `agent.created_by_employee_id` for agent filtering
  - Create index on `loan.created_at` for date ordering
  - _Requirements: 17.1, 17.2, 17.3, 17.4, 17.5, 17.6_

- [ ] 21. Final checkpoint - Integration testing and validation
  - Test complete employee agent creation flow (form submission → real-time table update)
  - Test admin all loans view with filtering and search
  - Test loan detail page with all 9 sections displaying correctly
  - Test loan edit page with pre-filled form and audit trail
  - Test signature status Yes/No selection with timestamp updates
  - Test real-time data synchronization (admin assigns loan → employee panel updates)
  - Test compact dashboard cards with clickable links
  - Test design token consistency across all templates
  - Verify all authentication and authorization checks work correctly
  - Verify all input validation and error handling work correctly
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional property-based tests and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation at key milestones
- Property tests validate universal correctness properties from the design document
- The implementation uses Python/Django with Bootstrap 5 and Tailwind CSS hybrid approach
- All real-time updates use AJAX polling with 5-second intervals (no WebSockets required for MVP)
- Design tokens provide single source of truth for visual consistency
- Agent filtering ensures employees only see their own agents, admins see all
- Signature status uses Yes/No radio buttons instead of Sign button
- All loans view displays complete data with 10 columns
- Loan detail page has exactly 9 sections with organized information
- Audit trail tracks all data changes with user and timestamp
