#!/usr/bin/env python
"""
Agent Dashboard API Views - Add to core/views.py

Place these functions at the end of the file, before the last closing.
"""

api_views_code = '''
# ============ AGENT DASHBOARD APIS ============

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_agent_profile(request):
    """Get agent profile information"""
    if request.user.role != 'agent':
        return Response({'error': 'Not authorized'}, status=403)
    
    try:
        agent = Agent.objects.get(user=request.user)
        data = {
            'user': {
                'username': request.user.username,
                'first_name': request.user.first_name,
                'last_name': request.user.last_name,
                'email': request.user.email,
                'phone': request.user.phone,
            },
            'status': agent.status,
            'loans_count': LoanApplication.objects.filter(assigned_agent=agent).count()
        }
        return Response(data)
    except Agent.DoesNotExist:
        return Response({'error': 'Agent not found'}, status=404)

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_agent_dashboard_stats(request):
    """Get agent dashboard statistics"""
    if request.user.role != 'agent':
        return Response({'error': 'Not authorized'}, status=403)
    
    try:
        agent = Agent.objects.get(user=request.user)
        loans = LoanApplication.objects.filter(assigned_agent=agent)
        
        stats = {
            'total_assigned': loans.count(),
            'processing': loans.filter(status='waiting_for_processing').count(),
            'approved': loans.filter(status='approved').count(),
            'rejected': loans.filter(status='rejected').count(),
            'disbursed': loans.filter(status='disbursed').count(),
        }
        return Response(stats)
    except Agent.DoesNotExist:
        return Response({'error': 'Agent not found'}, status=404)

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_agent_status_chart(request):
    """Get agent status distribution chart data"""
    if request.user.role != 'agent':
        return Response({'error': 'Not authorized'}, status=403)
    
    try:
        agent = Agent.objects.get(user=request.user)
        loans = LoanApplication.objects.filter(assigned_agent=agent)
        
        data = {
            'labels': ['Processing', 'Approved', 'Rejected', 'Disbursed'],
            'values': [
                loans.filter(status='waiting_for_processing').count(),
                loans.filter(status='approved').count(),
                loans.filter(status='rejected').count(),
                loans.filter(status='disbursed').count(),
            ]
        }
        return Response(data)
    except Agent.DoesNotExist:
        return Response({'error': 'Agent not found'}, status=404)

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_agent_trend_chart(request):
    """Get agent 30-day trend chart data"""
    if request.user.role != 'agent':
        return Response({'error': 'Not authorized'}, status=403)
    
    from datetime import timedelta, datetime
    
    try:
        agent = Agent.objects.get(user=request.user)
        loans = LoanApplication.objects.filter(assigned_agent=agent)
        
        # Generate last 30 days data
        labels = []
        values = []
        
        for i in range(29, -1, -1):
            date = datetime.now() - timedelta(days=i)
            date_str = date.strftime('%m-%d')
            count = loans.filter(created_at__date=date.date()).count()
            labels.append(date_str)
            values.append(count)
        
        data = {
            'labels': labels,
            'values': values
        }
        return Response(data)
    except Agent.DoesNotExist:
        return Response({'error': 'Agent not found'}, status=404)

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_my_assigned_loans(request):
    """Get agent's assigned loans (paginated)"""
    if request.user.role not in ['agent', 'employee']:
        return Response({'error': 'Not authorized'}, status=403)
    
    try:
        if request.user.role == 'agent':
            agent = Agent.objects.get(user=request.user)
            loans = LoanApplication.objects.filter(assigned_agent=agent).order_by('-created_at')
        else:
            # Employee
            loans = LoanApplication.objects.filter(assigned_employee=request.user).order_by('-created_at')
        
        # Pagination
        paginator = Paginator(loans, 10)
        page = request.GET.get('page', 1)
        loans_page = paginator.get_page(page)
        
        data = {
            'count': paginator.count,
            'results': [
                {
                    'id': loan.id,
                    'applicant_name': loan.applicant.first_name + ' ' + loan.applicant.last_name if loan.applicant else 'N/A',
                    'loan_amount': str(loan.loan_amount),
                    'status': loan.status,
                    'created_at': loan.created_at.isoformat() if loan.created_at else None,
                }
                for loan in loans_page
            ]
        }
        return Response(data)
    except Agent.DoesNotExist:
        return Response({'error': 'Agent not found'}, status=404)
'''

print("Copy and paste this code at the end of core/views.py:\n")
print(api_views_code)
