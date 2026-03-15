try:
    import pymysql
    pymysql.install_as_MySQLdb()
except ImportError:
    # Allow startup before dependency installation.
    pass

# This will make sure the app is always imported when
# Django starts so that shared_task will use this app.
try:
    from .celery import app as celery_app
    __all__ = ('celery_app',)
except ImportError:
    # Celery not installed yet
    pass
