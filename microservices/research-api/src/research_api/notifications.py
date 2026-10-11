"""Idempotent research notifications; invoke from an approved background worker.

Email delivery is intentionally owned by the authenticated Next.js email worker.
This module writes in-app notifications and daily digest outbox entries only.
"""
import hashlib
from datetime import datetime, timezone
from . import storage

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
