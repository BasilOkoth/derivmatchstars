from pathlib import Path
p=Path('bot.html')
s=p.read_text(encoding='utf-8')
needle='''        async function toggleBot() {
            const serverMode = window.SERVER_EXECUTION?.enabled === true;'''
assert s.count(needle)==1, 'Expected exactly one toggleBot() declaration'
if 'async function dmsStartConfirmedRealTrade()' in s:
    print('Already installed')
    raise SystemExit(0)
insert='''        // REAL purchases are individually reviewed; the DEMO cycle is never started.
        async function dmsStartConfirmedRealTrade() {
            const cfg = serverSessionConfigFromUi();
            const accounts = await serverExecRequest('/auth/platform/me');
            const account = (accounts.accounts || []).find(a =>
                String(a.account_type || '').toLowerCase() === 'real'
            );
            if (!account) throw new Error('No REAL Deriv account connected');
            const digit = Number(sessionState.sessionDigit ?? document.getElementById('predictedDigit')?.value);
            if (!Number.isInteger(digit) || digit < 0 || digit > 9)
                throw new Error('Choose a digit 0–9 before requesting a REAL quote');
            const stake = Number(cfg.base_stake);
            if (!Number.isFinite(stake) || stake <= 0)
                throw new Error('Enter a valid REAL stake');

            // Existing session is reused to avoid accidentally resetting a contract.
            const sessions = await serverExecRequest('/sessions');
            let row = (sessions || []).find(x =>
                String(x.account_id) === String(account.account_id) &&
                String(x.symbol) === String(cfg.symbol) &&
                String(x.account_mode || '').toUpperCase() === 'REAL'
            );
            if (row && (row.running || row.open_contract_id))
                throw new Error('Existing REAL session is active. Stop and reconcile it first.');
            if (!row) {
                row = await serverExecRequest('/sessions', {
                    method: 'POST',
                    body: {account_id:account.account_id, symbol:cfg.symbol,
                           base_stake:stake, multiplier:cfg.multiplier, max_trades:cfg.max_trades}
                });
            }
            const sid = Number(row.id);
            if (!Number.isInteger(sid) || sid <= 0) throw new Error('Could not establish REAL session');
            const quoted = await serverExecRequest(`/real-manual/sessions/${sid}/quote`, {
                method:'POST', body:{digit, stake}
            });
            const approved = window.confirm(
                `REAL-MONEY PURCHASE — authorize ONE trade only?\\n\\n` +
                `Account: ${quoted.account_id}\\nMarket: ${quoted.symbol}\\n` +
                `Digit: ${quoted.digit}\\nStake: ${quoted.stake}\\n` +
                `Ask price: ${quoted.ask_price}\\n\\n` +
                `Recovery and subsequent REAL purchases are NOT automatic.`
            );
            if (!approved) {
                log('REAL quote displayed but purchase was cancelled', 'SYSTEM');
                return false;
            }
            const bought = await serverExecRequest(`/real-manual/sessions/${sid}/confirm`, {
                method:'POST', body:{confirmation_token:quoted.confirmation_token, confirm:true}
            });
            log(`REAL contract ${bought.contract_id} purchased; no automatic recovery`, 'SYSTEM');
            alert(`REAL purchase submitted. Contract ${bought.contract_id}. Verify official settlement before another trade.`);
            return true;
        }

'''
s=s.replace(needle,insert+'''        async function toggleBot() {
            const serverMode = window.SERVER_EXECUTION?.enabled === true;
            if (serverMode && !window.isBotRunning &&
                String(serverSessionConfigFromUi().requested_mode || '').toUpperCase() === 'REAL') {
                try { await dmsStartConfirmedRealTrade(); }
                catch (err) {
                    log(`REAL manual purchase unavailable: ${err.message}`, 'ERROR');
                    alert(`REAL manual purchase unavailable: ${err.message}`);
                }
                return;
            }''',1)
p.write_text(s,encoding='utf-8')
print('Updated full bot.html with REAL per-purchase confirmation')
