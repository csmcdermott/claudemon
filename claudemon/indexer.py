import json
import os
from pathlib import Path

import claudemon.db as db

_QUERY_TEXT_MAX = 60


def _parse_timestamp(ts_str: str) -> int:
    """Convert ISO 8601 string to unix milliseconds."""
    from datetime import datetime
    dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
    return int(dt.timestamp() * 1000)


def _is_new_query(record: dict) -> bool:
    """True if this user record starts a new query (not a tool result or meta)."""
    return (
        record.get("type") == "user"
        and not record.get("isMeta", False)
        and not record.get("toolUseResult")
        and not record.get("isSidechain", True)
    )


def _is_clear_command(record: dict) -> bool:
    """True if this user record is a /clear command."""
    content = record.get("message", {}).get("content", [])
    if isinstance(content, list):
        text = "".join(
            c.get("text", "") for c in content if isinstance(c, dict) and c.get("type") == "text"
        )
    elif isinstance(content, str):
        text = content
    else:
        return False
    return text.strip() == "/clear"


def _extract_prompt_text(record: dict) -> str:
    """First text content of a user message, whitespace-collapsed. '' if none."""
    content = record.get("message", {}).get("content", [])
    if isinstance(content, list):
        text = " ".join(
            c.get("text", "")
            for c in content
            if isinstance(c, dict) and c.get("type") == "text"
        )
    elif isinstance(content, str):
        text = content
    else:
        return ""
    return " ".join(text.split())


def index_file(
    conn,
    file_path: Path,
    task_gap_minutes: int = 30,
) -> None:
    """Parse a JSONL session file and write new records to the DB.

    Uses byte-offset cursor for incremental parsing: only reads bytes
    appended since the last call.
    """
    file_path = Path(file_path)
    if not file_path.exists():
        return

    stat = os.stat(file_path)
    cursor = db.get_cursor(conn, str(file_path))

    if cursor and cursor["last_modified"] == stat.st_mtime:
        return  # file unchanged

    # Default session_id from filename; will be overridden by first record with sessionId
    session_id = file_path.stem
    project = file_path.parent.name  # slug like "-Users-foo-bar-MyProject"

    # Restore incremental state from cursor
    last_offset = cursor["last_offset"] if cursor else 0
    task_num = cursor["last_task_num"] if cursor else 0
    query_num = cursor["last_query_num"] if cursor else 0
    last_branch = cursor["last_branch"] if cursor else None
    last_timestamp = cursor["last_timestamp"] if cursor else 0

    # If file shrank (shouldn't happen but be safe), reset
    if last_offset > stat.st_size:
        last_offset = 0
        task_num = 0
        query_num = 0
        last_branch = None
        last_timestamp = 0

    gap_ms = task_gap_minutes * 60 * 1000
    current_query_id: str | None = None
    session_project: str | None = None
    session_started_at: int | None = None
    pending_title: str | None = None
    session_id_resolved = False

    with open(file_path, "rb") as f:
        if last_offset > 0:
            f.seek(last_offset)

        for raw_line in f:
            line = raw_line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue

            # Extract session_id from records (overrides filename stem)
            if not session_id_resolved and record.get("sessionId"):
                session_id = record["sessionId"]
                session_id_resolved = True

            rec_type = record.get("type")

            # Extract project from cwd on first record that has it
            if session_project is None and record.get("cwd"):
                session_project = Path(record["cwd"]).name or project

            # Track session timestamps
            ts_str = record.get("timestamp")
            ts = _parse_timestamp(ts_str) if ts_str else None
            if ts and session_started_at is None:
                session_started_at = ts

            if rec_type == "ai-title":
                pending_title = record.get("aiTitle")
                # Also resolve session_id from ai-title record if not yet resolved
                if not session_id_resolved and record.get("sessionId"):
                    session_id = record["sessionId"]
                    session_id_resolved = True
                continue

            if rec_type == "user" and _is_new_query(record):
                branch = record.get("gitBranch")
                is_clear = _is_clear_command(record)

                # Determine if this user message is a task boundary
                is_new_task = (
                    task_num == 0  # first task
                    or is_clear
                    or (branch and last_branch and branch != last_branch)
                    or (ts and last_timestamp and (ts - last_timestamp) > gap_ms)
                )

                if is_new_task:
                    task_num += 1
                    query_num = 1
                else:
                    query_num += 1

                short_id = session_id[:6]
                current_query_id = f"{short_id}:{task_num}:{query_num}"

                prompt_text = _extract_prompt_text(record)
                if prompt_text:
                    db.upsert_query(
                        conn, session_id, current_query_id,
                        prompt_text[:_QUERY_TEXT_MAX],
                    )

                last_branch = branch
                if ts:
                    last_timestamp = ts
                continue

            if rec_type == "assistant":
                msg = record.get("message", {})
                usage = msg.get("usage", {})
                model = msg.get("model", "unknown")

                input_tokens = usage.get("input_tokens", 0)
                output_tokens = usage.get("output_tokens", 0)
                cache_creation = usage.get("cache_creation_input_tokens", 0)
                cache_read = usage.get("cache_read_input_tokens", 0)

                if ts is None:
                    continue

                # Ensure session exists
                proj = session_project or project
                db.upsert_session(
                    conn, session_id, proj, pending_title,
                    session_started_at or ts, ts,
                    last_branch,
                )
                pending_title = None  # consumed

                short_id = session_id[:6]
                task_id = f"{short_id}:{task_num}" if task_num > 0 else f"{short_id}:1"
                query_id = current_query_id or f"{short_id}:1:1"

                db.insert_message(
                    conn, session_id, task_id, query_id, ts, model,
                    input_tokens, output_tokens, cache_creation, cache_read,
                )

                for block in msg.get("content", []):
                    if block.get("type") != "tool_use":
                        continue
                    block_name = block.get("name", "")
                    if block_name == "Skill":
                        tool_type = "skill"
                        tool_name = block.get("input", {}).get("skill", "unknown")
                    elif block_name.startswith("mcp__"):
                        tool_type = "mcp"
                        service = block_name.split("__")[1]
                        if service.startswith("plugin_"):
                            service = service.removeprefix("plugin_")
                            tool_name = service.split("_")[0].lower()
                        elif service.startswith("claude_ai_"):
                            tool_name = service.removeprefix("claude_ai_").lower().replace("_", "-")
                        else:
                            tool_name = service.split("_")[0].lower()
                    else:
                        continue
                    db.insert_tool_use(
                        conn, session_id, query_id, ts,
                        tool_type, tool_name, output_tokens,
                    )

                if ts:
                    last_timestamp = ts

        new_offset = f.tell()

    # If title arrived after all assistant messages, update session
    if pending_title:
        db.upsert_session(
            conn, session_id, session_project or project, pending_title,
            session_started_at or 0, last_timestamp, last_branch,
        )

    db.update_cursor(
        conn, str(file_path), new_offset, stat.st_mtime,
        task_num, query_num, last_branch, last_timestamp,
    )


def index_all(conn, projects_dir: Path, task_gap_minutes: int = 30) -> None:
    """Index every JSONL file under projects_dir."""
    for jsonl_file in sorted(projects_dir.glob("**/*.jsonl")):
        index_file(conn, jsonl_file, task_gap_minutes=task_gap_minutes)
