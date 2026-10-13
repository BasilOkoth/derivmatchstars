"""Run from the ROOT of the CURRENT GitHub checkout, after copying app/real_manual.py.
Creates COMPLETE updated app/__init__.py and app/main.py in place; backs up originals.
"""
from pathlib import Path
import shutil

root = Path.cwd()
init = root / 'app' / '__init__.py'
main = root / 'app' / 'main.py'
manual = root / 'app' / 'real_manual.py'
if not (init.exists() and main.exists() and manual.exists()):
    raise SystemExit('Run at repository root and copy app/real_manual.py before continuing')
old = init.read_text()
updated = old.replace('MultiUserEngine._execute_buy', 'MultiUserEngine._execute_demo_buy')
updated = updated.replace('self._execute_buy(', 'self._execute_demo_buy(')
# Only rename the class method hooks; do NOT rename helper functions or change
# REAL purchase restrictions in engine.py / deriv_ws.py.
if '_execute_buy' in updated:
    print('Review: other helper identifiers still include _execute_buy (expected).')
for path in (init, main):
    shutil.copy2(path, str(path) + '.before-real-manual.bak')
init.write_text(updated)
s = main.read_text()
if 'from .real_manual import router as real_manual_router' not in s:
    s += '\n\n# Explicit, one-purchase-at-a-time REAL API.\nfrom .real_manual import router as real_manual_router\napp.include_router(real_manual_router)\n'
main.write_text(s)
print('Updated app/__init__.py and app/main.py, preserved backups.')
