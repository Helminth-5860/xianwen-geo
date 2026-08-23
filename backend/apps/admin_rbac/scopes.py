from rest_framework.exceptions import NotFound

from apps.users.models import User


def has_customer_owner(user) -> bool:
    if user.is_staff or user.is_superuser:
        return False
    return User.objects.filter(
        pk=user.pk,
        customer_assignment__owner_admin__user__is_superuser=False,
        customer_assignment__owner_admin__role__isnull=False,
    ).exists()


def scoped_customers(user, context):
    """Return the business users governed by the current platform identity.

    CustomerAssignment is the sole authorization boundary.  ``User.tenant``
    remains a compatibility/branding attribute and must never widen access.
    """
    queryset = User.objects.filter(is_staff=False, is_superuser=False)
    if user.is_superuser:
        return queryset
    return queryset.filter(customer_assignment__owner_admin=context.profile)


def scoped_customer_or_404(user, context, customer_id):
    try:
        return scoped_customers(user, context).get(pk=customer_id)
    except User.DoesNotExist as exc:
        raise NotFound from exc
