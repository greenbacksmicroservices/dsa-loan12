"""
URL configuration for dsa_loan_management project.
"""
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

from . import error_handlers

handler400 = error_handlers.handler400
handler403 = error_handlers.handler403
handler404 = error_handlers.handler404
handler500 = error_handlers.handler500

urlpatterns = [
    # Custom admin views & API routes (MUST come before Django admin panel)
    path('', include('core.urls')),
    
    # Django admin panel (use different prefix to avoid conflict with custom /admin/ routes)
    path('superadmin/', admin.site.urls),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)


