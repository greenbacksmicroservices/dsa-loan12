#!/usr/bin/env python
import time
time.sleep(3)  # Wait for server

import urllib.request
import urllib.parse
import http.cookiejar
import re

cookie_jar = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cookie_jar))

try:
    login_page = opener.open('http://127.0.0.1:8000/admin-login/', timeout=5)
    login_html = login_page.read().decode('utf-8')
    
    csrf_match = re.search(r"name=['\"]csrfmiddlewaretoken['\"] value=['\"]([^'\"]+)['\"]", login_html)
    if csrf_match:
        csrf_token = csrf_match.group(1)
        
        login_data = urllib.parse.urlencode({
            'email': 'admindsa@gmail.com',
            'password': 'admin123',
            'csrfmiddlewaretoken': csrf_token
        }).encode('utf-8')
        
        login_response = opener.open('http://127.0.0.1:8000/admin-login/', login_data, timeout=5)
        login_response.read()
        
        response = opener.open('http://127.0.0.1:8000/admin/all-loans/', timeout=5)
        content = response.read()
        
        print(f'✓ Status: {response.status}')
        print(f'✓ Content length: {len(content)} bytes')
        print(f'✓ Has DOCTYPE: {b"<!DOCTYPE" in content[:100]}')
        print(f'✓ First 150 chars: {content[:150].decode("utf-8", errors="ignore")}')
    else:
        print('✗ CSRF token not found')
except Exception as e:
    print(f'✗ Error: {e}')
