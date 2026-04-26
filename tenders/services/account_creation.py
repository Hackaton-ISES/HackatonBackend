from django.contrib.auth.models import User
from django.db import transaction

from tenders.models import Company, UserProfile, ensure_user_profile
from tenders.services.risk_scoring import analyze_company


@transaction.atomic
def create_company_account(
    *,
    company_name: str,
    username: str,
    password: str,
    email: str = '',
    first_name: str = '',
    last_name: str = '',
) -> User:
    company = Company.objects.create(name=company_name)
    user = User.objects.create_user(
        username=username,
        email=email,
        password=password,
        first_name=first_name,
        last_name=last_name,
    )
    profile = ensure_user_profile(user)
    profile.role = UserProfile.Role.COMPANY
    profile.company = company
    profile.external_id = company.external_id
    profile.save(update_fields=['role', 'company', 'external_id', 'updated_at'])
    analyze_company(company)
    return user
