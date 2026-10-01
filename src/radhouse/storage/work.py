"""Work queries participate in the existing short serialized application transaction."""
from dataclasses import asdict
from datetime import datetime

from psycopg.types.json import Jsonb

from radhouse.domain.tasks import Rejected
from radhouse.domain.work import ArtifactManifest, VerificationReceipt, WorkBlocker, WorkItem


def encode(value):
    def normalize(item):
        if isinstance(item, datetime):
            return item.isoformat()
        if isinstance(item, dict):
            return {key: normalize(part) for key, part in item.items()}
        if isinstance(item, (tuple, list)):
            return [normalize(part) for part in item]
        return item
    return Jsonb(normalize(asdict(value)))


def decode(row, kind):
    if row is None:
        return None
    value = dict(row['snapshot'])
    for key in ('created_at', 'updated_at'):
        if key in value:
            value[key] = datetime.fromisoformat(value[key])
    if kind is WorkItem:
        value['blockers'] = tuple(WorkBlocker(**part) for part in value['blockers'])
    return kind(**value)


class WorkQueries:
    def work_item(self, work_id: str) -> WorkItem | None:
        return decode(self._connection.execute('SELECT snapshot FROM public.work_items WHERE work_id=%s', (work_id,)).fetchone(), WorkItem)

    def work_for_task(self, task_id: str) -> WorkItem | None:
        return decode(self._connection.execute('SELECT w.snapshot FROM public.work_items w JOIN public.work_steps s USING(work_id) WHERE s.task_id=%s', (task_id,)).fetchone(), WorkItem)

    def work_items(self, owner_id: str, project_id: str) -> list[WorkItem]:
        return [decode(row, WorkItem) for row in self._connection.execute('SELECT snapshot FROM public.work_items WHERE owner_id=%s AND project_id=%s ORDER BY snapshot->>\'created_at\' DESC, work_id', (owner_id, project_id)).fetchall()]

    def insert_work(self, work: WorkItem) -> None:
        self._connection.execute('INSERT INTO public.work_items(work_id,owner_id,project_id,accountable_bot_id,state,scope_revision,state_revision,snapshot) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)', (work.work_id,work.owner_id,work.project_id,work.accountable_bot_id,work.state,work.scope_revision,work.state_revision,encode(work)))
        self._connection.execute('INSERT INTO public.work_steps(work_id,scope_revision,step_key,task_id) VALUES (%s,%s,%s,%s)', (work.work_id,work.scope_revision,'deliver-artifact',work.task_id))

    def save_work(self, work: WorkItem, expected: int) -> None:
        result = self._connection.execute('UPDATE public.work_items SET state=%s,scope_revision=%s,state_revision=%s,snapshot=%s WHERE work_id=%s AND state_revision=%s', (work.state,work.scope_revision,work.state_revision,encode(work),work.work_id,expected))
        if result.rowcount != 1:
            raise Rejected('stale_work_state')

    def insert_artifact(self, artifact: ArtifactManifest, content: str) -> None:
        self._connection.execute('INSERT INTO public.work_artifacts(artifact_id,work_id,task_id,attempt_id,sha256,content,snapshot) VALUES (%s,%s,%s,%s,%s,%s,%s)', (artifact.artifact_id,artifact.work_id,artifact.task_id,artifact.attempt_id,artifact.sha256,content,encode(artifact)))

    def artifact(self, artifact_id: str) -> tuple[ArtifactManifest, str] | None:
        row = self._connection.execute('SELECT snapshot,content FROM public.work_artifacts WHERE artifact_id=%s', (artifact_id,)).fetchone()
        return (decode(row, ArtifactManifest), row['content']) if row else None

    def insert_verification(self, receipt: VerificationReceipt) -> None:
        self._connection.execute('INSERT INTO public.work_verifications(verification_id,work_id,task_id,artifact_id,snapshot) VALUES (%s,%s,%s,%s,%s)', (receipt.verification_id,receipt.work_id,receipt.task_id,receipt.artifact_id,encode(receipt)))
