"""SQLite idempotency ledger: uncertain outcomes stay blocked until manual reconcile."""
from __future__ import annotations
import sqlite3,json
from pathlib import Path

class IntentStore:
 def __init__(self,path):
  self.path=str(path)
  if self.path != ':memory:': Path(self.path).parent.mkdir(parents=True,exist_ok=True)
  with sqlite3.connect(self.path) as c:
   c.execute('CREATE TABLE IF NOT EXISTS intents (client_order_id TEXT PRIMARY KEY, account_id INTEGER NOT NULL, symbol_id INTEGER NOT NULL, status TEXT NOT NULL, payload TEXT NOT NULL, updated_at TEXT DEFAULT CURRENT_TIMESTAMP)')
 def reserve(self,order):
  with sqlite3.connect(self.path,timeout=10,isolation_level='IMMEDIATE') as c:
   c.execute('BEGIN IMMEDIATE')
   key=order['client_order_id']
   if c.execute('SELECT 1 FROM intents WHERE client_order_id=?',(key,)).fetchone():return False
   c.execute('INSERT INTO intents (client_order_id,account_id,symbol_id,status,payload) VALUES (?, ?, ?, ?, ?)',(key,order['ctidTraderAccountId'],order['symbolId'],'SUBMIT_UNCERTAIN',json.dumps(order)))
   return True
 def update(self,key,status):
  if status not in ('CONFIRMED','REJECTED','RECONCILED_ABSENT','FILLED','CLOSED'):
   raise ValueError('invalid status; uncertain state deliberately not retryable')
  with sqlite3.connect(self.path) as c:
   if c.execute('UPDATE intents SET status=?,updated_at=CURRENT_TIMESTAMP WHERE client_order_id=?',(status,key)).rowcount!=1:raise KeyError(key)
 def all(self):
  with sqlite3.connect(self.path) as c:return c.execute('SELECT client_order_id,status FROM intents ORDER BY updated_at DESC').fetchall()
