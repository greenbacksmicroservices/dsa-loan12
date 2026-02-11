from django import template
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta

register = template.Library()


@register.filter
def get_item(dictionary, key):
    """
    Custom filter to get a dictionary item by key in templates
    Usage: {{ dictionary|get_item:key }}
    """
    if isinstance(dictionary, dict):
        return dictionary.get(key)
    return None


@register.filter
def add_months(date, months):
    """
    Custom filter to add months to a date
    Usage: {{ date|add_months:months_value }}
    """
    try:
        if isinstance(months, str):
            months = int(months)
        if date:
            return date + relativedelta(months=months)
    except (TypeError, ValueError):
        pass
    return date
