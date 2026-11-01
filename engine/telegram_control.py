"""Optional owner-only Telegram polling for a *dedicated* gold demo bot.
Never enable polling on a Telegram token that already has an active webhook.
Uses standard HTTPS API; not needed for broker trading operations.
"""
from __future__ import annotations
import json,os,time,urllib.request,urllib.parse
from pathlib import Path
from engine.admin_commands import handle_message
from engine.strategy_registry import read

ROOT=Path(__file__).resolve().parents[1]

class TelegramController:
    def __init__(self,token,owner_id,offset_path=ROOT/'runtime/telegram.offset'):
        if not token or not owner_id:raise ValueError('Missing bot credentials')
        self.token=str(token);self.owner_id=str(owner_id);self.offset_path=Path(offset_path)
        self.offset=int(self.offset_path.read_text()) if self.offset_path.exists() else 0

    def api(self,method,payload):
        url=f'https://api.telegram.org/bot{self.token}/{method}'
        body=urllib.parse.urlencode(payload).encode()
        req=urllib.request.Request(url,data=body)
        with urllib.request.urlopen(req,timeout=35) as response:
            data=json.load(response)
        if not data.get('ok'):raise RuntimeError('Telegram API returned an error')
        return data.get('result')

    def once(self):
        updates=self.api('getUpdates',{'offset':self.offset,'timeout':20,'allowed_updates':'["message"]'})
        for u in updates:
            uid=int(u.get('update_id',0))
            if uid<self.offset:continue
            self.offset=uid+1
            msg=u.get('message') or {}
            sender=(msg.get('from') or {}).get('id')
            chat=(msg.get('chat') or {}).get('id')
            if str(sender)==self.owner_id and str(chat)==self.owner_id:
                text=str(msg.get('text',''))
                if text.startswith('/gold_'):
                    reply=handle_message(sender,text,self.owner_id)
                    if reply:self.api('sendMessage',{'chat_id':chat,'text':reply})
            self.offset_path.parent.mkdir(parents=True,exist_ok=True)
            tmp=self.offset_path.with_suffix('.tmp');tmp.write_text(str(self.offset));tmp.replace(self.offset_path)
        return len(updates)

    def loop(self):
        while True:
            try:self.once()
            except Exception as exc:
                print('TELEGRAM_CONTROL_WARNING',type(exc).__name__,flush=True)
                time.sleep(15)

def start_optional():
    token=os.environ.get('GOLD_TELEGRAM_BOT_TOKEN')
    owner=os.environ.get('GOLD_TELEGRAM_OWNER_ID')
    if not token or not owner or os.environ.get('GOLD_TELEGRAM_POLL')!='YES':return False
    import threading
    ctrl=TelegramController(token,owner)
    threading.Thread(target=ctrl.loop,daemon=True,name='gold_owner_bot').start()
    return True


def notify_owner(message):
    """One-way owner notification; safe even if Telegram bot uses an existing webhook."""
    token=os.environ.get('GOLD_TELEGRAM_BOT_TOKEN')
    owner=os.environ.get('GOLD_TELEGRAM_OWNER_ID')
    if not token or not owner:return False
    try:
        TelegramController(token,owner).api('sendMessage',{'chat_id':owner,'text':str(message)[:3900]})
        return True
    except Exception:
        return False
