import asyncio
import json
import logging
import time
from collections import defaultdict
from typing import Awaitable, Callable, Optional

import websockets

ws_log = logging.getLogger('digitmatchstar.websocket')
MessageCallback = Callable[[dict], Awaitable[None]]


class DerivWS:
    """Account-bound Deriv transport; callback delivery is ordered per subscription.

    Trading requests are never automatically repeated after an uncertain response.
    The reader never awaits strategy callbacks, avoiding request/response deadlocks.
    """

    def __init__(self, url: str):
        self.url = url
        self.ws = None
        self.req_id = 0
        self.pending = {}
        self.reader_task = None
        self.subscriptions = defaultdict(set)
        self.pending_subscription_callbacks = {}
        self._send_lock = asyncio.Lock()
        self._connect_lock = asyncio.Lock()
        self._callback_tasks = set()
        self._subscription_queues = {}
        self._subscription_workers = {}
        self._subscription_callbacks_generation = {}
        self.connection_generation = 0
        self.last_message_at = 0.0
        self.last_tick_at = {}
        self.stream_stats = defaultdict(lambda: {'enqueued': 0, 'processed': 0, 'errors': 0,
                                                  'overflow': 0, 'max_backlog': 0})
        self._proposal_lock = asyncio.Lock()
        self._last_proposal_at = 0.0
        self._proposal_min_interval = 0.90
        self._proposal_cooldown_until = 0.0
        self._rate_limit_streak = 0
        self._buy_lock = asyncio.Lock()
        self._last_buy_at = 0.0
        self._buy_min_interval = 0.48

    def is_open(self):
        if not self.ws or (self.reader_task and self.reader_task.done()):
            return False
        closed = getattr(self.ws, 'closed', None)
        if isinstance(closed, bool):
            return not closed
        state = getattr(self.ws, 'state', None)
        return str(state).upper().endswith('OPEN') if state is not None else True

    async def connect(self):
        if self.is_open():
            return
        async with self._connect_lock:
            if self.is_open():
                return
            self.ws = await websockets.connect(self.url, ping_interval=20, ping_timeout=20,
                                               close_timeout=5, open_timeout=15, max_queue=None)
            self.connection_generation += 1
            self.last_message_at = time.monotonic()
            self.reader_task = asyncio.create_task(self._reader())

    def _stop_dispatchers(self):
        for task in list(self._callback_tasks):
            task.cancel()
        self._callback_tasks.clear()
        for task in list(self._subscription_workers.values()):
            task.cancel()
        self._subscription_workers.clear()
        self._subscription_queues.clear()
        self._subscription_callbacks_generation.clear()
        self.last_tick_at.clear()

    async def close(self):
        if self.reader_task and not self.reader_task.done():
            self.reader_task.cancel()
            try:
                await self.reader_task
            except asyncio.CancelledError:
                pass
            except Exception:
                ws_log.exception('Reader close failed')
        if self.ws:
            try:
                await self.ws.close()
            except Exception:
                ws_log.exception('WebSocket close failed')
        self.ws = None
        for future in list(self.pending.values()):
            if not future.done():
                future.cancel()
        self.pending.clear()
        self.pending_subscription_callbacks.clear()
        self.subscriptions.clear()
        self._stop_dispatchers()

    async def _run_subscription_callback(self, callback, data):
        try:
            await callback(data)
        except asyncio.CancelledError:
            raise
        except Exception:
            ws_log.exception('Deriv subscription callback failed msg_type=%s', data.get('msg_type'))

    def _schedule_subscription_callback(self, callback, data):
        task = asyncio.create_task(self._run_subscription_callback(callback, data))
        self._callback_tasks.add(task)
        task.add_done_callback(self._callback_tasks.discard)

    async def _consume_subscription(self, sub_id, generation):
        queue = self._subscription_queues[sub_id]
        while generation == self.connection_generation:
            data = await queue.get()
            try:
                for callback in tuple(self.subscriptions.get(sub_id, ())):
                    try:
                        await callback(data)
                    except asyncio.CancelledError:
                        raise
                    except Exception:
                        self.stream_stats[sub_id]['errors'] += 1
                        ws_log.exception('DMS_STREAM_CALLBACK_ERROR sub=%s generation=%s type=%s',
                                         sub_id, generation, data.get('msg_type'))
                self.stream_stats[sub_id]['processed'] += 1
            finally:
                queue.task_done()

    def _dispatch_subscription(self, data):
        sub_id = str((data.get('subscription') or {}).get('id') or '')
        if not sub_id or not self.subscriptions.get(sub_id):
            return
        if self._subscription_callbacks_generation.get(sub_id) != self.connection_generation:
            return
        queue = self._subscription_queues.get(sub_id)
        if queue is None:
            queue = asyncio.Queue(maxsize=2048)
            self._subscription_queues[sub_id] = queue
        if data.get('msg_type') == 'tick':
            self.last_tick_at[sub_id] = time.monotonic()
        stats = self.stream_stats[sub_id]
        if queue.full():
            # Never silently discard a market tick: report stream loss and
            # force a visible reconnect/error instead of corrupting tick order.
            stats['overflow'] += 1
            ws_log.error('DMS_STREAM_OVERFLOW sub=%s queued=%s', sub_id, queue.qsize())
            raise RuntimeError(f'DMS_STREAM_OVERFLOW sub={sub_id}: tick backlog exceeded')
        queue.put_nowait(data)
        stats['enqueued'] += 1
        stats['max_backlog'] = max(stats['max_backlog'], queue.qsize())
        task = self._subscription_workers.get(sub_id)
        if task is None or task.done():
            self._subscription_workers[sub_id] = asyncio.create_task(
                self._consume_subscription(sub_id, self.connection_generation))

    async def _reader(self):
        try:
            async for msg in self.ws:
                self.last_message_at = time.monotonic()
                data = json.loads(msg)
                req_id = data.get('req_id')
                if req_id in self.pending:
                    future = self.pending.pop(req_id)
                    if not future.done():
                        future.set_result(data)
                if req_id in self.pending_subscription_callbacks:
                    callback = self.pending_subscription_callbacks[req_id]
                    sub_id = (data.get('subscription') or {}).get('id')
                    if sub_id:
                        self.pending_subscription_callbacks.pop(req_id, None)
                        self.subscriptions[str(sub_id)].add(callback)
                        self._subscription_callbacks_generation[str(sub_id)] = self.connection_generation
                if data.get('subscription'):
                    self._dispatch_subscription(data)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            ws_log.exception('DMS_STREAM_READER_ERROR generation=%s', self.connection_generation)
            for future in list(self.pending.values()):
                if not future.done():
                    future.set_exception(exc)
        finally:
            for future in list(self.pending.values()):
                if not future.done():
                    future.set_exception(ConnectionError('Deriv WebSocket reader stopped'))
            self.pending.clear()
            self.pending_subscription_callbacks.clear()
            self.subscriptions.clear()
            self._stop_dispatchers()
            ws_log.warning('DMS_STREAM_READER_STOPPED generation=%s', self.connection_generation)

    async def request(self, payload, timeout=15, subscription_callback=None):
        await self.connect()
        self.req_id += 1
        req_id = self.req_id
        request_payload = dict(payload)
        request_payload['req_id'] = req_id
        future = asyncio.get_running_loop().create_future()
        self.pending[req_id] = future
        if subscription_callback is not None:
            self.pending_subscription_callbacks[req_id] = subscription_callback
        try:
            async with self._send_lock:
                await self.ws.send(json.dumps(request_payload))
            data = await asyncio.wait_for(future, timeout)
        except asyncio.TimeoutError as exc:
            self.pending.pop(req_id, None)
            self.pending_subscription_callbacks.pop(req_id, None)
            raise RuntimeError(f'Deriv WebSocket request timed out after {timeout:.0f}s') from exc
        except Exception:
            self.pending.pop(req_id, None)
            self.pending_subscription_callbacks.pop(req_id, None)
            raise
        if 'error' in data:
            self.pending_subscription_callbacks.pop(req_id, None)
            err = data['error'] or {}
            raise RuntimeError(f"{err.get('code')}: {err.get('message')}" if err.get('code')
                               else err.get('message') or str(err))
        return data

    async def _reset_after_timeout(self):
        await self.close()
        await self.connect()

    async def proposal_digitmatch(self, symbol, digit, amount, duration=1, currency='USD'):
        payload = {'proposal': 1, 'amount': round(float(amount), 2), 'basis': 'stake',
                   'contract_type': 'DIGITMATCH', 'currency': str(currency or 'USD').upper(),
                   'duration': int(duration), 'duration_unit': 't', 'barrier': str(int(digit)),
                   'underlying_symbol': str(symbol)}
        async with self._proposal_lock:
            timeout_retry_used = False
            while True:
                now = time.monotonic()
                delay = max(0, self._proposal_min_interval - (now - self._last_proposal_at),
                            self._proposal_cooldown_until - now)
                if delay:
                    await asyncio.sleep(delay)
                try:
                    self._last_proposal_at = time.monotonic()
                    data = await self.request(payload)
                    self._rate_limit_streak = 0
                    self._proposal_cooldown_until = 0
                    return data
                except RuntimeError as exc:
                    txt = str(exc).lower()
                    if 'timed out' in txt and not timeout_retry_used:
                        timeout_retry_used = True
                        await self._reset_after_timeout()
                        continue
                    if 'ratelimit' in txt or 'rate limit' in txt:
                        self._rate_limit_streak = min(self._rate_limit_streak + 1, 6)
                        backoff = (1.5, 2.5, 4.0, 6.0, 8.0, 10.0)[self._rate_limit_streak - 1]
                        self._proposal_cooldown_until = time.monotonic() + backoff
                        await asyncio.sleep(backoff)
                        continue
                    raise

    async def buy_digitmatch_direct(self, *, symbol, digit, amount, currency='USD', duration=1, account_mode):
        if str(account_mode or '').upper() not in {'DEMO', 'REAL'}:
            raise RuntimeError('An explicit DEMO or REAL account mode is required for BUY')
        params = {'amount': round(float(amount), 2), 'basis': 'stake',
                  'contract_type': 'DIGITMATCH', 'currency': str(currency or 'USD').upper(),
                  'duration': int(duration), 'duration_unit': 't', 'barrier': str(int(digit)),
                  'underlying_symbol': str(symbol)}
        async with self._buy_lock:
            wait = self._buy_min_interval - (time.monotonic() - self._last_buy_at)
            if wait > 0:
                await asyncio.sleep(wait)
            self._last_buy_at = time.monotonic()
            return await self.request({'buy': '1', 'price': round(float(amount), 2), 'parameters': params})

    async def buy(self, proposal_id, price, *, account_mode):
        if str(account_mode or '').upper() not in {'DEMO', 'REAL'}:
            raise RuntimeError('An explicit DEMO or REAL account mode is required for BUY')
        return await self.request({'buy': proposal_id, 'price': float(price)})

    @staticmethod
    def _contract_id_value(contract_id):
        try:
            return int(contract_id)
        except (TypeError, ValueError) as exc:
            raise RuntimeError(f'Invalid Deriv contract_id {contract_id!r}; expected integer') from exc

    async def contract_status(self, contract_id):
        return await self.request({'proposal_open_contract': 1,
                                   'contract_id': self._contract_id_value(contract_id)})

    async def subscribe_contract(self, contract_id, callback):
        data = await self.request({'proposal_open_contract': 1,
                                   'contract_id': self._contract_id_value(contract_id),
                                   'subscribe': 1}, subscription_callback=callback)
        sub_id = (data.get('subscription') or {}).get('id')
        if sub_id:
            return str(sub_id)
        req_id = data.get('req_id')
        if req_id is not None:
            self.pending_subscription_callbacks.pop(req_id, None)
        self._schedule_subscription_callback(callback, data)
        return None

    async def ticks_history(self, symbol, count=100):
        count = max(10, min(int(count or 100), 1000))
        return await self.request({'ticks_history': str(symbol), 'count': count,
                                   'end': 'latest', 'style': 'ticks'})

    async def subscribe_ticks(self, symbol, callback):
        data = await self.request({'ticks': str(symbol), 'subscribe': 1},
                                  subscription_callback=callback)
        sub_id = (data.get('subscription') or {}).get('id')
        if not sub_id:
            raise RuntimeError(f'Deriv returned no tick subscription id for {symbol}')
        return str(sub_id)

    async def forget(self, subscription_id):
        result = await self.request({'forget': str(subscription_id)})
        sub_id = str(subscription_id)
        self.subscriptions.pop(sub_id, None)
        task = self._subscription_workers.pop(sub_id, None)
        if task:
            task.cancel()
        self._subscription_queues.pop(sub_id, None)
        self._subscription_callbacks_generation.pop(sub_id, None)
        self.last_tick_at.pop(sub_id, None)
        return result
