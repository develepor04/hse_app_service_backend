from typing import List, Optional
from app.repositories.base import BaseRepository
from app.models.incident import Incident


class IncidentRepository(BaseRepository[Incident]):
    model_class = Incident

    def _filtered_query(
        self, org_id: int,
        status: Optional[str] = None, incident_type: Optional[str] = None,
        severity: Optional[str] = None, source: Optional[str] = None,
        q: Optional[str] = None,
    ):
        query = self._db.query(self.model_class).filter(self.model_class.organisation_id == org_id)
        if status:
            query = query.filter(self.model_class.investigation_status == status)
        if incident_type:
            query = query.filter(self.model_class.incident_type == incident_type)
        if severity:
            query = query.filter(self.model_class.severity == severity)
        if source:
            # Real column now (migration 077) — was a GPS-presence guess that
            # mislabelled every GPS-less row "Web App" before a web creation
            # path existed to actually produce one.
            query = query.filter(self.model_class.source == source)
        if q:
            like = f"%{q}%"
            query = query.filter(self.model_class.description.ilike(like))
        return query

    def get_filtered_by_org(
        self, org_id: int, skip: int = 0, limit: int = 100,
        status: Optional[str] = None, incident_type: Optional[str] = None,
        severity: Optional[str] = None, source: Optional[str] = None,
        q: Optional[str] = None,
    ) -> List[Incident]:
        return (
            self._filtered_query(org_id, status, incident_type, severity, source, q)
            .order_by(self.model_class.id.desc())
            .offset(skip)
            .limit(limit)
            .all()
        )

    def count_filtered_by_org(
        self, org_id: int,
        status: Optional[str] = None, incident_type: Optional[str] = None,
        severity: Optional[str] = None, source: Optional[str] = None,
        q: Optional[str] = None,
    ) -> int:
        return self._filtered_query(org_id, status, incident_type, severity, source, q).count()

    def get_all(self, skip: int = 0, limit: int = 100) -> List[Incident]:
        return (
            self._db.query(self.model_class)
            .order_by(self.model_class.id.desc())
            .offset(skip)
            .limit(limit)
            .all()
        )

    def get_all_by_org(self, org_id: int, skip: int = 0, limit: int = 100) -> List[Incident]:
        return (
            self._db.query(self.model_class)
            .filter(self.model_class.organisation_id == org_id)
            .order_by(self.model_class.id.desc())
            .offset(skip)
            .limit(limit)
            .all()
        )

    def count_all(self) -> int:
        return self._db.query(self.model_class).count()

    def count_by_org(self, org_id: int) -> int:
        return (
            self._db.query(self.model_class)
            .filter(self.model_class.organisation_id == org_id)
            .count()
        )
