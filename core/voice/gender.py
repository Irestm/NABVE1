from __future__ import annotations

from modules.user_profile import service_layer as profile_service_layer
from modules.user_profile.domain import DEFAULT_GENDER, GENDER_KEY
from modules.user_profile.uow import ProfileUnitOfWork


def get_user_gender() -> str:
    return profile_service_layer.get_fact(ProfileUnitOfWork(), GENDER_KEY) or DEFAULT_GENDER


def pick(male: str, female: str) -> str:
    return female if get_user_gender() == "female" else male
