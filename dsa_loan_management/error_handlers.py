from django.shortcuts import render


def error_message_handler(request, status_code, title, message):
    return render(
        request,
        'error_message.html',
        {
            'status_code': status_code,
            'title': title,
            'message': message,
        },
        status=status_code,
    )


def handler400(request, exception=None):
    return error_message_handler(
        request,
        400,
        'Bad Request',
        'The request could not be processed. Please check your input and try again.',
    )


def handler403(request, exception=None):
    return error_message_handler(
        request,
        403,
        'Access Denied',
        'You do not have permission to access this page.',
    )


def handler404(request, exception=None):
    return error_message_handler(
        request,
        404,
        'Page Not Found',
        'The page you are looking for does not exist or may have been moved.',
    )


def handler500(request):
    return error_message_handler(
        request,
        500,
        'Server Error',
        'Something went wrong on our side. Please try again in a few moments.',
    )
