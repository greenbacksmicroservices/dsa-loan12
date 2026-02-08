"""
URL configuration for dsa_loan_management project.
"""
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    # Custom admin views & API routes (MUST come before Django admin panel)
    path('', include('core.urls')),
    
    # Django admin panel (use different prefix to avoid conflict with custom /admin/ routes)
    path('superadmin/', admin.site.urls),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)


