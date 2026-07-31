from rest_framework.exceptions import NotFound

from apps.users.models import User

from .models import AdminRole


def scoped_customers(user, context):
    queryset = User.objects.filter(is_staff=False, is_superuser=False)
    if user.is_superuser:
        return queryset
    role = context.profile.role
    if role is None:
        return queryset.none()
    if role.data_scope == AdminRole.DataScope.ALL:
        return queryset
    if role.data_scope == AdminRole.DataScope.OWN:
        return queryset.filter(customer_assignment__owner_admin=context.profile)
    return queryset.filter(
        customer_assignment__owner_admin__role=role,
    )


def scoped_customer_or_404(user, context, customer_id):
    try:
        return scoped_customers(user, context).get(pk=customer_id)
    except User.DoesNotExist as exc:
        raise NotFound from exc
