"""Idempotent research notifications; invoke from an approved background worker.

Email delivery is intentionally owned by the authenticated Next.js email worker.
This module writes in-app notifications and daily digest outbox entries only.

An outbox entry moves through these states, and only along these arrows:

    pending --> sending --> delivered
       |           |
       |           +--> pending      (the send failed: back in the queue)
       +--> cancelled                (email alerts were turned off)

``sending`` is claimed before the email goes out, so an entry whose delivery could
not be acknowledged afterwards is never sent twice, and ``cancelled`` means an alert
queued while alerts were off can never be mailed later in a burst. A claim that is
neither delivered nor released within CLAIM_TIMEOUT (the job died mid-run) goes
back to ``pending`` the next time the queue is read, so no alert is stranded.
"""
import hashlib
from datetime import datetime, timedelta, timezone
from . import storage

CLAIM_TIMEOUT = timedelta(minutes=15)

OUTBOX_TRANSITIONS = {
    'pending': {'sending', 'cancelled', 'delivered'},  # pending -> delivered: clients from before 'sending'
    'sending': {'delivered', 'pending'},
    'delivered': set(),
    'cancelled': set(),
}


class OutboxTransitionError(ValueError):
    """The entry is not in a state that allows the requested move."""


def publish_research_change(user_id, symbol, assessment, previous_label, preferences):
    label=assessment.get('label')
    if label not in {'buy','hold','sell'} or label==previous_label:return None
    day=datetime.now(timezone.utc).date().isoformat()
    key=hashlib.sha256(f'{user_id}:{symbol}:{label}:{day}'.encode()).hexdigest()[:32]
    value={'id':key,'symbol':symbol,'title':f'{symbol} research changed to {label}','body':'Review the latest attributable evidence and uncertainty before drawing conclusions.','read':False,'created_at':datetime.now(timezone.utc).isoformat()}
    existing={r['key'] for r in storage.read(user_id,'notification')}
    existing_email={r['key'] for r in storage.read(user_id,'email_outbox')}
    if preferences.get('inAppAlerts') and key not in existing:storage.write(user_id,'notification',key,value)
    if preferences.get('emailAlerts') and key not in existing_email:storage.write(user_id,'email_outbox',key,{**value,'status':'pending'})
    return key


def move_outbox(user_id, key, to):
    """Move one outbox entry to ``to``. False when there is no such entry; raises
    OutboxTransitionError when its current state does not allow the move."""
    for row in storage.read(user_id, 'email_outbox'):
        if row['key'] == key:
            current = row['value'].get('status', 'pending')
            if to not in OUTBOX_TRANSITIONS.get(current, set()):
                raise OutboxTransitionError(f'An email that is {current} cannot become {to}.')
            value = {**row['value'], 'status': to}
            if to == 'sending':
                value['claimed_at'] = datetime.now(timezone.utc).isoformat()
            storage.write(user_id, 'email_outbox', key, value)
            return True
    return False


def queued_email(user_id, now=None):
    """Entries waiting to be mailed. Claims older than CLAIM_TIMEOUT are first
    returned to the queue: a job that died after claiming must not strand them."""
    now = now or datetime.now(timezone.utc)
    rows = storage.read(user_id, 'email_outbox')
    stale = []
    for row in rows:
        value = row['value']
        if value.get('status') != 'sending':
            continue
        try:
            claimed = datetime.fromisoformat(value.get('claimed_at', ''))
        except ValueError:
            claimed = None
        if claimed is None or now - claimed >= CLAIM_TIMEOUT:
            stale.append(row)
    if stale:
        storage.apply(user_id, writes=[('email_outbox', r['key'], {**r['value'], 'status': 'pending'}) for r in stale])
        for row in stale:
            row['value'] = {**row['value'], 'status': 'pending'}
    return [r for r in rows if r['value'].get('status', 'pending') == 'pending']


def cancel_pending_email(user_id):
    """Cancel every queued email for a user who turned email alerts off. Returns how many."""
    rows = [r for r in storage.read(user_id, 'email_outbox') if r['value'].get('status', 'pending') == 'pending']
    storage.apply(user_id, writes=[('email_outbox', r['key'], {**r['value'], 'status': 'cancelled'}) for r in rows])
    return len(rows)
