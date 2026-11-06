from .services import permitted_businesses


def workspace_navigation(request):
    return {'has_multiple_businesses': request.user.is_authenticated and
            permitted_businesses(request.user).count() > 1}
