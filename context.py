def build_context(event):
    raw = event.message.text
    return {
        "event": event,
        "user": event.source.user_id,
        "group_id": get_source_id(event),
        "raw_text": raw,
        "text": raw.strip(),
        "lines": raw.strip().splitlines(),
        "db": load_db(),
    }
