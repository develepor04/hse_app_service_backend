from sqlalchemy import and_


def org_scoped_join(fk_condition, org_column, org_id):
    """Join condition that also requires the joined row's own org to match.

    Employee (and similar lookup) tables use a global, cross-tenant primary key,
    so joining on the foreign key alone can pull back a same-numbered row that
    belongs to a *different* organisation (e.g. showing another tenant's
    employee name as a CAPA action's assignee). Use this wherever a join target
    is itself an org-scoped table.

    When org_id is None (superadmin / unscoped request) no org constraint is
    added, since there is no single tenant to constrain the join to.
    """
    if org_id is None:
        return fk_condition
    return and_(fk_condition, org_column == org_id)
