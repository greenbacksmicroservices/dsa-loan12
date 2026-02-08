#!/usr/bin/env python
import os

# Read the urls.py file
with open('core/urls.py', 'r') as f:
    content = f.read()

# Check if admin_dashboard line exists
if "path('admin/dashboard/'" not in content:
    print("admin_dashboard line NOT found - adding it...")
    # Find and replace the section
    old_section = """path('admin/logout/', views.admin_logout_view, name='admin_logout'),
    path('admin/new-entry-assign/', views.admin_new_entry_assign, name='admin_new_entry_assign'),"""
    
    new_section = """path('admin/logout/', views.admin_logout_view, name='admin_logout'),
    path('admin/dashboard/', admin_views.admin_dashboard, name='admin_dashboard'),
    path('admin/new-entry-assign/', views.admin_new_entry_assign, name='admin_new_entry_assign'),"""
    
    if old_section in content:
        content = content.replace(old_section, new_section)
        with open('core/urls.py', 'w') as f:
            f.write(content)
        print("✓ Successfully added admin_dashboard line")
    else:
        print("✗ Could not find the section to replace")
else:
    print("✓ admin_dashboard line already exists")

# Verify
with open('core/urls.py', 'r') as f:
    verify = f.read()
    if "path('admin/dashboard/'" in verify:
        print("✓ Verification: admin_dashboard is present in file")
    else:
        print("✗ Verification failed")
