"""Operator-run registration of one explicit public key and conversation."""
import re

import psycopg

from radhouse.domain.tasks import Rejected


def bind_key(store, *, principal_id: str, pubkey: str, conversation_id: str, project_id: str):
    """Rotate one person's conversation key without creating any other grant."""
    if re.fullmatch(r"[a-f0-9]{64}", pubkey) is None:
        raise Rejected("invalid_buzz_key", 422)
    try:
        return _bind_key(store, principal_id, pubkey, conversation_id, project_id)
    except psycopg.Error:
        raise Rejected("database_unavailable", 503) from None


def _bind_key(store, principal_id, pubkey, conversation_id, project_id):
    with store.transaction() as tx:
        access = tx.access(principal_id)
        project = tx.project(project_id)
        if access is None or not access.active or project_id not in access.projects or project is None or project.state != "active":
            raise Rejected("access_denied", 403)
        existing = tx.binding("buzz", pubkey, conversation_id)
        if existing and existing.principal_id != principal_id:
            raise Rejected("key_owned_by_another_person", 403)
        connection = tx._connection
        # This operator command requires the PostgreSQL implementation. It is
        # deliberately not an operator HTTP route or a runtime worker command.
        rows = connection.execute("SELECT subject,revision,active,project_id FROM channel_bindings "
            "WHERE channel='buzz' AND principal_id=%s AND conversation_id=%s FOR UPDATE",
            (principal_id, conversation_id)).fetchall()
        active = [row for row in rows if row["active"]]
        if (len(active) == 1 and active[0]["subject"] == pubkey
                and active[0]["project_id"] == project_id):
            return active[0]["revision"]
        revision = max((row["revision"] for row in rows), default=0) + 1
        connection.execute("UPDATE channel_bindings SET active=false,revision=%s "
            "WHERE channel='buzz' AND principal_id=%s AND conversation_id=%s", (revision, principal_id, conversation_id))
        connection.execute("INSERT INTO channel_bindings(channel,subject,conversation_id,principal_id,project_id,revision,active) "
            "VALUES ('buzz',%s,%s,%s,%s,%s,true) ON CONFLICT(channel,subject,conversation_id) DO UPDATE "
            "SET project_id=EXCLUDED.project_id,revision=EXCLUDED.revision,active=true",
            (pubkey, conversation_id, principal_id, project_id, revision))
        return revision
