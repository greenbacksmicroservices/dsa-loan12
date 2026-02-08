import os
import sys
import django
from django.test import RequestFactory

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'dsa_loan_management.settings')
sys.path.insert(0, 'd:\\WEB DEVIOPMENT\\DSA')
django.setup()

from core.admin_views import admin_all_loans
from core.models import User
from django.contrib.auth import get_user_model

# Create a test request
factory = RequestFactory()
request = factory.get('/admin/all-loans/')

# Get the admin user
User_model = get_user_model()
try:
    user = User_model.objects.get(email='admindsa@gmail.com')
    request.user = user
    print(f'User found: {user.email}, is_authenticated: {user.is_authenticated}, role: {user.role}')
    
    # Call the view
    response = admin_all_loans(request)
    
    print(f'Response type: {type(response)}')
    print(f'Response status: {response.status_code}')
    print(f'Response content length: {len(response.content)}')
    
    if hasattr(response, 'streaming'):
        print(f'Is streaming: {response.streaming}')
    
    # Check if response is actually a HttpResponse
    content = response.content if hasattr(response, 'content') else str(response)
    print(f'Has DOCTYPE: {b"<!DOCTYPE" in content[:100]}')
    print(f'Content type: {response.get("Content-Type", "Unknown")}')
    
except User_model.DoesNotExist:
    print('User not found')
except Exception as e:
    print(f'Error: {e}')
    import traceback
    traceback.print_exc()
