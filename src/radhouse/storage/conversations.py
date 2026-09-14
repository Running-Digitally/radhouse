"""Conversation queries on the controller's existing transaction and DML role."""

from dataclasses import asdict

from psycopg.types.json import Jsonb

from radhouse.domain.conversations import (
    BUZZ_THREAD_ANCESTRY_REJECTED,
    ConversationLink,
    ConversationMessage,
    MessageRoute,
)
from radhouse.domain.tasks import Rejected
from radhouse.domain.tasks import InputFile


class ConversationQueries:
    def conversation_link(self, link_id):
        row = self._connection.execute(
            "SELECT snapshot FROM conversation_links WHERE link_id=%s", (link_id,)
        ).fetchone()
        return ConversationLink(**row["snapshot"]) if row else None

    def conversation_links(self, principal_id=None):
        rows = self._connection.execute(
            "SELECT snapshot FROM conversation_links WHERE (%s::text IS NULL OR principal_id=%s) ORDER BY link_id LIMIT 100",
            (principal_id, principal_id),
        ).fetchall()
        return [ConversationLink(**row["snapshot"]) for row in rows]

    def conversation_link_for_channel(self, channel_id):
        row = self._connection.execute(
            "SELECT snapshot FROM conversation_links WHERE channel_id=%s", (channel_id,)
        ).fetchone()
        return ConversationLink(**row["snapshot"]) if row else None

    def conversation_enrollment(self, link_id):
        row = self._connection.execute(
            "SELECT enrollment FROM conversation_links WHERE link_id=%s", (link_id,)
        ).fetchone()
        return row["enrollment"] if row else None

    def save_conversation_enrollment(self, link_id, enrollment):
        self._connection.execute(
            "UPDATE conversation_links SET enrollment=%s WHERE link_id=%s",
            (Jsonb(enrollment), link_id),
        )

    def save_conversation_link(self, link):
        existing = self.conversation_link(link.link_id)
        if existing is not None:
            if existing != link:
                raise Rejected("conversation_link_conflict")
            return
        self._connection.execute(
            "INSERT INTO conversation_links(link_id,channel_id,principal_id,bot_id,project_id,snapshot,cursor_time) VALUES(%s,%s,%s,%s,%s,%s,%s)",
            (
                link.link_id,
                link.channel_id,
                link.principal_id,
                link.bot_id,
                link.project_id,
                Jsonb(asdict(link)),
                link.activated_at,
            ),
        )

    def conversation_status(self, link_id):
        return self._connection.execute(
            "SELECT cursor_time,scan_time,scan_id,error_code FROM conversation_links WHERE link_id=%s",
            (link_id,),
        ).fetchone()

    def conversation_scan_progress(self, link_id, cursor):
        self._connection.execute(
            "UPDATE conversation_links SET scan_time=%s,scan_id=%s WHERE link_id=%s",
            (*(cursor or (None, None)), link_id),
        )

    def conversation_progress(self, link_id, *, cursor=None, error=None):
        self._connection.execute(
            "UPDATE conversation_links SET cursor_time=GREATEST(cursor_time,COALESCE(%s,cursor_time)),error_code=%s WHERE link_id=%s",
            (cursor, error, link_id),
        )

    def conversation_message(self, message_id):
        row = self._connection.execute(
            "SELECT * FROM conversation_messages WHERE message_id=%s", (message_id,)
        ).fetchone()
        return self._conversation_row(row) if row else None

    def conversation_reply(self, link_id, event_id):
        row = self._connection.execute(
            "SELECT m.* FROM conversation_messages m LEFT JOIN conversation_outbox o ON o.message_id=m.message_id "
            "WHERE m.link_id=%s AND (m.message_id=%s OR o.event->>'id'=%s) LIMIT 1",
            (link_id, event_id, event_id),
        ).fetchone()
        return self._conversation_row(row) if row else None

    @staticmethod
    def _conversation_row(row):
        snapshot = dict(row["snapshot"])
        snapshot["files"] = tuple(
            InputFile(**value) for value in snapshot.get("files", ())
        )
        return {
            "message": ConversationMessage(**snapshot),
            "route": MessageRoute(**row["route"]) if row["route"] else None,
            "event": row["source_event"],
            "processed": row["processed"],
            "sequence": row["sequence"],
        }

    def save_conversation_message(
        self, message, *, route=None, event=None, processed=False
    ):
        old = self.conversation_message(message.message_id)
        if old is not None:
            if (
                old["message"].link_id,
                old["message"].author,
                old["message"].content,
                old["message"].source,
            ) != (message.link_id, message.author, message.content, message.source):
                raise Rejected("conversation_message_conflict")
            self._connection.execute(
                "UPDATE conversation_messages SET task_id=%s,snapshot=%s,route=COALESCE(route,%s),processed=%s WHERE message_id=%s",
                (
                    message.task_id,
                    Jsonb(asdict(message)),
                    Jsonb(asdict(route)) if route else None,
                    processed,
                    message.message_id,
                ),
            )
        else:
            self._connection.execute(
                "INSERT INTO conversation_messages(message_id,link_id,task_id,snapshot,route,source_event,processed) VALUES(%s,%s,%s,%s,%s,%s,%s)",
                (
                    message.message_id,
                    message.link_id,
                    message.task_id,
                    Jsonb(asdict(message)),
                    Jsonb(asdict(route)) if route else None,
                    Jsonb(event) if event else None,
                    processed,
                ),
            )

    def conversation_history(
        self, link_id, *, after=0, limit=100, before=None, tail=False
    ):
        if not 1 <= limit <= 200 or after < 0 or before is not None and before < 1:
            raise Rejected("invalid_history_window", 422)
        if tail or before is not None:
            rows = self._connection.execute(
                "SELECT * FROM conversation_messages WHERE link_id=%s "
                "AND (%s::bigint IS NULL OR sequence<%s) ORDER BY sequence DESC LIMIT %s",
                (link_id, before, before, limit),
            ).fetchall()[::-1]
        else:
            rows = self._connection.execute(
                "SELECT * FROM conversation_messages WHERE link_id=%s AND sequence>%s ORDER BY sequence LIMIT %s",
                (link_id, after, limit),
            ).fetchall()
        return [self._conversation_row(row) for row in rows]

    def conversation_pending(self, link_id, limit=20):
        rows = self._connection.execute(
            "SELECT * FROM conversation_messages WHERE link_id=%s AND NOT processed ORDER BY sequence LIMIT %s",
            (link_id, min(max(limit, 1), 100)),
        ).fetchall()
        return [self._conversation_row(row) for row in rows]

    def conversation_task_messages(self, link_id):
        rows = self._connection.execute(
            "SELECT DISTINCT m.task_id FROM conversation_messages m JOIN tasks t ON t.task_id=m.task_id "
            "WHERE m.link_id=%s AND (t.snapshot->>'phase'!='closed' OR m.task_id IN "
            "(SELECT task_id FROM conversation_messages WHERE link_id=%s AND task_id IS NOT NULL ORDER BY sequence DESC LIMIT 100)) "
            "ORDER BY m.task_id LIMIT 201",
            (link_id, link_id),
        ).fetchall()
        if len(rows) > 200:
            raise Rejected("conversation_active_task_limit", 409)
        return [row["task_id"] for row in rows]

    def conversation_event(self, message_id):
        row = self._connection.execute(
            "SELECT event FROM conversation_outbox WHERE message_id=%s", (message_id,)
        ).fetchone()
        return row["event"] if row else None

    def conversation_focus(self, link):
        # Only owner selections move focus. Delayed bot progress and random
        # task UUID ordering cannot replace the selected context.
        row = self._connection.execute(
            "SELECT task_id FROM conversation_messages WHERE link_id=%s "
            "AND snapshot->>'author'=%s AND processed AND task_id IS NOT NULL "
            "ORDER BY (snapshot->>'created_at')::bigint DESC, sequence DESC LIMIT 1",
            (link.link_id, link.principal_id),
        ).fetchone()
        return row["task_id"] if row else None

    def conversation_unannounced_publications(self, link_id, limit=20):
        rows = self._connection.execute(
            "SELECT p.task_id FROM publications p WHERE EXISTS "
            "(SELECT 1 FROM conversation_messages m WHERE m.link_id=%s AND m.task_id=p.task_id) "
            "AND NOT EXISTS (SELECT 1 FROM conversation_messages m WHERE m.link_id=%s "
            "AND m.message_id='publication:' || p.publication_id) ORDER BY p.publication_id LIMIT %s",
            (link_id, link_id, min(max(limit, 1), 100)),
        ).fetchall()
        return [row["task_id"] for row in rows]

    def conversation_task_anchor(self, link, task_id):
        row = self._connection.execute(
            "SELECT message_id FROM conversation_messages WHERE link_id=%s AND task_id=%s "
            "AND snapshot->>'author'=%s AND route->>'action'='start' AND processed "
            "ORDER BY sequence LIMIT 1", (link.link_id, task_id, link.principal_id),
        ).fetchone()
        return row["message_id"] if row else None

    def conversation_guidance_messages(self, link, task_id):
        rows = self._connection.execute(
            "SELECT message_id FROM conversation_messages WHERE link_id=%s AND route->>'task_id'=%s "
            "AND snapshot->>'author'=%s AND route->>'action'='guide' "
            "ORDER BY sequence DESC LIMIT 64", (link.link_id, task_id, link.principal_id),
        ).fetchall()
        return [row["message_id"] for row in rows]

    def conversation_changed_tasks(self, link_id, limit=20):
        rows = self._connection.execute(
            "SELECT t.task_id FROM tasks t WHERE EXISTS "
            "(SELECT 1 FROM conversation_messages m WHERE m.link_id=%s AND m.task_id=t.task_id) "
            "AND t.state_revision>COALESCE((SELECT MAX((m.snapshot->>'task_state_revision')::bigint) "
            "FROM conversation_messages m WHERE m.link_id=%s AND m.task_id=t.task_id),0) "
            "ORDER BY t.task_id LIMIT %s",
            (link_id, link_id, min(max(limit, 1), 100)),
        ).fetchall()
        return [row["task_id"] for row in rows]

    def conversation_enqueue(self, delivery_key, link_id, message_id, event):
        old = self._connection.execute(
            "SELECT event FROM conversation_outbox WHERE delivery_key=%s",
            (delivery_key,),
        ).fetchone()
        if old:
            # Reuse retained signature/time across retries; caller cannot replace it.
            return old["event"]
        self._connection.execute(
            "INSERT INTO conversation_outbox(delivery_key,link_id,message_id,event) VALUES(%s,%s,%s,%s)",
            (delivery_key, link_id, message_id, Jsonb(event)),
        )
        return event

    def conversation_outgoing(self, link_id, limit=20):
        return self._connection.execute(
            "SELECT o.* FROM conversation_outbox o JOIN conversation_messages m ON m.message_id=o.message_id "
            "WHERE o.link_id=%s AND NOT o.delivered AND o.error_code IS DISTINCT FROM %s "
            "ORDER BY m.sequence LIMIT %s",
            (link_id, BUZZ_THREAD_ANCESTRY_REJECTED, min(max(limit, 1), 100)),
        ).fetchall()

    def conversation_undelivered_messages(self, link_id, limit=20):
        rows = self._connection.execute(
            "SELECT m.* FROM conversation_messages m LEFT JOIN conversation_outbox o ON o.message_id=m.message_id "
            "WHERE m.link_id=%s AND m.processed AND o.delivery_key IS NULL "
            "AND NOT (m.snapshot->>'source'='buzz') ORDER BY m.sequence LIMIT %s",
            (link_id, min(max(limit, 1), 100)),
        ).fetchall()
        return [self._conversation_row(row) for row in rows]

    def conversation_acknowledge(self, delivery_key, *, error=None):
        self._connection.execute(
            "UPDATE conversation_outbox SET delivered=%s,error_code=%s WHERE delivery_key=%s",
            (error is None, error, delivery_key),
        )
