"""User-run, two-attempt model-list User-Agent comparison. No import-time I/O."""
import os
import socket
import urllib.error
import urllib.request

URL = 'https://api.groq.com/openai/v1/models'
ALTERNATE_USER_AGENT = 'TraceMicro-Diagnostic/1.0'
TIMEOUT_SECONDS = 15


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Preserve the status without following another URL or exposing headers.
        raise urllib.error.HTTPError(URL, code, 'redirect_refused', None, None)


def attempt(headers):
    """One GET attempt; never read response bodies or retry."""
    try:
        request = urllib.request.Request(URL, headers=headers, method='GET')
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
        with opener.open(request, timeout=TIMEOUT_SECONDS) as response:
            status = response.getcode()
            return status, 'ok' if 200 <= status < 300 else 'http_error'
    except urllib.error.HTTPError as error:
        status = error.code
        try:
            error.close()
        except Exception:
            pass  # Never expose cleanup exception messages or response details.
        category = {400:'http_bad_request',401:'http_unauthorized',403:'http_forbidden',
                    404:'http_not_found',429:'http_rate_limited'}.get(status,'http_error')
        return status, 'redirect_refused' if 300 <= status < 400 else category
    except PermissionError:
        return None, 'local_permission_denied'
    except (TimeoutError,socket.timeout):
        return None, 'timeout'
    except urllib.error.URLError as error:
        if isinstance(error.reason,PermissionError): return None, 'local_permission_denied'
        return None, 'timeout' if isinstance(error.reason,TimeoutError) else 'network_error'
    except Exception:
        return None, 'transport_error'


def main():
    # Only user execution reaches this read; no value is printed/saved/logged.
    key = os.environ.get('GROQ_API_KEY')
    if not key or not key.strip() or '\r' in key or '\n' in key:
        print('status=none category=missing_or_invalid_key')
        return 1
    common = {'Authorization':'Bearer '+key,'Content-Type':'application/json'}
    # Exactly two attempts with the same key, URL, method, body, proxy/redirect
    # policy and timeout. Only the second request overrides urllib's default UA.
    for headers in (common, dict(common, **{'User-Agent':ALTERNATE_USER_AGENT})):
        status, category = attempt(headers)
        print('status='+('none' if status is None else str(status))+' category='+category)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
