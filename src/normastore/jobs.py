from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone

from normastore.domain.enums import NotificationStatus, RentalState

REMINDER_EVENTS = (("BEFORE_DUE", -1), ("DUE_TODAY", 0), ("OVERDUE_1", 1), ("OVERDUE_3", 3), ("OVERDUE_7", 7))


def scheduled_reminders(due_date: date) -> list[tuple[str, datetime]]:
    return [
        (event, datetime.combine(due_date + timedelta(days=offset), time(9), tzinfo=timezone.utc))
        for event, offset in REMINDER_EVENTS
    ]


def due_message(title: str, due_date: date, overdue_days: int = 0) -> str:
    if overdue_days:
        return f"NormaStore: '{title}' đã quá hạn {overdue_days} ngày. Vui lòng sắp xếp trả đĩa."
    return f"NormaStore: '{title}' có hạn trả {due_date:%d/%m/%Y}. Cảm ơn bạn."


@dataclass(frozen=True)
class NotificationRun:
    sent: int = 0
    skipped: int = 0
    failed: int = 0


def current_reminder_event(due_date: date, today: date) -> str:
    overdue_days = (today - due_date).days
    if overdue_days >= 7:
        return "OVERDUE_7"
    if overdue_days >= 3:
        return "OVERDUE_3"
    if overdue_days >= 1:
        return "OVERDUE_1"
    if overdue_days == 0:
        return "DUE_TODAY"
    return "BEFORE_DUE"


def process_notification_outbox(
    repository,
    send_email: Callable[[str, str], None] | None,
    send_sms: Callable[[str, str], None] | None,
    now: datetime | None = None,
) -> NotificationRun:
    """Send one currently relevant reminder per rental/channel and mark stale entries."""
    now = now or datetime.now(timezone.utc)
    rows = repository.due_reminders(now)
    grouped = defaultdict(list)
    for row in rows:
        grouped[(row[0].rental_term_id, row[0].channel)].append(row)

    sent = skipped = failed = 0
    for entries in grouped.values():
        outbox, term, line, customer = entries[0]
        if not term or term.state != RentalState.ACTIVE or not line:
            for entry, *_ in entries:
                entry.status = NotificationStatus.SKIPPED
                entry.error = "Dòng thuê không còn hoạt động"
                skipped += 1
            continue
        wanted_event = current_reminder_event(term.due_date, now.date())
        selected = next((entry for entry in entries if entry[0].event == wanted_event), entries[-1])
        for entry, *_ in entries:
            if entry is not selected[0]:
                entry.status = NotificationStatus.SKIPPED
                entry.error = "Đã gộp vào nhắc nhở hiện tại"
                skipped += 1
        event_row = selected[0]
        overdue_days = max(0, (now.date() - term.due_date).days)
        body = due_message(line.title_snapshot, term.due_date, overdue_days)
        try:
            if event_row.channel == "EMAIL":
                if not customer.email_opt_in or not customer.email or not send_email:
                    raise RuntimeError("Email chưa cấu hình hoặc khách không đăng ký nhận")
                send_email(customer.email, body)
            else:
                if not customer.sms_opt_in or not send_sms:
                    raise RuntimeError("SMS chưa cấu hình hoặc khách không đăng ký nhận")
                send_sms(customer.phone, body)
            event_row.status = NotificationStatus.SENT
            event_row.error = None
            event_row.attempts += 1
            sent += 1
        except Exception as exc:
            event_row.status = NotificationStatus.FAILED
            event_row.error = str(exc)[:1000]
            event_row.attempts += 1
            failed += 1
    return NotificationRun(sent=sent, skipped=skipped, failed=failed)
