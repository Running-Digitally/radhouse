"""Render only the pinned old-runtime state compatibility pair into a new directory.

Schema31 stores tool pins as prompt blobs. The unchanged old runtime can delete
those blobs during ordinary prompt updates; its rollback must use this pair.
This does not restore or downgrade a database and never touches vault data.
"""
import ast
import hashlib
import json
from pathlib import Path

PACKAGE = Path(__file__).parent


def replace_exact(text, old, new):
    if text.count(old) != 1:
        raise ValueError("hermes_rollback_context_mismatch")
    return text.replace(old, new, 1)


def render(root):
    lock = json.loads((PACKAGE / "rollback-state31-lock.json").read_text())
    raw = {name: (Path(root) / name).read_bytes() for name in lock["files"]}
    for name, value in raw.items():
        if hashlib.sha256(value).hexdigest() != lock["files"][name]["before_sha256"]:
            raise ValueError("hermes_rollback_source_mismatch")
    before = raw['hermes_state.py'].decode()
    after = replace_exact(before,
        '"SELECT 1 FROM sessions WHERE sessions.system_prompt_hash = system_prompts.hash)"',
        '"SELECT 1 FROM sessions WHERE sessions.system_prompt_hash = system_prompts.hash "\n'
        '            "OR sessions.tool_names = system_prompts.hash)"')
    before_sessions = raw['hermes_state_sessions.py'].decode()
    after_sessions = replace_exact(before_sessions,
        '"SELECT s.*, COALESCE(sp.prompt, s.system_prompt) AS _system_prompt_resolved "\n'
        '            "FROM sessions s LEFT JOIN system_prompts sp ON sp.hash = s.system_prompt_hash WHERE s.id = ?",',
        '"SELECT s.*, COALESCE(sp.prompt, s.system_prompt) AS _system_prompt_resolved, "\n'
        '            "COALESCE(tp.prompt, s.tool_names) AS _tool_names_resolved "\n'
        '            "FROM sessions s LEFT JOIN system_prompts sp ON sp.hash = s.system_prompt_hash "\n'
        '            "LEFT JOIN system_prompts tp ON tp.hash = s.tool_names WHERE s.id = ?",')
    start = after_sessions.index('    def get_session(self, session_id: str)')
    end = after_sessions.index('\n    def ', start+10)
    section = after_sessions[start:end]
    changed = replace_exact(section,
        '        return self._session_row_dict(row) if row else None',
        '''        if row is None:
            return None
        data = self._session_row_dict(row)
        payload = data.pop("_tool_names_resolved")
        try:
            pin = json.loads(payload) if payload else None
        except (ValueError, TypeError):
            pin = None
        if isinstance(pin, dict):
            # New builds store complete definitions; this old runtime expects
            # only their stable order of names and rebuilds its own schemas.
            tools = pin.get("tools")
            names = [tool.get("function", {}).get("name") for tool in tools
                     if isinstance(tool, dict) and isinstance(tool.get("function"), dict)] if isinstance(tools, list) else []
            data["tool_names"] = json.dumps([name for name in names if isinstance(name, str) and name])
        else:
            data["tool_names"] = payload if isinstance(pin, list) else None
        return data''')
    after_sessions = after_sessions[:start]+changed+after_sessions[end:]
    output = {"hermes_state.py": after, "hermes_state_sessions.py": after_sessions}
    for name, source in output.items():
        ast.parse(source)
        if hashlib.sha256(source.encode()).hexdigest() != lock["files"][name]["after_sha256"]:
            raise ValueError("hermes_rollback_result_mismatch")
    return output


def write(root, destination):
    """Caller composes these checked bytes into its paired rollback release."""
    output = render(root)
    destination = Path(destination)
    destination.mkdir(mode=0o700, parents=True, exist_ok=False)
    for name, source in output.items():
        (destination / name).write_text(source)
    return {name: hashlib.sha256(source.encode()).hexdigest() for name, source in output.items()}
