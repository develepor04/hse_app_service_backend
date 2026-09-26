"""
Seeds application-level roles used for API authentication / authorisation.
`level` determines access hierarchy — higher = more privileged.
"""

from seeds.base import BaseSeeder
from app.models.app_role import AppRole


class AppRolesSeeder(BaseSeeder):
    model      = AppRole
    unique_key = "name"

    def data(self) -> list[dict]:
        return [
            {
                "name":        "superadmin",
                "label":       "Super Administrator",
                "description": "Unrestricted access to all modules, settings, and user management.",
                "level":       100,
            },
            {
                "name":        "admin",
                "label":       "Administrator",
                "description": "Full access to all HSE data; can manage users but cannot change system settings.",
                "level":       80,
            },
            {
                "name":        "safety_manager",
                "label":       "HSE Manager",
                "description": "Can create and approve permits, incidents, CAPA actions, and safety walks.",
                "level":       60,
            },
            {
                "name":        "supervisor",
                "label":       "Supervisor",
                "description": "Can issue permits, log incidents and near-misses, manage shift schedules.",
                "level":       40,
            },
            {
                "name":        "operator",
                "label":       "Worker",
                "description": "Can view assigned data and submit incident/near-miss reports.",
                "level":       20,
            },
            {
                "name":        "auditor",
                "label":       "Auditor",
                "description": "Can view assigned audits, run checklists, and submit compliance findings.",
                "level":       30,
            },
            {
                "name":        "viewer",
                "label":       "Viewer",
                "description": "Read-only access across all modules.",
                "level":       10,
            },
        ]
