"""
Seeds HSE operational roles from the Excel test data (ROLE001–ROLE013).
These map to job titles used in the `employees` table.
"""

from seeds.base import BaseSeeder
from app.models.role import Role


class RolesSeeder(BaseSeeder):
    model      = Role
    unique_key = "id"

    def data(self) -> list[dict]:
        return [
            # id matches the numeric part of ROLE001..ROLE013
            {
                "id": 1,
                "role_name":        "Plant Manager",
                "job_category":     "Senior Management",
                "authority_level":  5,
                "permit_authority": "Yes",
                "safety_signatory": "Yes",
            },
            {
                "id": 2,
                "role_name":        "Safety Manager",
                "job_category":     "Senior Management",
                "authority_level":  5,
                "permit_authority": "Yes",
                "safety_signatory": "Yes",
            },
            {
                "id": 3,
                "role_name":        "Operations Manager",
                "job_category":     "Senior Management",
                "authority_level":  5,
                "permit_authority": "Yes",
                "safety_signatory": "Yes",
            },
            {
                "id": 4,
                "role_name":        "Department Supervisor",
                "job_category":     "Supervision",
                "authority_level":  4,
                "permit_authority": "Yes",
                "safety_signatory": "Yes",
            },
            {
                "id": 5,
                "role_name":        "Shift Leader",
                "job_category":     "Supervision",
                "authority_level":  3,
                "permit_authority": "Yes",
                "safety_signatory": "No",
            },
            {
                "id": 6,
                "role_name":        "Assembly Technician",
                "job_category":     "Technician",
                "authority_level":  2,
                "permit_authority": "No",
                "safety_signatory": "No",
            },
            {
                "id": 7,
                "role_name":        "Quality Engineer",
                "job_category":     "Technician",
                "authority_level":  2,
                "permit_authority": "No",
                "safety_signatory": "No",
            },
            {
                "id": 8,
                "role_name":        "Test Technician",
                "job_category":     "Technician",
                "authority_level":  2,
                "permit_authority": "No",
                "safety_signatory": "No",
            },
            {
                "id": 9,
                "role_name":        "Maintenance Technician",
                "job_category":     "Technician",
                "authority_level":  2,
                "permit_authority": "Yes",
                "safety_signatory": "No",
            },
            {
                "id": 10,
                "role_name":        "Machine Operator",
                "job_category":     "Operator",
                "authority_level":  1,
                "permit_authority": "No",
                "safety_signatory": "No",
            },
            {
                "id": 11,
                "role_name":        "Production Operator",
                "job_category":     "Operator",
                "authority_level":  1,
                "permit_authority": "No",
                "safety_signatory": "No",
            },
            {
                "id": 12,
                "role_name":        "Administrative Assistant",
                "job_category":     "Admin",
                "authority_level":  1,
                "permit_authority": "No",
                "safety_signatory": "No",
            },
            {
                "id": 13,
                "role_name":        "Contractor - Specialist",
                "job_category":     "Contractor",
                "authority_level":  1,
                "permit_authority": "No",
                "safety_signatory": "No",
            },
        ]
