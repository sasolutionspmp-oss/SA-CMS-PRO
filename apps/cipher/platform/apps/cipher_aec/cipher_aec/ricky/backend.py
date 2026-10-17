"""Bridge to the same authoritative services used by manual product workflows."""

from .contracts import Authority, RickyError, digest
from .tools import CITATION, validate


class FrappeBackend:
    def require_effects_enabled(self):
        from cipher_aec.governance.context import require_effects_enabled
        require_effects_enabled()

    def authority(self, company, project, *, user=None):
        from cipher_aec.api.contracts import version_of
        from cipher_aec.governance.context import authority_fingerprint, current_actor, require_project, session_authority_reference
        actor = current_actor(user)
        record = require_project(company, project, ability="ricky.run", actor=actor)
        return Authority(actor.user, actor.person_id, company, project, version_of(record), authority_fingerprint(actor, company, project),
                         session_authority_reference(actor) if user is None else None)

    def require_permission(self, authority, ability):
        self._actor(authority, ability)

    def verify_session(self, authority):
        from cipher_aec.governance.context import current_actor, require_session_authority
        require_session_authority(current_actor(authority.user), authority.session_reference)

    def lock_scope(self, authority, ability):
        from cipher_aec.governance.context import current_actor, require_project
        actor = current_actor(authority.user, lock=True)
        if actor.person_id != authority.person:
            raise RickyError("stale_authority", "The requesting identity changed.")
        require_project(authority.company, authority.project, ability=ability, actor=actor, lock=True)

    def _actor(self, authority, ability="project.read"):
        from cipher_aec.governance.context import current_actor, require_project
        actor = current_actor(authority.user)
        if actor.person_id != authority.person:
            raise RickyError("stale_authority", "The requesting identity changed.")
        require_project(authority.company, authority.project, ability=ability, actor=actor)
        return actor

    def project(self, authority):
        from cipher_aec.api.contracts import version_of
        from cipher_aec.governance.context import require_project
        actor = self._actor(authority)
        record = require_project(authority.company, authority.project, actor=actor)
        return {"project": record.name, "company": record.company, "title": record.project_name, "revision": version_of(record)}

    @staticmethod
    def _citation(value):
        allowed = set(CITATION["properties"]) - {"citation_id"}
        result = {key: value[key] for key in allowed if key in value}
        if "revision_number" in result:
            result["revision_number"] = str(result["revision_number"])
        result["citation_id"] = digest({key: result[key] for key in ("revision_id", "page", "excerpt_sha256")})
        validate(CITATION, result, "citation")
        return result

    def search_documents(self, authority, query, limit):
        from cipher_aec.documents.service import search_documents
        actor = self._actor(authority, "document.read")
        return [self._citation(row) for row in search_documents(authority.company, authority.project, query, limit=limit, actor=actor)]

    def verify_sources(self, authority, sources):
        if not sources:
            return
        from cipher_aec.documents.service import get_citation, get_document
        actor = self._actor(authority, "document.read")
        for source in sources:
            validate(CITATION, source, "citation")
            record = get_document(authority.company, source["document_id"], actor=actor)["document"]
            if record["project"] != authority.project or record["company"] != authority.company:
                raise RickyError("not_found", "This evidence is outside the current project.")
            current = self._citation(get_citation(authority.company, source["revision_id"], source["page"], excerpt_sha256=source["excerpt_sha256"], actor=actor))
            if any(current[key] != source[key] for key in ("citation_id", "source_sha256", "excerpt_sha256", "document_id", "revision_id", "page", "excerpt")):
                raise RickyError("stale_source", "A cited source no longer matches the recorded evidence.")

    def create_task(self, authority, fields, operation_id, sources):
        import frappe
        from cipher_aec.api.contracts import version_of
        from cipher_aec.governance.context import authority_fingerprint, require_project, require_session_authority
        from cipher_aec.projects.service import create_task
        self._actor(authority, "task.create")
        if frappe.session.user != authority.user:
            raise RickyError("forbidden", "Task approval requires the requesting person's active session.")
        def guard(actor, locked_project):
            # Current locking reads are essential on MariaDB REPEATABLE-READ: an
            # earlier precheck must not make a later effect use an old snapshot.
            require_project(authority.company, authority.project, ability="ricky.run", actor=actor, lock=True)
            require_project(authority.company, authority.project, ability="document.read", actor=actor, lock=True)
            require_session_authority(actor, authority.session_reference, lock=True)
            if actor.person_id != authority.person or authority_fingerprint(actor, authority.company, authority.project, lock=True) != authority.authority_version:
                raise RickyError("stale_authority", "Project authority changed after the proposal was prepared.")
            if version_of(locked_project) != authority.project_revision:
                raise RickyError("stale_source", "The project changed after the proposal was prepared.")
            self.verify_sources(authority, sources)
        return create_task(company=authority.company, project=authority.project, operation_id=operation_id,
                           expected_version=authority.project_revision, subject=fields["subject"], description=fields["description"], guard=guard)
