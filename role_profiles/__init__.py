"""
role_profiles/__init__.py
Registry of every available role profile. To add a new role type: write
role_profiles/<name>.py exporting `PROFILE = RoleProfile(...)` (see base.py
for the shape, product_manager.py/customer_success.py for real examples),
then add it to _PROFILES below. Nothing else needs to change.
"""

from role_profiles.account_executive import PROFILE as _ACCOUNT_EXECUTIVE
from role_profiles.base import PanelPersona, RoleProfile
from role_profiles.chief_of_staff import PROFILE as _CHIEF_OF_STAFF
from role_profiles.customer_success import PROFILE as _CUSTOMER_SUCCESS
from role_profiles.product_manager import PROFILE as _PRODUCT_MANAGER
from role_profiles.software_engineer import PROFILE as _SOFTWARE_ENGINEER

_PROFILES = {
    _PRODUCT_MANAGER.id: _PRODUCT_MANAGER,
    _CUSTOMER_SUCCESS.id: _CUSTOMER_SUCCESS,
    _ACCOUNT_EXECUTIVE.id: _ACCOUNT_EXECUTIVE,
    _CHIEF_OF_STAFF.id: _CHIEF_OF_STAFF,
    _SOFTWARE_ENGINEER.id: _SOFTWARE_ENGINEER,
}

DEFAULT_PROFILE_ID = _PRODUCT_MANAGER.id


def get_profile(profile_id: str) -> RoleProfile:
    """Falls back to the default profile for an unrecognized id rather than
    raising - a stale session_state value (e.g. from before a profile was
    renamed or removed) shouldn't crash the app."""
    return _PROFILES.get(profile_id, _PROFILES[DEFAULT_PROFILE_ID])


def list_profiles() -> list:
    return list(_PROFILES.values())
