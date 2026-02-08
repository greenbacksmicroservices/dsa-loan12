from django.urls import path, include
from django.views.generic import RedirectView
from rest_framework.routers import DefaultRouter
from . import views
from . import dashboard_views
from . import application_detail_router
from . import employee_agent_views
from . import agent_views
from . import employee_views
from . import loan_management_api
from . import professional_views
from . import employee_management_views
from . import admin_views_new
from . import admin_api
from . import admin_unified_views
from . import admin_all_loans_views
from . import admin_assign_role_views
from . import admin_views

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
    
    # Registration Wizard
    path('register/<str:role>/step/<int:step>/', views.registration_wizard, name='registration_wizard'),
    
    # Admin Authentication & Dashboard
    path('admin-login/', views.admin_login_view, name='admin_login'),
    path('admin/logout/', views.admin_logout_view, name='admin_logout'),
    path('admin/dashboard/', views.admin_dashboard, name='admin_dashboard'),
    path('admin/new-entry-assign/', views.admin_new_entry_assign, name='admin_new_entry_assign'),
    
    # Agent Dashboard & Views
    path('agent/dashboard/', agent_views.agent_dashboard, name='agent_dashboard'),
    path('agent/new-entries/', agent_views.agent_new_entries, name='agent_new_entries'),
    path('agent/add-loan/', agent_views.agent_add_loan, name='agent_add_loan'),
    path('agent/sub-agents/', agent_views.agent_sub_agents, name='agent_sub_agents'),
    path('agent/sub-agents/create/', agent_views.create_sub_agent, name='create_sub_agent'),
    path('agent/my-applications/', agent_views.agent_my_applications, name='agent_my_applications'),
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
    path('', employee_views.employee_all_loans, name='employee_all_loans'),
    path('employee/assigned-loans/', employee_views.employee_assigned_loans, name='employee_assigned_loans'),
    path('employee/profile/', employee_views.employee_profile, name='employee_profile'),
    path('employee/settings/', employee_views.employee_settings, name='employee_settings'),
    
    # Employee Assigned Loans API
    path('api/employee/assigned-loans/', employee_views.api_get_assigned_loans, name='api_get_assigned_loans'),
    path('api/employee/loan-action/', employee_views.employee_loan_action, name='employee_loan_action'),
    
    # Employee Panel - New Pages (Fintech UI)
    path('employee/new-entry-request/', employee_views.employee_new_entry_request_page, name='employee_new_entry_request'),
    path('employee/new-entries/', employee_views.employee_new_entry_request_page, name='employee_new_entries'),
    path('employee/all-loans/', employee_views.employee_all_loans, name='employee_all_loans_view'),
    path('employee/loan/<int:loan_id>/detail/', employee_views.employee_loan_detail_page, name='employee_loan_detail'),
    path('employee/my-agents/', employee_views.employee_my_agents_page, name='employee_my_agents_page'),
    
    # Employee Panel - New APIs (Fintech UI)
    path('api/employee/dashboard-stats/', employee_views.employee_dashboard_stats, name='api_employee_dashboard_stats'),
    path('api/employee/assigned-loans-list/', employee_views.employee_assigned_loans_list_api, name='api_employee_assigned_loans_list'),
    path('api/employee/all-processed-loans/', employee_views.employee_all_processed_loans_api, name='api_employee_all_processed_loans'),
    path('api/employee/loan/<int:loan_id>/detail/', employee_views.employee_loan_detail_api, name='api_employee_loan_detail'),
    path('api/employee/my-agents/', employee_views.employee_my_agents_api, name='api_employee_my_agents'),
    path('api/employee/add-agent/', employee_views.employee_add_agent_api, name='api_employee_add_agent'),
    path('api/employee/loan/<int:loan_id>/approve/', employee_views.employee_approve_loan_api, name='api_employee_approve_loan'),
    path('api/employee/loan/<int:loan_id>/reject/', employee_views.employee_reject_loan_api, name='api_employee_reject_loan'),
    path('api/employee/loan/<int:loan_id>/disburse/', employee_views.employee_disburse_loan_api, name='api_employee_disburse_loan'),
    
    # New Entries Management
    path('admin/new-entries/', views.new_entries, name='new_entries'),
    path('admin/application-detail/<int:applicant_id>/', views.application_detail, name='application_detail'),
    path('admin/new-entry/<int:applicant_id>/', views.new_entry_detail, name='new_entry_detail'),
    path('admin/assign-application/<int:applicant_id>/', views.assign_application, name='assign_application'),
    
    # Waiting for Processing (Employee/Agent)
    path('my-applications/', views.my_applications, name='my_applications'),
    path('api/my-applications/', loan_management_api.api_my_applications, name='api_my_applications'),
    path('api/application/<int:applicant_id>/assign-employee/', loan_management_api.api_assign_employee, name='api_assign_employee'),
    
    # Comprehensive Loan Form
    path('comprehensive-loan-form/', views.comprehensive_loan_form, name='comprehensive_loan_form'),
    path('admin/loan-detail/<int:loan_id>/', views.loan_detail, name='loan_detail'),
    
    # ========== ADMIN ALL LOANS - MASTER DATABASE VIEW ==========
    path('admin/all-loans/', admin_views.admin_all_loans, name='admin_all_loans'),
    path('api/admin/all-loans/', admin_views.api_get_all_loans, name='api_get_all_loans'),
    path('admin/loan/<int:loan_id>/view/', admin_views.admin_loan_detail, name='admin_loan_view'),
    path('api/admin/loan/<int:loan_id>/detail/', admin_views.api_get_loan_detail, name='api_admin_loan_detail'),
    path('admin/loan/<int:loan_id>/edit/', admin_views.admin_edit_loan, name='admin_edit_loan_master'),
    path('api/admin/loan/<int:loan_id>/delete/', admin_views.api_delete_loan, name='api_delete_loan'),
    path('api/admin/loan/<int:loan_id>/reassign/', admin_views.api_reassign_loan, name='api_reassign_loan'),
    path('api/admin/all-loans/stats/', admin_views.api_get_loan_stats, name='api_all_loans_stats'),
    
    # ========== ADMIN ASSIGN AGENTS TO EMPLOYEES ==========
    path('admin/assign-role/', admin_assign_role_views.admin_assign_role, name='admin_assign_role'),
    path('api/admin/get-employees-for-agent-assignment/', admin_assign_role_views.api_get_employees_for_agent_assignment, name='api_get_employees_for_agent_assignment'),
    path('api/admin/get-employee-agents/<int:employee_id>/', admin_assign_role_views.api_get_employee_agents, name='api_get_employee_agents'),
    path('api/admin/assign-agent-to-employee/', admin_assign_role_views.api_assign_agent_to_employee, name='api_assign_agent_to_employee'),
    path('api/admin/unassign-agent-from-employee/', admin_assign_role_views.api_unassign_agent_from_employee, name='api_unassign_agent_from_employee'),
    
    # ========== PROFESSIONAL LOAN MANAGEMENT API ROUTES ==========
    
    # New Loan Applications Management (AJAX only)
    path('api/new-applicant/', loan_management_api.create_new_applicant, name='api_new_applicant'),
    path('api/applicants/', loan_management_api.get_applicants, name='api_applicants'),
    path('api/applicant/<int:applicant_id>/', loan_management_api.get_applicant_detail, name='api_applicant_detail'),
    path('api/applicant/<int:applicant_id>/update/', loan_management_api.update_applicant, name='api_applicant_update'),
    path('api/applicant/<int:applicant_id>/status/', loan_management_api.update_applicant_status, name='api_applicant_status'),
    path('api/applicant/<int:applicant_id>/assign/', loan_management_api.assign_to_employee, name='api_applicant_assign'),
    
    # Document Management
    path('api/document/upload/', loan_management_api.upload_document, name='api_document_upload'),
    path('api/document/<int:document_id>/delete/', loan_management_api.delete_document, name='api_document_delete'),
    path('api/documents/<int:applicant_id>/', loan_management_api.get_documents, name='api_get_documents'),
    
    # REST API routes
    path('api/', include(router.urls)),
    path('api-auth/', include('rest_framework.urls')),
]
