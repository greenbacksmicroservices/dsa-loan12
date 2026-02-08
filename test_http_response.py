import urllib.request
import urllib.parse
import http.cookiejar
import re

# Create cookie jar and opener
cookie_jar = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cookie_jar))

try:
    # First get the login page to extract CSRF token
    login_page = opener.open('http://127.0.0.1:8000/admin-login/', timeout=5)
    login_html = login_page.read().decode('utf-8')
    
    # Extract CSRF token
    csrf_match = re.search(r"name=['\"]csrfmiddlewaretoken['\"] value=['\"]([^'\"]+)['\"]", login_html)
    if csrf_match:
        csrf_token = csrf_match.group(1)
        print('CSRF token found:', csrf_token[:20] + '...')
        
        # Login with CSRF token
        login_data = urllib.parse.urlencode({
            'email': 'admindsa@gmail.com',
            'password': 'admin123',
            'csrfmiddlewaretoken': csrf_token
        }).encode('utf-8')
        
        login_response = opener.open('http://127.0.0.1:8000/admin-login/', login_data, timeout=5)
        print('Login status:', login_response.status)
        login_response.read()  # Read and discard
        
        # Get admin page
        response = opener.open('http://127.0.0.1:8000/admin/all-loans/', timeout=5)
        
        print('\n=== RESPONSE HEADERS ===')
        for header, value in response.headers.items():
            print(f'{header}: {value}')
        
        content = response.read()
        
        print('\n=== RESPONSE BODY ===')
        print('Admin all-loans status:', response.status)
        print('Content length:', len(content))
        print('Has DOCTYPE:', b'<!DOCTYPE' in content[:100])
        if len(content) > 0:
            print('First 300 chars:')
            print(content[:300])
        else:
            print('Content is empty!')
    else:
        print('CSRF token not found in login page')
except Exception as e:
    print('Error:', e)
    import traceback
    traceback.print_exc()

