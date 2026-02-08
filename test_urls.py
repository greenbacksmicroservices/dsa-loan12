import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'dsa_loan_management.settings')
django.setup()

try:
    from dsa_loan_management import urls
    print("✓ URLs imported successfully")
    print(f"✓ urlpatterns type: {type(urls.urlpatterns)}")
    print(f"✓ Number of patterns: {len(urls.urlpatterns)}")
    for i, pattern in enumerate(urls.urlpatterns):
        print(f"  [{i}] {pattern.pattern}")
except Exception as e:
    print(f"✗ Error: {e}")
    import traceback
    traceback.print_exc()
