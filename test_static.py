from pathlib import Path
import ast
p=Path(__file__).parent/'app/engine.py'
s=p.read_text()
t=ast.parse(s)
cls=next(x for x in t.body if isinstance(x,ast.ClassDef) and x.name=='MultiUserEngine')
names={x.name:x for x in cls.body if isinstance(x,(ast.FunctionDef,ast.AsyncFunctionDef))}
assert '_persist_fast_tick_outcome' in names
f=names['_handle_strategy_tick']
segment=ast.get_source_segment(s,f)
assert 'active["decided"] = True' in segment
assert 'asyncio.create_task(' in segment
assert '_persist_fast_tick_outcome(int(sid), contract_id, bool(is_win))' in segment
assert 'await self._execute_account_buy' not in segment
assert '_three_trade_locked_target' in s
assert 'previous.status or "").upper() != "SETTLED"' in s
print('AST and execution-boundary static checks passed')
