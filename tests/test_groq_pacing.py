import json
import unittest
import urllib.error
from unittest.mock import patch

from tracemicro.providers import GroqProvider,GroqConfig,HTTPResult,ProviderError,safe_rate_limits


def body():
    return json.dumps({'choices':[{'finish_reason':'stop','message':{'content':'{"type":"inspect_source","class":"fixture.A"}'}}]}).encode()


class RatePacingTests(unittest.TestCase):
    def test_allowlist_rejects_unrelated_and_malformed_values(self):
        headers={'authorization':'private','set-cookie':'private','retry-after':'Bearer private',
                 'x-ratelimit-limit-tokens':'8000','x-ratelimit-remaining-tokens':'123',
                 'x-ratelimit-reset-tokens':'2m3.5s','x-ratelimit-reset-requests':'private'}
        self.assertEqual(safe_rate_limits(headers),{'x-ratelimit-limit-tokens':8000,
                         'x-ratelimit-remaining-tokens':123,'x-ratelimit-reset-tokens':'2m3.5s'})
        self.assertEqual(safe_rate_limits({'retry-after':'60'}),{'retry_after_seconds':60.0})
        self.assertIn('retry_after_utc',safe_rate_limits({'retry-after':'Wed, 21 Oct 2015 07:28:00 GMT'}))

    def test_success_and_429_metadata_no_retry(self):
        calls=[]
        def transport(*args):
            calls.append(1)
            if len(calls)==1: return HTTPResult(body(),safe_rate_limits({'x-ratelimit-remaining-tokens':'100'}))
            raise urllib.error.HTTPError('https://api.groq.com',429,'private',
                  {'retry-after':'60','x-ratelimit-limit-tokens':'8000','authorization':'private'},None)
        p=GroqProvider(GroqConfig('simulated'),transport=transport)
        with patch('tracemicro.providers.os.environ',{'GROQ_API_KEY':'offline-placeholder'}):
            p.decide({})
            with self.assertRaises(ProviderError): p.decide({})
        self.assertEqual(len(calls),2)
        self.assertEqual(p.records[0]['rate_limits'],{'x-ratelimit-remaining-tokens':100})
        self.assertEqual(p.records[1]['rate_limits'],{'x-ratelimit-limit-tokens':8000,'retry_after_seconds':60.0})
        self.assertNotIn('private',json.dumps(p.records))

    def test_fake_clock_pacing_bounded_and_request_cap_preserved(self):
        now=[0.0]; waits=[]; calls=[]
        def sleep(seconds): waits.append(seconds); now[0]+=seconds
        def transport(*args): calls.append(1); return body()
        p=GroqProvider(GroqConfig('simulated',max_requests=3,min_interval_seconds=60,max_pacing_wait_seconds=60),
                       transport=transport,clock=lambda:now[0],sleeper=sleep)
        with patch('tracemicro.providers.os.environ',{'GROQ_API_KEY':'offline-placeholder'}):
            p.decide({}); p.decide({})
            with self.assertRaises(ProviderError) as caught: p.decide({})
            self.assertEqual(caught.exception.code,'pacing_wait_budget_exhausted')
            with self.assertRaises(ProviderError) as caught: p.decide({})
            self.assertEqual(caught.exception.code,'provider_request_cap')
        self.assertEqual(waits,[60])
        self.assertEqual(len(calls),2)
        self.assertEqual(p.records[1]['pacing_wait_seconds'],60)

    def test_disabled_pacing_never_sleeps(self):
        def forbidden_sleep(seconds): raise AssertionError('Unexpected sleep')
        p=GroqProvider(GroqConfig('simulated'),transport=lambda *args:body(),sleeper=forbidden_sleep)
        with patch('tracemicro.providers.os.environ',{'GROQ_API_KEY':'offline-placeholder'}):
            p.decide({}); p.decide({})
        self.assertEqual(p.pacing_wait_total,0)
        with self.assertRaises(ValueError): GroqConfig('x',min_interval_seconds=61)
        with self.assertRaises(ValueError): GroqConfig('x',min_interval_seconds=60,max_pacing_wait_seconds=30)


if __name__=='__main__': unittest.main()
