"""JSON chart API endpoints for dashboards."""

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.http import require_GET

from .chart_helpers import (
    get_monthly_loan_application_counts,
    get_partner_loan_status_overview,
    get_partner_team_application_overview,
    get_today_application_status_counts,
    get_user_hierarchy_counts,
)
from .decorators import subadmin_required
from .role_decorators import admin_required


def _no_cache_response(payload):
    response = JsonResponse(payload)
    response['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    response['Pragma'] = 'no-cache'
    return response


@login_required
@require_GET
@admin_required
def api_admin_chart_data(request):
    """Admin dashboard chart payloads (global data)."""
    chart = (request.GET.get('chart') or 'all').strip().lower()
    payload = {'success': True, 'generated_at': __import__('django.utils.timezone', fromlist=['timezone']).timezone.now().isoformat()}

    if chart in {'all', 'monthly'}:
        payload['monthly_loan_applications'] = get_monthly_loan_application_counts(12)
    if chart in {'all', 'hierarchy'}:
        payload['user_hierarchy_overview'] = get_user_hierarchy_counts()
    if chart in {'all', 'today'}:
        payload['today_applications_by_status'] = get_today_application_status_counts()

    return _no_cache_response(payload)


@login_required(login_url='login')
@require_GET
@subadmin_required
def api_partner_chart_data(request):
    """Partner dashboard chart payloads (partner hierarchy only)."""
    chart = (request.GET.get('chart') or 'all').strip().lower()
    payload = {'success': True, 'generated_at': __import__('django.utils.timezone', fromlist=['timezone']).timezone.now().isoformat()}

    if chart in {'all', 'loan_status'}:
        payload['partner_loan_status_overview'] = get_partner_loan_status_overview(request.user)
    if chart in {'all', 'team'}:
        payload['partner_team_application_overview'] = get_partner_team_application_overview(request.user)

    return _no_cache_response(payload)
