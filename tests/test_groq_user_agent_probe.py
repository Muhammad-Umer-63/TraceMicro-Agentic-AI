import contextlib
import io
import unittest
import urllib.error
import urllib.request
from unittest.mock import Mock, patch

from tools import groq_user_agent_probe as probe


class UserAgentProbeTests(unittest.TestCase):
    def execute(self, opener):
        output=io.StringIO()
        with patch('tools.groq_user_agent_probe.os.environ',{'GROQ_API_KEY':'synthetic-offline-placeholder'}), \
             patch('tools.groq_user_agent_probe.urllib.request.build_opener',return_value=opener) as factory, \
             contextlib.redirect_stdout(output):
            code=probe.main()
        return code,output.getvalue(),factory

    def response(self,status=200):
        response=Mock()
        response.__enter__=Mock(return_value=response)
        response.__exit__=Mock(return_value=False)
        response.getcode.return_value=status
        response.read.side_effect=AssertionError('Must not read a body')
        return response

    def test_only_user_agent_changes_and_two_requests(self):
        response=self.response()
        opener=Mock(); opener.open.return_value=response
        code,output,factory=self.execute(opener)
        self.assertEqual(code,0)
        self.assertEqual(output,'status=200 category=ok\n'*2)
        self.assertEqual(opener.open.call_count,2)
        first,second=[c.args[0] for c in opener.open.call_args_list]
        self.assertEqual(first.full_url,second.full_url)
        self.assertEqual(first.full_url,probe.URL)
        self.assertEqual((first.get_method(),second.get_method()),('GET','GET'))
        self.assertIsNone(first.data); self.assertIsNone(second.data)
        self.assertIsNone(first.get_header('User-agent'))
        self.assertEqual(second.get_header('User-agent'),probe.ALTERNATE_USER_AGENT)
        left=dict(first.header_items()); right=dict(second.header_items()); right.pop('User-agent')
        self.assertEqual(left,right)
        for call in factory.call_args_list:
            proxy,redirect=call.args
            self.assertIsInstance(proxy,urllib.request.ProxyHandler)
            self.assertEqual(proxy.proxies,{})
            self.assertIsInstance(redirect,probe.NoRedirect)
        self.assertEqual([c.kwargs for c in opener.open.call_args_list],[{'timeout':15},{'timeout':15}])
        response.read.assert_not_called()

    def test_http403_then200_output_contains_only_status_category(self):
        opener=Mock()
        opener.open.side_effect=[urllib.error.HTTPError(probe.URL,403,'private error text',{},None),self.response()]
        _,output,_=self.execute(opener)
        self.assertEqual(output,'status=403 category=http_forbidden\nstatus=200 category=ok\n')
        self.assertNotIn('private',output)
        self.assertNotIn('synthetic',output)
        self.assertEqual(opener.open.call_count,2)

    def test_first_failure_does_not_retry_and_second_attempt_runs(self):
        opener=Mock(); opener.open.side_effect=[TimeoutError('private'),PermissionError('private')]
        _,output,_=self.execute(opener)
        self.assertEqual(opener.open.call_count,2)
        self.assertEqual(output,'status=none category=timeout\nstatus=none category=local_permission_denied\n')

    def test_missing_key_never_attempts_request(self):
        output=io.StringIO()
        with patch('tools.groq_user_agent_probe.os.environ',{}), \
             patch('tools.groq_user_agent_probe.urllib.request.build_opener') as factory, \
             contextlib.redirect_stdout(output):
            self.assertEqual(probe.main(),1)
        factory.assert_not_called()
        self.assertEqual(output.getvalue(),'status=none category=missing_or_invalid_key\n')

    def test_redirect_is_not_followed(self):
        with self.assertRaises(urllib.error.HTTPError) as caught:
            probe.NoRedirect().redirect_request(None,None,302,'private',{},'https://other.invalid')
        self.assertEqual(caught.exception.code,302)


if __name__ == '__main__': unittest.main()
