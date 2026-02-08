from django.contrib.auth.decorators import login_required
from .models import Agent

def agent_profile_context(request):
    """
    Context processor to pass agent profile information to all templates
    """
    context = {
        'agent_profile': None,
    }
    
    if request.user.is_authenticated and request.user.role == 'agent':
        try:
            agent = Agent.objects.get(user=request.user)
            context['agent_profile'] = agent
        except Agent.DoesNotExist:
            pass
    
    return context
