"""Operational metadata, durable queue counters and feature negotiation; no camera/server."""
import io
import json
import sys
import tempfile
import urllib.error
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sender import Sender
from outbox import Outbox
from config_sync import ConfigSync


def main():
    with tempfile.TemporaryDirectory() as directory, closing(Outbox(str(Path(directory) / 'outbox.db'))) as box:
        box.bind('https://example.invalid','owner-a')
        with patch('outbox.time.time', return_value=1000):
            box.put('metric','one',{'metricId':'one','userId':'owner-a','private':'NOT-FOR-WEB'})
            box.put('metric','two',{'metricId':'two','userId':'owner-a'})
        box.mark_failed(['one'],'Bearer NOT-FOR-WEB',now=1001)
        stats = box.stats(include_diagnostics=True)
        assert stats['retrying'] == 1 and stats['oldestPendingAt'] == 1000
        assert box.stats() == dict(pending=2,sent=0,dead=0), 'Legacy counters must keep their public shape'
        sender = Sender(box,'https://example.invalid',token='NOT-FOR-WEB',check_schema=False)
        sender.q.put(('metric','three',{},False))
        initial = sender.diagnostics()
        assert initial['deliveryState']=='NOT_SENT' and initial['queued']==1 and initial['pending']==2
        assert initial['lastAttemptAt'] is None and initial['lastAttemptMs'] is None
        assert 'NOT-FOR-WEB' not in json.dumps(initial)
        items = box.due(now=2000)
        ack = {'accepted':['one'],'rejected':[{'id':'two','reason':'private failure NOT-FOR-WEB'}]}
        with patch.object(sender._opener,'open',return_value=io.BytesIO(json.dumps(ack).encode())), patch('sender.time.monotonic',side_effect=[10,10.125]):
            assert sender._send(items)
        sent = sender.diagnostics(config_ms=250)
        assert sent['acceptedSinceStart']==1 and sent['dead']==1 and sent['pending']==0 and sent['retrying']==0
        assert sent['lastAttemptMs']==125 and sent['configFetchApplyMs']==250 and sent['deliveryState']=='OK'
        assert sent['oldestPendingAt'] is None and 'NOT-FOR-WEB' not in json.dumps(sent)
        box.put('metric','four',{'metricId':'four','userId':'owner-a'})
        items = box.due()
        with patch.object(sender._opener,'open',return_value=io.BytesIO(b'{"accepted":[],"rejected":[]}')):
            assert not sender._send(items)
        assert sender.diagnostics()['deliveryState']=='RETRYING'
        assert sender.diagnostics()['lastFailureCode']=='NETWORK_OR_RESPONSE'
        error = urllib.error.HTTPError('https://NOT-FOR-WEB.invalid',401,'NOT-FOR-WEB',None,None)
        with patch.object(sender._opener,'open',side_effect=error):
            assert not sender._send(items)
        assert sender.diagnostics()['deliveryState']=='AUTH_REQUIRED'
        assert 'NOT-FOR-WEB' not in json.dumps(sender.diagnostics())
        box.bind('https://example.invalid','owner-a')
        sender.auth = SimpleNamespace(base_url='https://example.invalid',user_id='owner-b')
        assert not sender._send(items)
        assert sender.last_failure_code=='SOURCE_MISMATCH'
        assert sender.diagnostics() is None, 'Another owner must not receive even queue counts or timestamps'

    sync = ConfigSync(SimpleNamespace(base_url='http://example.invalid'))
    callbacks = []
    sync.sio = SimpleNamespace(connected=True,emit=lambda event,body,callback=None: callbacks.append(callback) if callback else None)
    sync.observations.set_diagnostics(initial)
    sync.observations.put('desktop','session','GOOD')
    packets = []
    sync.observations.send(lambda event,body: packets.append(body),force=True)
    assert 'diagnostics' not in packets[-1], 'New desktop must work with an old backend'
    sync._emit_observation('device-state',packets[-1])
    for _ in range(50): sync._emit_observation('device-state',packets[-1])
    assert len(callbacks)==1, 'Missing legacy ACK must not accumulate unbounded callbacks'
    callbacks[-1]({'accepted':True,'code':'OBSERVATION_ACCEPTED'})
    assert not sync.observations.diagnostics_supported
    callbacks[-1]({'accepted':True,'diagnosticsSupported':True})
    sync.observations.send(lambda event,body: packets.append(body),force=True)
    assert packets[-1]['diagnostics']==initial
    old = callbacks[-1]
    sync.connection_generation += 1
    sync.observations.enable_diagnostics(False)
    old({'accepted':True,'diagnosticsSupported':True})
    assert not sync.observations.diagnostics_supported, 'Old connection ACK must not enable a new connection'
    sync.observations.enable_diagnostics(True)
    sync._emit_observation('device-state',packets[-1]);callbacks[-1]({'accepted':False,'code':'OBSERVATION_INVALID'})
    assert not sync.observations.diagnostics_supported
    sync.taken = dict(version=3,revision='a'*64,effective={},_fetch_started_mono=20)
    with patch('config_sync.time.monotonic',return_value=20.75): sync.complete(True)
    assert sync.status()['fetchApplyMs']==750
    sync.taken = dict(version=3,revision='a'*64,effective={},_fetch_started_mono=20)
    with patch('config_sync.time.monotonic',return_value=21): sync.complete(False)
    assert sync.status()['fetchApplyMs'] is None
    sync.taken = dict(version=None,revision=None,effective={})
    sync.complete(True)
    assert sync.status()['fetchApplyMs'] is None
    print('PASS: queue/retention counters, safe codes, complete ACK, monotonic timings, legacy negotiation and connection isolation')


if __name__=='__main__': main()
