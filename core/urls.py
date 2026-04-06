from django.urls import path, include
from django.views.generic import RedirectView
from django.contrib.auth import views as auth_views
from rest_framework.routers import DefaultRouter
from . import views
from . import admin_views
from . import dashboard_views
from . import application_detail_router
from . import employee_agent_views
from . import agent_views
from . import employee_views
from . import employee_views_new
from . import loan_management_api
from . import professional_views
from . import employee_management_views
from . import admin_views_new
from . import admin_api
from . import admin_unified_views
from . import admin_assign_views
from . import subadmin_views
from . import loan_api

router = DefaultRouter()
router.register(r'users', views.UserViewSet, basename='user')
router.register(r'agents', views.AgentViewSet, basename='agent')
router.register(r'loans', views.LoanViewSet, basename='loan')
router.register(r'loan-documents', views.LoanDocumentViewSet, basename='loan-document')
router.register(r'loan-applications', views.LoanApplicationViewSet, basename='loan-application')
router.register(r'applicant-documents', views.ApplicantDocumentViewSet, basename='applicant-document')
router.register(r'complaints', views.ComplaintViewSet, basename='complaint')
router.register(r'complaint-comments', views.ComplaintCommentViewSet, basename='complaint-comment')
router.register(r'activities', views.ActivityLogViewSet, basename='activity')

urlpatterns = [
    # Root redirect
    path('', RedirectView.as_view(url='login/', permanent=False), name='home'),
    
    # Frontend Views
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('dashboard/', views.dashboard, name='dashboard'),
    path(
        'password-reset/',
        auth_views.PasswordResetView.as_view(
            template_name='core/auth/password_reset_form.html',
            email_template_name='core/auth/password_reset_email.html',
            subject_template_name='core/auth/password_reset_subject.txt',
            success_url='/password-reset/done/'
        ),
        name='password_reset'
    ),
    path(
        'password-reset/done/',
        auth_views.PasswordResetDoneView.as_view(template_name='core/auth/password_reset_done.html'),
        name='password_reset_done'
    ),
    path(
        'reset/<uidb64>/<token>/',
        auth_views.PasswordResetConfirmView.as_view(
            template_name='core/auth/password_reset_confirm.html',
            success_url='/reset/done/'
        ),
        name='password_reset_confirm'
    ),
    path(
        'reset/done/',
        auth_views.PasswordResetCompleteView.as_view(template_name='core/auth/password_reset_complete.html'),
        name='password_reset_complete'
    ),
    
    # Registration Wizard
    path('register/<str:role>/step/<int:step>/', views.registration_wizard, name='registration_wizard'),
    
    # Admin Authentication & Dashboard
    path('admin-login/', views.admin_login_view, name='admin_login'),
    path('admin/logout/', views.admin_logout_view, name='admin_logout'),
    path('admin/dashboard/', admin_views.admin_dashboard, name='admin_dashboard'),
    path('admin/new-entry-assign/', views.admin_new_entry_assign, name='admin_new_entry_assign'),
    path('admin/all-loans/', admin_views.admin_all_loans, name='admin_all_loans'),
    path('admin/add-loan/', admin_views.admin_add_loan, name='admin_add_loan'),
    path('admin/all-employees/', views.admin_all_employees, name='admin_all_employees'),
    path('admin/all-agents/', views.admin_all_agents, name='admin_all_agents'),
    path('admin/add-agent/', admin_views.add_agent, name='add_agent'),
    path('admin/join-requests/', admin_views.admin_join_requests, name='admin_join_requests'),
    path('api/admin/join-requests/', admin_views.api_admin_join_requests, name='api_admin_join_requests'),
    path('api/admin/join-requests/<int:application_id>/detail/', admin_views.api_admin_join_request_detail, name='api_admin_join_request_detail'),
    path('api/admin/join-requests/<int:application_id>/action/', admin_views.api_admin_join_request_action, name='api_admin_join_request_action'),
    path('admin/team-management/', admin_views.team_management, name='team_management'),
    path('admin/subadmin-management/', admin_views.admin_subadmin_management, name='admin_subadmin_management'),
    path('api/admin/subadmin/<int:subadmin_id>/full-details/', admin_views.api_admin_subadmin_full_details, name='api_admin_subadmin_full_details'),
    path('admin/profile/', views.admin_profile, name='admin_profile'),
    
    # Admin Loan Status Pages
    path('admin/new-entries/', admin_views.admin_new_entries, name='admin_new_entries'),
    path('admin/in-processing/', admin_views.admin_in_processing, name='admin_in_processing'),
    path('admin/follow-ups/', admin_views.admin_follow_ups, name='admin_follow_ups'),
    path('admin/approved/', admin_views.admin_approved, name='admin_approved'),
    path('admin/rejected/', admin_views.admin_rejected, name='admin_rejected'),
    path('admin/disbursed/', admin_views.admin_disbursed, name='admin_disbursed'),
    path('admin/assign-application/<int:app_id>/', admin_views.assign_application, name='assign_application'),
    path('api/admin/application/<int:app_id>/details/', admin_views.api_get_application_details, name='api_application_details'),
    path('admin/loan/<int:loan_id>/detail/', views.admin_loan_detail, name='admin_loan_detail'),
    path('admin/loan/<int:loan_id>/assign-employee/', views.admin_assign_employee, name='admin_assign_employee'),
    path('admin/reports/', views.admin_reports, name='admin_reports'),
    path('admin/complaints/', views.admin_complaints, name='admin_complaints'),
    path('admin/settings/', views.admin_settings, name='admin_settings'),
    
    # Loan Management APIs
    path('api/loan/<int:loan_id>/details/', loan_api.api_loan_details, name='api_loan_details'),
    path('api/loan/<int:loan_id>/reject/', loan_api.api_loan_reject, name='api_loan_reject'),
    path('api/loan/<int:loan_id>/disburse/', loan_api.api_loan_disburse, name='api_loan_disburse'),
    path('api/loan/<int:loan_id>/disbursed-details/update/', loan_api.api_update_disbursed_details, name='api_update_disbursed_details'),
    path('api/loan/<int:loan_id>/delete/', loan_api.api_loan_delete, name='api_loan_delete'),
    path('api/loan/<int:loan_id>/forclose/', loan_api.api_loan_forclose, name='api_loan_forclose'),
    
    # SubAdmin Dashboard & Views
    path('subadmin/dashboard/', subadmin_views.subadmin_dashboard, name='subadmin_dashboard'),
    path('api/subadmin/dashboard-stats/', subadmin_views.api_subadmin_dashboard_stats, name='api_subadmin_dashboard_stats'),
    path('api/subadmin/recent-loans/', subadmin_views.api_subadmin_recent_loans, name='api_subadmin_recent_loans'),
    path('api/subadmin/loan/<int:loan_id>/details/', subadmin_views.api_subadmin_loan_details, name='api_subadmin_loan_details'),
    path('subadmin/add-loan/', subadmin_views.subadmin_add_loan, name='subadmin_add_loan'),
    path('subadmin/all-loans/', subadmin_views.subadmin_all_loans, name='subadmin_all_loans'),
    path('subadmin/loan/<int:loan_id>/detail/', subadmin_views.subadmin_loan_detail, name='subadmin_loan_detail'),
    path('subadmin/loan/<int:loan_id>/assign/', subadmin_views.subadmin_assign_employee_api, name='subadmin_assign_employee_api'),
    path('subadmin/my-agents/', subadmin_views.subadmin_my_agents, name='subadmin_my_agents'),
    path('subadmin/agent/<int:agent_id>/detail/', subadmin_views.subadmin_agent_detail, name='subadmin_agent_detail'),
    path('subadmin/agents/<int:agent_id>/', subadmin_views.subadmin_get_agent, name='subadmin_get_agent'),
    path('subadmin/agents/<int:agent_id>/update/', subadmin_views.subadmin_update_agent, name='subadmin_update_agent'),
    path('subadmin/agents/<int:agent_id>/delete/', subadmin_views.subadmin_delete_agent, name='subadmin_delete_agent'),
    path('subadmin/my-employees/', subadmin_views.subadmin_my_employees, name='subadmin_my_employees'),
    path('subadmin/employee/<int:employee_id>/detail/', subadmin_views.subadmin_employee_detail, name='subadmin_employee_detail'),
    path('subadmin/employees/<int:employee_id>/', subadmin_views.subadmin_get_employee, name='subadmin_get_employee'),
    path('subadmin/employees/<int:employee_id>/update/', subadmin_views.subadmin_update_employee, name='subadmin_update_employee'),
    path('subadmin/employees/<int:employee_id>/delete/', subadmin_views.subadmin_delete_employee, name='subadmin_delete_employee'),
    path('subadmin/reports/', subadmin_views.subadmin_reports, name='subadmin_reports'),
    path('subadmin/complaints/', subadmin_views.subadmin_complaints, name='subadmin_complaints'),
    path('subadmin/settings/', subadmin_views.subadmin_settings, name='subadmin_settings'),
    
    # Agent Dashboard & Views
    path('agent/dashboard/', agent_views.agent_dashboard, name='agent_dashboard'),
    path('agent/new-entries/', agent_views.agent_new_entries, name='agent_new_entries'),
    path('agent/add-loan/', agent_views.agent_add_loan, name='agent_add_loan'),
    path('agent/sub-agents/', agent_views.agent_sub_agents, name='agent_sub_agents'),
    path('agent/sub-agents/add/', agent_views.agent_add_employee, name='agent_add_employee'),
    path('agent/sub-agents/create/', agent_views.create_sub_agent, name='create_sub_agent'),
    path('agent/my-applications/', agent_views.agent_my_applications, name='agent_my_applications'),
    path('agent/loan/<int:loan_id>/edit-reverted/', agent_views.agent_resubmit_reverted_loan, name='agent_resubmit_reverted_loan'),
    path('agent/reports/', agent_views.agent_reports, name='agent_reports'),
    path('agent/complaints/', agent_views.agent_complaints, name='agent_complaints'),
    path('agent/complaints/file/', agent_views.file_complaint, name='file_complaint'),
    path('agent/profile/', agent_views.agent_profile, name='agent_profile'),
    path('agent/profile/edit/', agent_views.agent_edit_profile, name='agent_edit_profile'),
    path('agent/settings/', agent_views.agent_settings, name='agent_settings'),
    path('api/agent/dashboard-stats/', agent_views.api_agent_dashboard_stats, name='api_agent_dashboard_stats'),
    path('api/agent/notifications/', agent_views.agent_notifications, name='agent_notifications'),
    path('api/agent/recent-entries/', agent_views.api_agent_recent_entries, name='api_agent_recent_entries'),
    
    # Employee Dashboard & Views
    path('employee/dashboard/', employee_views.employee_dashboard, name='employee_dashboard'),
    path('employee/add-loan/', admin_views.admin_add_loan, name='employee_add_loan'),
    path('employee/assigned-loans/', employee_views.employee_assigned_loans, name='employee_assigned_loans'),
    path('employee/profile/', employee_views.employee_profile, name='employee_profile'),
    path('employee/settings/', employee_views.employee_settings, name='employee_settings'),
    
    # Employee Assigned Loans API
    path('api/employee/assigned-loans/', views.employee_assigned_loans_list, name='api_get_assigned_loans'),
    path('api/employee/loan-action/', employee_views.employee_loan_action, name='employee_loan_action'),
    
    # Employee Panel - New Pages (Fintech UI)
    path('employee/new-entry-request/', views.employee_request_new_entry_loan, name='employee_new_entry_request'),
    path('employee/new-entries/', views.employee_request_new_entry_loan, name='employee_new_entries'),
    path('employee/all-loans/', employee_views.employee_all_loans, name='employee_all_loans'),
    path('employee/loans/total/', employee_views.employee_loan_status_list, {'status_key': 'total'}, name='employee_loans_total'),
    path('employee/loans/new-entry/', employee_views.employee_loan_status_list, {'status_key': 'new_entry'}, name='employee_loans_new_entry'),
    path('employee/loans/in-processing/', employee_views.employee_loan_status_list, {'status_key': 'waiting'}, name='employee_loans_waiting'),
    path('employee/loans/awaiting/', employee_views.employee_loan_status_list, {'status_key': 'awaiting'}, name='employee_loans_awaiting'),
    path('employee/loans/approved/', employee_views.employee_loan_status_list, {'status_key': 'approved'}, name='employee_loans_approved'),
    path('employee/loans/rejected/', employee_views.employee_loan_status_list, {'status_key': 'rejected'}, name='employee_loans_rejected'),
    path('employee/loans/follow-up/', employee_views.employee_loan_status_list, {'status_key': 'follow_up'}, name='employee_loans_followup'),
    path('employee/loans/follow-up-pending/', employee_views.employee_loan_status_list, {'status_key': 'follow_up_pending'}, name='employee_loans_followup_pending'),
    path('employee/loans/disbursed/', employee_views.employee_loan_status_list, {'status_key': 'disbursed'}, name='employee_loans_disbursed'),
    path('employee/bank-processing/', views.employee_bank_processing_queue, name='employee_bank_processing'),
    path('employee/loan/<int:loan_id>/detail/', employee_views_new.employee_loan_detail_page, name='employee_loan_detail'),
    path('employee/loan/<int:loan_id>/bank-processing/', employee_views_new.employee_bank_processing_page, name='employee_bank_processing_detail'),
    path('employee/my-agents/', employee_views_new.employee_my_agents_page, name='employee_my_agents_page'),
    
    # Employee Panel - New APIs (Fintech UI)
    path('api/employee/dashboard-stats/', employee_views.employee_dashboard_stats, name='api_employee_dashboard_stats'),
    path('api/employee/monthly-loans/', employee_views.employee_monthly_loans_api, name='api_employee_monthly_loans'),
    path('api/employee/assigned-loans-list/', employee_views.employee_assigned_loans_list_api, name='api_employee_assigned_loans_list'),
    path('api/employee/all-processed-loans/', employee_views.employee_all_processed_loans_api, name='api_employee_all_processed_loans'),
    path('api/employee/loan/<int:loan_id>/detail/', views.employee_assigned_loan_detail, name='api_employee_loan_detail'),
    path('api/employee/loan/<int:loan_id>/follow-up/update/', views.employee_update_follow_up_details, name='api_employee_follow_up_update'),
    path('api/employee/loan/<int:loan_id>/follow-up/document/', views.employee_upload_follow_up_document, name='api_employee_follow_up_document'),
    path('api/employee/my-agents/', employee_views_new.employee_my_agents_api, name='api_employee_my_agents'),
    path('api/employee/add-agent/', employee_views_new.employee_add_agent_api, name='api_employee_add_agent'),
    path('api/employee/loan/<int:loan_id>/collect/', views.employee_collect_for_banking, name='api_employee_collect_loan'),
    path('api/employee/loan/<int:loan_id>/revert/', views.employee_revert_loan_to_agent, name='api_employee_revert_loan'),
    path('api/employee/loan/<int:loan_id>/sign/', views.employee_sign_off_loan, name='api_employee_sign_off_loan'),
    path('api/employee/loan/<int:loan_id>/approve/', views.employee_approve_loan, name='api_employee_approve_loan'),
    path('api/employee/loan/<int:loan_id>/reject/', views.employee_reject_loan, name='api_employee_reject_loan'),
    path('api/employee/loan/<int:loan_id>/disburse/', views.employee_disburse_loan, name='api_employee_disburse_loan'),
    path('api/employee/upload-profile-photo/', employee_views_new.employee_upload_profile_photo, name='api_employee_upload_profile_photo'),
    
    # New Entries Management
    path('admin/new-entries/', views.new_entries, name='new_entries'),
    path('admin/application-detail/<int:applicant_id>/', views.application_detail, name='application_detail'),
    path('admin/new-entry/<int:applicant_id>/', views.new_entry_detail, name='new_entry_detail'),
    path('admin/assign-application/<int:applicant_id>/', views.assign_application, name='assign_application'),
    
    # Waiting for Processing (Employee/Agent)
    path('my-applications/', views.my_applications, name='my_applications'),
    path('my-assigned-loans/', employee_agent_views.my_assigned_loans, name='my_assigned_loans'),
    path('loan/<int:loan_id>/action/', employee_agent_views.loan_detail_for_action, name='loan_detail_for_action'),
    path('application/<int:applicant_id>/', views.view_application, name='view_application'),
    path('admin/new-entry/<int:applicant_id>/detail/', views.view_new_entry_detail, name='view_new_entry_detail'),
    path('waiting/<int:applicant_id>/detail/', views.view_waiting_detail, name='view_waiting_detail'),
    path('admin/follow-up/<int:applicant_id>/detail/', views.view_followup_detail, name='view_followup_detail'),
    path('admin/reassign/<int:applicant_id>/', views.reassign_application, name='reassign_application'),
    path('admin/send-reminder/<int:applicant_id>/', views.send_follow_up_reminder, name='send_follow_up_reminder'),
    
    # Employee/Agent Actions (API endpoints)
    path('api/loan/<int:loan_id>/approve/', employee_agent_views.approve_loan, name='approve_loan'),
    path('api/loan/<int:loan_id>/reject/', employee_agent_views.reject_loan, name='reject_loan'),
    path('api/my-assigned-loans/', employee_agent_views.get_assigned_loans_api, name='get_assigned_loans_api'),
    
    # Legacy URLs (redirect to admin)
    path('loan-entry/', views.loan_entry, name='loan_entry_legacy'),
    path('loan/<int:loan_id>/documents/', views.document_upload, name='document_upload_legacy'),
    path('employee-list/', views.employee_list, name='employee_list_legacy'),
    path('agent-list/', views.agent_list, name='agent_list_legacy'),
    path('reports/', views.reports, name='reports_legacy'),
    path('complaints/', views.complaints, name='complaints_legacy'),
    
    # API Routes
    path('api/', include(router.urls)),
    path('api/dashboard-stats/', views.dashboard_stats, name='dashboard_stats'),
    path('api/admin/new-entries/', views.api_admin_new_entries, name='api_admin_new_entries'),
    path('api/admin-all-loans/', admin_views.api_admin_all_loans, name='api_admin_all_loans'),
    path('api/admin/create-subadmin/', admin_views.api_create_subadmin, name='api_create_subadmin'),
    path('api/admin/subadmin/<int:subadmin_id>/update/', admin_views.api_update_subadmin, name='api_update_subadmin'),
    path('api/admin/subadmin/<int:subadmin_id>/delete/', admin_views.api_delete_subadmin, name='api_delete_subadmin'),
    path('api/admin/get-subadmins/', admin_views.api_get_subadmins, name='api_get_subadmins'),
    path('api/subadmin/<int:subadmin_id>/toggle-status/', views.api_toggle_subadmin_status, name='api_toggle_subadmin_status'),
    
    # Agent Dashboard APIs
    path('api/agent-profile/', views.get_agent_profile, name='get_agent_profile'),
    path('api/agent-dashboard/stats/', views.get_agent_dashboard_stats, name='agent_dashboard_stats'),
    path('api/agent-dashboard/status-chart/', views.get_agent_status_chart, name='agent_status_chart'),
    path('api/agent-dashboard/trend-chart/', views.get_agent_trend_chart, name='agent_trend_chart'),
    path('api/my-assigned-loans/', views.get_my_assigned_loans, name='my_assigned_loans'),
    
    # AJAX API for Assignment Workflow
    path('api/get-employees/', views.get_employees_list, name='get_employees'),
    path('api/get-agents/', views.get_agents_list, name='get_agents'),
    path('api/assign-to-employee/<int:applicant_id>/', views.assign_to_employee, name='assign_to_employee'),
    path('api/assign-to-agent/<int:applicant_id>/', views.assign_to_agent, name='assign_to_agent'),
    path('api/approve/<int:applicant_id>/', views.approve_application, name='approve_application'),
    path('api/reject/<int:applicant_id>/', views.reject_application, name='reject_application'),
    
    # Workflow Dashboard & Automation
    path('admin/workflow-dashboard/', views.workflow_dashboard, name='workflow_dashboard'),
    path('admin/waiting-applications/', views.waiting_applications, name='waiting_applications'),
    path('admin/follow-up-applications/', views.follow_up_applications, name='follow_up_applications'),
    path('api/workflow/batch-assign/', views.batch_assign_applications, name='batch_assign_applications'),
    path('api/workflow/application-detail/<int:applicant_id>/', views.get_application_detail, name='get_application_detail'),
    path('api/workflow/stats/', views.workflow_stats, name='workflow_stats'),
    path('api/workflow/manual-follow-up/<int:applicant_id>/', views.manual_trigger_follow_up, name='manual_follow_up'),
    path('api/workflow/change-status/<int:applicant_id>/', views.change_application_status, name='change_status'),
    path('admin/follow-up/<int:applicant_id>/', views.follow_up_details, name='follow_up_details'),
    
    # NEW DASHBOARD SYSTEM - Table-based views with strict form control
    # New Entry - Admin only (READ-ONLY LIST + DETAIL)
    path('admin/dashboard/new-entry/', dashboard_views.admin_new_entry, name='admin_new_entry'),
    path('admin/dashboard/new-entry/<int:applicant_id>/', dashboard_views.admin_new_entry_detail, name='admin_new_entry_detail'),
    
    # Waiting for Processing - Role-based (READ-ONLY + APPROVE/REJECT)
    path('dashboard/waiting-for-processing/', dashboard_views.waiting_for_processing_list, name='waiting_for_processing_list'),
    path('dashboard/waiting-for-processing/<int:applicant_id>/', dashboard_views.waiting_for_processing_detail, name='waiting_for_processing_detail'),
    
    # Required Follow-up - Admin only (READ-ONLY + REASSIGN)
    path('admin/dashboard/required-follow-up/', dashboard_views.required_followup_list, name='required_followup_list'),
    path('admin/dashboard/required-follow-up/<int:applicant_id>/', dashboard_views.required_followup_detail, name='required_followup_detail'),
    path('admin/dashboard/required-follow-up/<int:applicant_id>/assign/', dashboard_views.reassign_followup_employee, name='reassign_followup_employee'),
    
    # Approved Applications - Admin only (READ-ONLY)
    path('admin/dashboard/approved/', dashboard_views.approved_applications, name='approved_list'),
    path('admin/dashboard/approved/<int:applicant_id>/', dashboard_views.approved_detail, name='approved_detail'),
    
    # Rejected Applications - Admin only (READ-ONLY)
    path('admin/dashboard/rejected/', dashboard_views.rejected_applications, name='rejected_list'),
    path('admin/dashboard/rejected/<int:applicant_id>/', dashboard_views.rejected_detail, name='rejected_detail'),
    
    # Disbursed Applications - Finance only (READ-ONLY)
    path('admin/dashboard/disbursed/', dashboard_views.disbursed_applications, name='disbursed_list'),
    path('admin/dashboard/disbursed/<int:applicant_id>/', dashboard_views.disbursed_detail, name='disbursed_detail'),
    
    # APPLICATION DETAIL ROUTER - Master router for all application detail pages
    # Routes to correct template based on status + role + safety checks
    path('application/<int:applicant_id>/detail/', application_detail_router.application_detail_router, name='application_detail_router'),
    path('application/<int:applicant_id>/form/', application_detail_router.new_entry_form_view, name='new_entry_form'),
    
    # NEW LOAN APPLICATION FORM
    path('loan-application-form/', views.loan_application_form, name='loan_application_form'),
    
    # AJAX Endpoints for real-time dashboard updates
    path('api/dashboard/counts/', dashboard_views.get_dashboard_counts, name='get_dashboard_counts'),
    path('api/dashboard/stats/', dashboard_views.get_dashboard_stats, name='get_dashboard_stats'),
    path('api/dashboard/trigger-followup-check/', dashboard_views.trigger_followup_check, name='trigger_followup_check'),
    
    # NEW REAL-TIME API ENDPOINTS FOR DOCUMENT & ASSIGNMENT MANAGEMENT
    path('api/loan/<int:loan_id>/documents/', views.api_get_loan_documents, name='api_get_loan_documents'),
    path('api/applicant/<int:applicant_id>/documents/', views.api_get_applicant_documents, name='api_get_applicant_documents'),
    path('api/my-assignments/', views.api_get_my_assignments, name='api_get_my_assignments'),
    path('api/update-application-status/', views.api_update_application_status, name='api_update_application_status'),
    path('api/assign-application/', views.api_assign_application, name='api_assign_application'),
    
    # ========== EMPLOYEE MANAGEMENT SYSTEM (NEW) ==========
    path('admin/employees/', employee_management_views.employee_management, name='employee_management'),
    path('admin/employees/add/', employee_management_views.employee_add_new, name='employee_add_new'),
    path('admin/employee-detail/<int:employee_id>/', employee_management_views.employee_detail, name='employee_detail'),
    path('api/employees/', employee_management_views.api_get_employees, name='api_get_employees'),
    path('api/employees/add/', employee_management_views.api_add_employee, name='api_add_employee'),
    path('api/employees/<int:employee_id>/', employee_management_views.api_get_employee, name='api_get_employee'),
    path('api/employees/<int:employee_id>/update/', employee_management_views.api_update_employee, name='api_update_employee'),
    path('api/employees/<int:employee_id>/delete/', employee_management_views.api_delete_employee, name='api_delete_employee'),
    path('api/employees/<int:employee_id>/toggle-status/', employee_management_views.api_toggle_employee_status, name='api_toggle_employee_status'),
    path('api/employees/stats/', employee_management_views.api_employee_stats, name='api_employee_stats'),
    
    # ========== ADMIN PROFILE & SETTINGS ==========
    path('admin/profile/', views.admin_profile, name='admin_profile'),
    path('api/admin/profile/', views.api_update_admin_profile, name='api_update_admin_profile'),
    path('api/admin/change-password/', views.api_change_password, name='api_change_password'),
    
    # ========== PROCESSING REQUESTS (ADMIN & EMPLOYEE) ==========
    path('admin/processing-requests/', views.admin_processing_requests, name='admin_assign_processing'),
    path('api/admin/processing-requests/', admin_views_new.api_admin_processing_requests, name='api_admin_processing_requests'),
    
    # ========== ADMIN PROFILE & SETTINGS (NEW) ==========
    path('admin/profile/', admin_views_new.admin_profile, name='admin_profile'),
    path('api/admin/profile/', admin_views_new.api_update_admin_profile, name='api_update_admin_profile'),
    path('api/admin/change-password/', admin_views_new.api_change_password, name='api_change_password'),
    
    # ========== PROCESSING REQUESTS (ADMIN & EMPLOYEE) (NEW) ==========
    path('admin/processing-requests/', admin_views_new.admin_processing_requests, name='admin_assign_processing'),
    
    # ========== USER PROFILE MANAGEMENT API (NEW) ==========
    path('api/profile/', admin_api.api_get_user_profile, name='api_get_user_profile'),
    path('api/profile/update/', admin_api.api_update_user_profile, name='api_update_user_profile'),
    path('api/profile/change-password/', admin_api.api_change_user_password, name='api_change_user_password'),
    path('api/profile/upload-photo/', admin_api.api_upload_profile_photo, name='api_upload_profile_photo'),
    
    # ========== PROCESSING REQUESTS API (NEW) ==========
    path('api/processing-requests/', admin_api.api_admin_processing_requests, name='api_processing_requests'),
    path('api/processing-requests/reassign/', admin_api.api_reassign_processing_request, name='api_reassign_processing_request'),
    
    # ========== ADMIN DASHBOARD STATS (NEW) ==========

    
    # ========== READ-ONLY NEW ENTRIES & LOAN DETAILS SYSTEM ==========
    # Admin Views - READ-ONLY with Assignment Panel
    # New Entries - List view (READ-ONLY table, no form)
    path('admin/new-entries/', views.admin_new_entries_list, name='admin_new_entries'),
    # Loan Detail - READ-ONLY form with assignment panel
    path('admin/loan/<int:applicant_id>/readonly/', views.admin_loan_detail_readonly, name='admin_loan_detail_readonly'),
    # API Endpoints for new entries
    path('api/admin/new-entries/', admin_api.api_admin_new_entries, name='api_admin_new_entries'),
    path('api/admin/new-entries/<int:applicant_id>/', admin_api.api_admin_new_entry_detail, name='api_admin_new_entry_detail'),
    path('api/admin/new-entries/<int:applicant_id>/assign/', admin_api.api_admin_assign_application_to_employee, name='api_admin_assign_application'),
    
    # Create Employee and Agent APIs
    path('api/admin/employees/create/', admin_api.api_create_employee, name='api_create_employee'),
    path('api/admin/agents/create/', admin_api.api_create_agent, name='api_create_agent'),
    path('api/admin/agents/add/', admin_api.api_add_agent, name='api_add_agent'),
    path('api/admin/agents/<int:agent_id>/', admin_api.api_get_agent, name='api_get_agent'),
    path('api/admin/agents/<int:agent_id>/update/', admin_api.api_update_agent, name='api_update_agent'),
    path('api/admin/agents/<int:agent_id>/delete/', admin_api.api_delete_agent, name='api_delete_agent'),
    
    # LEGACY UNIFIED SYSTEM - Keep for backward compatibility
    path('admin/loan/<int:applicant_id>/detail/', admin_unified_views.admin_loan_detail, name='admin_loan_detail'),
    path('admin/loan/<int:applicant_id>/assign/', admin_unified_views.admin_assign_employee, name='admin_assign_employee'),
    path('admin/loan/<int:applicant_id>/edit/', admin_unified_views.admin_edit_application, name='admin_edit_application'),
    path('admin/loan/<int:applicant_id>/update/', admin_unified_views.admin_update_application, name='admin_update_application'),
    path('admin/loan/<int:applicant_id>/upload-doc/', admin_unified_views.admin_upload_document, name='admin_upload_document'),
    path('admin/loan/<int:applicant_id>/followup/', admin_unified_views.admin_trigger_followup, name='admin_trigger_followup'),
    path('admin/loan/<int:applicant_id>/update-status/', admin_unified_views.admin_update_status, name='admin_update_status'),
    
    # Loan Details - All loans accessible from sidebar with real-time data
    path('admin/loan-details/', admin_unified_views.admin_loan_details_all, name='admin_loan_details_all'),
    
    # Real-time API Endpoints
    path('api/dashboard-stats/', admin_unified_views.api_dashboard_stats, name='api_dashboard_stats'),
    path('api/loan-list/', admin_unified_views.api_loan_list, name='api_loan_list'),
    
    # Admin Management Views - Employee, Agent, Complaints (LEGACY)
    path('admin/employees-legacy/', views.admin_employee_list, name='admin_employee_list'),
    path('admin/agents/', views.admin_agent_list, name='admin_agent_list'),
    path('admin/complaints/', views.admin_complaints_list, name='admin_complaints_list'),
    
    # API Endpoints for complaints with employee/agent info
    path('api/admin/complaints/', views.api_get_complaints_with_filer, name='api_complaints_with_filer'),
    
    # Employee Dashboard Routes - NEW
    path('employee/dashboard/', views.employee_dashboard, name='employee_dashboard'),
    path('employee/profile/', views.employee_profile, name='employee_profile'),
    path('employee/settings/', views.employee_settings, name='employee_settings'),
    path('employee/request-new-entry-loan/', views.employee_request_new_entry_loan, name='employee_request_new_entry_loan'),
    
    # Employee Real-Time API Endpoints
    path('api/employee-dashboard-stats/', views.employee_dashboard_stats, name='employee_dashboard_stats'),
    path('api/employee-assigned-loans/', views.employee_assigned_loans, name='employee_assigned_loans'),
    path('api/employee/assigned-loans/', views.employee_assigned_loans_list, name='employee_assigned_loans_list'),
    path('api/employee/assigned-loans/<int:loan_id>/', views.employee_assigned_loan_detail, name='employee_assigned_loan_detail'),
    path('api/employee/loan/<int:loan_id>/approve/', views.employee_approve_loan, name='employee_approve_loan'),
    path('api/employee/loan/<int:loan_id>/reject/', views.employee_reject_loan, name='employee_reject_loan'),
    path('api/employee/loan/<int:loan_id>/disburse/', views.employee_disburse_loan, name='employee_disburse_loan'),
    
    # Comprehensive Loan Application Form
    path('comprehensive-loan-form/', views.comprehensive_loan_form, name='comprehensive_loan_form'),
    path('admin/loan-detail/<int:loan_id>/', views.loan_detail, name='loan_detail'),
    
    # ========== PROFESSIONAL LOAN MANAGEMENT API ROUTES ===========
    
    # New Loan Applications Management (AJAX only)
    path('admin/new-loan-applications/', views.new_entries, name='admin_new_loan_applications'),
    path('new-loan-applications-professional/', loan_management_api.api_get_new_loan_applications, name='new_loan_applications_professional'),
    path('api/new-loan-applications/', loan_management_api.api_get_new_loan_applications, name='api_new_loan_applications'),
    path('api/loan-detail/<int:loan_id>/', loan_management_api.api_get_loan_detail, name='api_loan_detail'),
    path('api/assign-loan-to-employee/<int:loan_id>/', loan_management_api.api_assign_loan_to_employee, name='api_assign_loan_to_employee'),
    path('api/loan/<int:loan_id>/approve/', loan_management_api.api_approve_loan_ajax, name='api_approve_loan_ajax'),
    path('api/loan/<int:loan_id>/reject/', loan_management_api.api_reject_loan_ajax, name='api_reject_loan_ajax'),
    path('api/loan/<int:loan_id>/disburse/', loan_management_api.api_disburse_loan_ajax, name='api_disburse_loan_ajax'),
    
    # Dashboard Real-time API
    path('api/dashboard-realtime-stats/', loan_management_api.api_dashboard_stats, name='api_dashboard_realtime_stats'),
    path('api/recent-complaints/', loan_management_api.api_get_recent_complaints, name='api_recent_complaints'),
    
    # Employee Management API (Admin only)
    path('admin/employees-management/', views.admin_employee_list, name='admin_employees_management'),
    path('api/create-employee/', loan_management_api.api_create_employee, name='api_create_employee'),
    path('api/delete-employee/<int:employee_id>/', loan_management_api.api_delete_employee, name='api_delete_employee'),
    
    # Report Download API
    path('api/download-report/', loan_management_api.api_download_report, name='api_download_report'),
    
    # ========== PROFESSIONAL VIEWS ROUTES ==========
    
    # Professional Loan Applications
    path('admin/professional/new-loans/', professional_views.professional_new_loan_applications, name='professional_new_loan_applications'),
    
    # Professional Employee Management
    path('admin/professional/employees/', professional_views.professional_employee_management, name='professional_employee_management'),
    
    # Real-time Dashboard
    path('admin/professional/dashboard/', professional_views.real_time_dashboard, name='real_time_dashboard'),
    
    # Complaint Management
    path('admin/professional/complaints/', professional_views.admin_complaints_panel, name='admin_complaints_panel'),
    
    # Loan Assignment
    path('admin/professional/assignments/', professional_views.loan_assignment_panel, name='loan_assignment_panel'),
    
    # Employee Dashboard
    path('employee/professional/dashboard/', professional_views.employee_dashboard_view, name='employee_dashboard_view'),
    
    # Activity Log
    path('admin/professional/activity-log/', professional_views.activity_log_view, name='activity_log_view'),
    
    # System Settings
    path('admin/professional/settings/', professional_views.system_settings_view, name='system_settings_view'),
    
    # Reports Download
    path('admin/professional/reports/', professional_views.download_reports, name='download_reports'),
    
    # ========== NEW LOAN MANAGEMENT SYSTEM URLS ==========
    # Admin Loan Views
    path('admin/loan-entries/', views.loan_entries_view, name='loan_entries'),
    path('admin/loan-waiting/', views.loan_waiting_view, name='loan_waiting'),
    path('admin/loan-followup/', views.loan_followup_view, name='loan_followup'),
    path('admin/loan-approved/', views.loan_approved_view, name='loan_approved'),
    path('admin/loan-rejected/', views.loan_rejected_view, name='loan_rejected'),
    path('admin/loan-disbursed/', views.loan_disbursed_view, name='loan_disbursed'),
    path('admin/loan-details/', views.loan_details_view, name='loan_details'),
    
    # Loan Application Detail Page
    path('admin/loan-application/<int:loan_id>/', views.loan_application_detail, name='loan_application_detail'),
    
    # Loan Management APIs
    path('api/loan-entries/', views.api_loan_entries, name='api_loan_entries'),
    path('api/loan-status/<str:status>/', views.api_loan_status_list, name='api_loan_status_list'),
    path('api/loan/<int:loan_id>/assign/', views.api_assign_loan, name='api_assign_loan'),
    path('api/loan/<int:loan_id>/reassign/', views.api_reassign_loan, name='api_reassign_loan'),
    path('api/dashboard-stats/', views.api_dashboard_stats, name='api_dashboard_stats'),
    path('api/employees-list/', views.api_employees_list, name='api_employees_list'),
    
    # Employee Assigned Loans APIs
    path('api/employee/assigned-loans/', admin_api.api_employee_assigned_loans, name='api_employee_assigned_loans'),
    path('api/employee/assigned-loans/<int:loan_id>/action/', admin_api.api_employee_loan_action, name='api_employee_loan_action'),
    path('api/employee/assigned-loans/<int:loan_id>/update-status/', admin_api.api_employee_loan_update_status, name='api_employee_loan_update_status'),
    path('api/loan/<int:loan_id>/detail/', views.api_loan_detail, name='api_loan_detail'),
    
    # ========== EMPLOYEE PANEL - NEW IMPLEMENTATION ==========
    # Employee Dashboard & All Loans
    path('api/employee/dashboard-stats-new/', views.employee_dashboard_stats, name='api_employee_dashboard_stats_new'),
    path('api/employee/all-loans/', employee_views_new.employee_all_loans_api, name='api_employee_all_loans'),
    path('api/employee/new-entry-requests/', employee_views_new.employee_new_entry_requests_api, name='api_employee_new_entry_requests'),
    path('api/employee/loan/<int:loan_id>/update/', employee_views_new.employee_update_loan_api, name='api_employee_update_loan'),
    path('api/employee/loan/<int:loan_id>/delete/', employee_views_new.employee_delete_loan_api, name='api_employee_delete_loan'),
    path('api/employee/agents/<int:agent_id>/update/', employee_views_new.employee_update_agent_api, name='api_employee_update_agent'),
    path('api/employee/agents/<int:agent_id>/delete/', employee_views_new.employee_delete_agent_api, name='api_employee_delete_agent'),
    
    # Employee Loan Detail & Actions
    path('api/employee/loan/<int:loan_id>/detail/', employee_views_new.employee_loan_detail_api, name='api_employee_loan_detail_new'),
    path('api/employee/loan/<int:loan_id>/approve/', employee_views_new.employee_approve_loan_api, name='api_employee_approve_loan'),
    path('api/employee/loan/<int:loan_id>/reject/', employee_views_new.employee_reject_loan_api, name='api_employee_reject_loan'),
    path('api/employee/loan/<int:loan_id>/disburse/', employee_views_new.employee_disburse_loan_api, name='api_employee_disburse_loan'),
    
    # Employee Agent Management
    path('api/employee/agents/', employee_views_new.employee_my_agents_api, name='api_employee_my_agents'),
    path('api/employee/agent/add/', employee_views_new.employee_add_agent_api, name='api_employee_add_agent'),
    
    # ========== ADMIN ASSIGNMENT ENDPOINTS (REAL-TIME) ==========
    path('api/admin/assign-loan/', admin_assign_views.admin_assign_loan_to_employee, name='api_admin_assign_loan'),
    path('api/admin/loan/<int:loan_id>/reassign/', admin_assign_views.admin_reassign_loan, name='api_admin_reassign_loan'),
    path('api/admin/loan/<int:loan_id>/assignment-status/', admin_assign_views.admin_get_assignment_status, name='api_admin_assignment_status'),
]




