"""Pure Telegram owner-only strategy toggle handler (no network/bot token).
Call handle_message(user_id, text, owner_id) from existing bot's text handler.
This module does NOT install a webhook or start a Telegram bot.
"""
from __future__ import annotations
from engine.strategy_registry import read,toggle
from strategies.catalog import SPECS

def handle_message(user_id, text, owner_id):
    if not owner_id or str(user_id)!=str(owner_id):return '⛔ هذا الأمر للمالك فقط.'
    parts=str(text).strip().split()
    if not parts:return ''
    cmd=parts[0].split('@')[0]
    if cmd=='/gold_strategies':
        d=read()['strategies'];enabled=sum(v['enabled'] for v in d.values())
        # Telegram max message size: show summary, use /gold_on ID or /gold_off ID
        groups=['{}: {}'.format(k,'🟢' if v['enabled'] else '🔴') for k,v in sorted(d.items())]
        page=int(parts[1]) if len(parts)==2 and parts[1].isdigit() else 1
        pages=(len(groups)+24)//25
        if page<1 or page>pages:return f'اختر صفحة بين 1 و{pages} عبر /gold_strategies 2'
        return f'🥇 استراتيجيات الذهب: {enabled}/{len(d)} مفعّلة في محرك الديمو | صفحة {page}/{pages}\n'+'\n'.join(groups[(page-1)*25:page*25])+'\nللتنقل: /gold_strategies 2'
    if cmd in ('/gold_on','/gold_off'):
        if len(parts)!=2:return 'الطريقة: /gold_on STRATEGY_ID أو /gold_off STRATEGY_ID'
        sid=parts[1]
        if sid not in SPECS:return 'معرّف استراتيجية غير موجود.'
        flag=cmd=='/gold_on';toggle(sid,flag)
        return f'{"🟢 تم تفعيل" if flag else "🔴 تم إيقاف"} {sid} في محرك الفحص وإشارات الديمو. إرسال الأمر يخضع لطبقات المخاطرة واشتراطات حساب الوسيط.'
    return ''
