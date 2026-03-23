# Bug Fixes and Feature Enhancements - Requirements

## Overview
Complete bug fixes and feature enhancements for DSA Loan Management System to ensure production-ready deployment on Hostinger VPS.

## Requirements

### 1. Agent Panel - Reverted Loan Editing
**Current Issue**: When employee reverts loan to agent, agent sees limited edit form
**Required**: Full loan application form with all fields editable + multiple document uploads

**Changes Needed**:
- Enhance `agent_resubmit_reverted_loan` view to show complete loan application form
- Allow editing all fields: applicant details, address, loan details, bank details, co-applicant, guarantor
- Support multiple document uploads (not just one)
- Real-time document preview
- Save and resubmit to Banking Processing

### 2. Employee Panel - Signature Handling
**Current Issue**: "Sign" button exists in approval page
**Required**: Replace with "Signature Done: Yes/No" option

**Changes Needed**:
- Remove "Sign (Tick Mark)" button from `templates/core/employee/loan_detail.html`
- Add radio buttons or dropdown: "Signature Done: Yes / No"
- Update approval modal to include signature status
- Modify backend to save signature status with approval

### 3. SubAdmin Panel - Employee/Agent Management
**Current Issue**: SubAdmin cannot view/edit employee and agent details like admin
**Required**: SubAdmin should have full visibility and edit capabilities for their employees/agents

**Changes Needed**:
- Add employee list view for subadmin with full details
- Add agent list view for subadmin with full details
- Enable edit functionality for subadmin on employees/agents
- Show bank details, personal details, performance metrics
- Real-time updates

### 4. Registration Page - Remove Loan Fields
**Current Issue**: Registration page has loan-related fields (Loan Type, Amount, Tenure, Interest Rate, Purpose)
**Required**: Remove all loan fields from registration

**Files to Modify**:
- `templates/core/login.html` - Registration section
- `templates/core/admin_login.html` - Registration section
- Registration wizard templates
- Backend views handling registration

**Fields to Remove**:
- Loan Type *
- Loan Amount (₹) *
- Tenure (Months) *
- Interest Rate (%) *
- Loan Purpose *

### 5. Admin Panel - All Loans Edit Enhancement
**Current Issue**: Edit section shows limited fields
**Required**: Full loan application form details for editing

**Changes Needed**:
- Enhance admin all loans edit view
- Show complete loan application form
- Allow editing all fields
- Include document management
- Real-time validation

### 6. SubAdmin/Agent Creation - Bank Details
**Current Issue**: No bank details collected during subadmin/agent creation
**Required**: Add bank details fields

**Fields to Add**:
- Bank Name *
- Account Number *
- IFSC Code *
- Bank Type (Private/Government/Cooperative/NBFC)
- Branch Name
- Account Holder Name

### 7. Bug Fixes

#### Critical Bugs:
1. **Duplicate Login Decorators** - Remove duplicate `@login_required` in views.py
2. **Missing Notifications** - Implement notification system for loan status changes
3. **Incomplete Revert Logic** - Fix revert flow to properly return to agent queue
4. **Signature Field Inconsistency** - Sync `is_sm_signed` between Loan and LoanApplication models

#### Data Integrity Bugs:
5. **Mobile Number Validation** - Fix regex pattern and add consistent validation
6. **PIN Code Handling** - Enforce 6-digit validation consistently
7. **Status Enum Mismatch** - Standardize status values across models
8. **Duplicate URL Patterns** - Remove duplicate URL entries

#### Workflow Bugs:
9. **24-Hour Follow-up** - Implement automated follow-up task
10. **Employee-Agent Relationship** - Validate assignment before auto-assignment
11. **Loan Sync Inconsistency** - Prevent duplicate records in sync
12. **SubAdmin Scope Leakage** - Ensure proper scoping in all queries

#### Security Bugs:
13. **Password Field in Loan Model** - Remove password field
14. **Rate Limiting** - Add rate limiting to login endpoints
15. **CSRF Protection** - Ensure all API endpoints have CSRF validation

#### UI/UX Bugs:
16. **Inconsistent Status Labels** - Standardize status display
17. **Missing Error Handling** - Add try-catch blocks
18. **Document Upload Validation** - Add file type/size validation

### 8. Production Readiness for Hostinger VPS

**Requirements**:
- Optimize database queries (add indexes, select_related, prefetch_related)
- Add proper logging and error tracking
- Configure static files for production
- Add database connection pooling
- Implement caching where appropriate
- Add health check endpoints
- Configure ALLOWED_HOSTS properly
- Set DEBUG=False with proper error pages
- Add database backup automation
- Configure HTTPS and security headers

## Success Criteria

1. Agent can edit complete loan application when reverted
2. Employee approval uses "Signature Done: Yes/No" instead of sign button
3. SubAdmin can view and edit all employee/agent details
4. Registration page has no loan fields
5. Admin can edit complete loan details
6. Bank details collected for subadmin/agent creation
7. All critical bugs fixed
8. System runs smoothly on Hostinger VPS without errors
9. Real-time updates work correctly
10. No data integrity issues

## Priority

1. **P0 (Critical)**: Bug fixes (security, data integrity)
2. **P1 (High)**: Agent revert editing, Employee signature handling
3. **P2 (Medium)**: SubAdmin enhancements, Registration cleanup
4. **P3 (Low)**: Production optimizations

## Timeline

- Bug Fixes: Immediate
- Feature Enhancements: 2-3 days
- Production Optimization: 1-2 days
- Testing & Deployment: 1 day
