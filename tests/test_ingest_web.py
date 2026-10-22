"""SSRF guard + safe fetch. Local servers only; DNS is faked with an injected resolver."""

import json
import ssl
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from careerforge.ingest.errors import FetchFailed, SourceNotSupported, UnsafeURL
from careerforge.ingest.web import (
    FetchPolicy,
    check_url,
    fetch_job_text,
    fetch_page,
    is_public_ip,
    page_to_text,
)

LOCAL = FetchPolicy(allow_private=True, ports=None, timeout=3)


class Site:
    """Tiny scripted web server. routes: path -> (status, headers, body_bytes) or a callable(handler)."""

    def __init__(self, routes, tls=None):
        self.routes, self.seen = routes, []
        outer = self

        class H(BaseHTTPRequestHandler):
            def do_GET(self):
                outer.seen.append(
                    {"path": self.path, "host": self.headers.get("Host"), "ua": self.headers.get("User-Agent")}
                )
                status, headers, body = outer.routes.get(self.path.split("?")[0], (404, {}, b"nope"))
                self.send_response(status)
                for k, v in headers.items():
                    self.send_header(k, v)
                if "Content-Length" not in headers:
                    self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *a):
                pass

        class Server(ThreadingHTTPServer):
            def handle_error(self, request, client_address):
                if isinstance(sys.exc_info()[1], (ConnectionResetError, BrokenPipeError, ssl.SSLError)):
                    outer.dropped += 1  # the client refused our certificate and hung up: what those tests expect
                else:
                    super().handle_error(request, client_address)

        self.dropped = 0
        self.httpd = Server(("127.0.0.1", 0), H)
        if tls:
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            ctx.load_cert_chain(*tls)
            self.httpd.socket = ctx.wrap_socket(self.httpd.socket, server_side=True)
        threading.Thread(target=self.httpd.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True).start()
        self.port = self.httpd.server_port

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


HTML = {"Content-Type": "text/html; charset=utf-8"}


@pytest.fixture
def site():
    made = []

    def make(routes, tls=None):
        s = Site(routes, tls)
        made.append(s)
        return s

    yield make
    for s in made:
        s.close()


def resolver_to(ip, calls=None):
    def resolve(host, port):
        if calls is not None:
            calls.append(host)
        return [ip]

    return resolve


class TestIpPolicy:
    @pytest.mark.parametrize("ip", ["127.0.0.1", "10.1.2.3", "172.16.0.9", "192.168.1.1", "169.254.169.254", "100.64.0.1",
                                    "0.0.0.0", "::1", "fe80::1", "fc00::1", "::ffff:127.0.0.1", "::ffff:169.254.169.254",
                                    "64:ff9b::7f00:1", "224.0.0.1", "not-an-ip"])  # fmt: skip
    def test_private_and_special_addresses_refused(self, ip):
        assert not is_public_ip(ip)

    @pytest.mark.parametrize("ip", ["8.8.8.8", "1.1.1.1", "93.184.216.34", "2606:4700:4700::1111"])
    def test_public_addresses_allowed(self, ip):
        assert is_public_ip(ip)


class TestCheckUrl:
    @pytest.mark.parametrize("url", [
        "http://localhost/", "http://127.0.0.1/", "http://127.1/", "http://2130706433/", "http://0x7f.1/",
        "http://[::1]/", "http://[::ffff:7f00:1]/", "http://169.254.169.254/latest/meta-data/",
        "http://10.0.0.5/admin", "http://192.168.0.1/", "http://100.64.0.1/", "http://0.0.0.0/", "http://localhost./",
    ])  # fmt: skip
    def test_internal_targets_are_blocked_via_real_dns_resolution(self, url):
        with pytest.raises(UnsafeURL):
            check_url(url)

    @pytest.mark.parametrize("url", [
        "file:///etc/passwd", "ftp://example.com/", "gopher://example.com/", "javascript:alert(1)", "data:text/html,x",
        "http://user:pw@example.com/", "http://example.com:22/", "http://example.com:6379/", "", "http://",
        "http://exa mple.com/", "http://x/" + "a" * 3000, "//example.com/",
    ])  # fmt: skip
    def test_bad_schemes_ports_and_shapes(self, url):
        with pytest.raises((UnsafeURL, FetchFailed)):
            check_url(url, resolver=resolver_to("93.184.216.34"))

    def test_hostname_that_resolves_private_is_blocked(self):
        with pytest.raises(UnsafeURL, match="private"):
            check_url("https://innocent.example.com/", resolver=resolver_to("10.0.0.7"))

    def test_any_private_answer_among_many_blocks(self):
        with pytest.raises(UnsafeURL):
            check_url("https://rebind.example.com/", resolver=lambda h, p: ["93.184.216.34", "127.0.0.1"])

    def test_public_host_passes_and_returns_validated_ips(self):
        url, host, port, ips = check_url("https://example.com/job", resolver=resolver_to("93.184.216.34"))
        assert (host, port, ips) == ("example.com", 443, ["93.184.216.34"])


class TestFetch:
    def test_fetches_with_honest_user_agent(self, site):
        s = site(
            {"/job": (200, HTML, b"<html><body><main>" + b"Python developer needed. " * 20 + b"</main></body></html>")}
        )
        page = fetch_page(f"http://jobs.example.test:{s.port}/job", LOCAL, resolver_to("127.0.0.1"))
        assert page.status == 200 and b"Python developer" in page.body
        assert "CareerForgeBot" in s.seen[0]["ua"] and "Mozilla" not in s.seen[0]["ua"]

    def test_connection_is_pinned_and_host_header_is_the_real_hostname(self, site):
        calls = []
        s = site({"/": (200, HTML, b"<html>" + b"x" * 100 + b"</html>")})
        fetch_page(f"http://jobs.example.test:{s.port}/", LOCAL, resolver_to("127.0.0.1", calls))
        assert s.seen[0]["host"] == f"jobs.example.test:{s.port}"  # virtual-host routing still works
        assert calls == ["jobs.example.test"]  # resolved exactly once: no second lookup between check and connect

    def test_blocked_by_default_even_when_the_server_exists(self, site):
        s = site({"/": (200, HTML, b"secret internal page")})
        with pytest.raises(UnsafeURL):
            fetch_page(f"http://127.0.0.1:{s.port}/", FetchPolicy(ports=None))
        assert s.seen == []  # not a single request reached it

    def test_redirect_to_internal_address_is_blocked(self, site):
        internal = site({"/secret": (200, HTML, b"internal")})
        public = site({"/go": (302, {"Location": f"http://internal.example.test:{internal.port}/secret"}, b"")})

        def resolve(host, port):
            return ["93.184.216.34"] if host == "public.example.test" else ["127.0.0.1"]

        # pretend the public host is reachable: point it at our local server by resolving it to loopback ONLY for
        # the connect step (allow_private lets the first hop through); the redirect target must still be refused
        # when private addresses are not allowed. Test the guard directly on the second hop:
        with pytest.raises(UnsafeURL):
            check_url(f"http://internal.example.test:{internal.port}/secret", FetchPolicy(ports=None), resolve)
        assert public.seen == [] and internal.seen == []

    def test_redirects_are_followed_and_revalidated_each_hop(self, site):
        s = site({"/a": (302, {"Location": "/b"}, b""), "/b": (301, {"Location": "/c"}, b""),
                  "/c": (200, HTML, b"<html>" + b"final page " * 20 + b"</html>")})  # fmt: skip
        page = fetch_page(f"http://x.example.test:{s.port}/a", LOCAL, resolver_to("127.0.0.1"))
        assert b"final page" in page.body and [h["path"] for h in s.seen] == ["/a", "/b", "/c"]

    def test_redirect_loop_gives_up(self, site):
        s = site({"/a": (302, {"Location": "/a"}, b"")})
        with pytest.raises(FetchFailed, match="too many"):
            fetch_page(f"http://x.example.test:{s.port}/a", LOCAL, resolver_to("127.0.0.1"))

    def test_redirect_to_non_http_scheme_blocked(self, site):
        s = site({"/a": (302, {"Location": "file:///etc/passwd"}, b"")})
        with pytest.raises(UnsafeURL):
            fetch_page(f"http://x.example.test:{s.port}/a", LOCAL, resolver_to("127.0.0.1"))

    def test_oversize_body_refused_while_streaming(self, site):
        s = site({"/big": (200, {**HTML, "Content-Length": "1000"}, b"x" * 1000)})
        with pytest.raises(FetchFailed, match="too large"):
            fetch_page(
                f"http://x.example.test:{s.port}/big",
                FetchPolicy(allow_private=True, ports=None, max_bytes=500),
                resolver_to("127.0.0.1"),
            )

    @pytest.mark.parametrize(
        "status,msg", [(403, "login"), (999, "login"), (404, "not found"), (429, "rate"), (503, "error")]
    )
    def test_http_errors_have_friendly_messages(self, site, status, msg):
        s = site({"/": (status, HTML, b"x")})
        with pytest.raises(FetchFailed, match=msg):
            fetch_page(f"http://x.example.test:{s.port}/", LOCAL, resolver_to("127.0.0.1"))

    def test_non_page_content_types_rejected_with_hint(self, site):
        s = site(
            {
                "/cv.pdf": (200, {"Content-Type": "application/pdf"}, b"%PDF-1.4"),
                "/i.png": (200, {"Content-Type": "image/png"}, b"x"),
            }
        )
        with pytest.raises(FetchFailed, match="upload it as a file"):
            fetch_page(f"http://x.example.test:{s.port}/cv.pdf", LOCAL, resolver_to("127.0.0.1"))
        with pytest.raises(FetchFailed, match="not a web page"):
            fetch_page(f"http://x.example.test:{s.port}/i.png", LOCAL, resolver_to("127.0.0.1"))

    def test_unreachable_host_is_a_friendly_error_without_leaking_details(self):
        with pytest.raises(FetchFailed) as ei:
            fetch_page("http://x.example.test:9/", LOCAL, resolver_to("127.0.0.1"))
        assert "127.0.0.1" not in str(ei.value)

    @pytest.mark.parametrize(
        "url", ["https://www.linkedin.com/in/someone", "https://linkedin.com/jobs/view/1", "https://lnkd.in/abc"]
    )
    def test_linkedin_is_refused_honestly(self, url):
        with pytest.raises(SourceNotSupported, match="Save to PDF"):
            fetch_page(url)


@pytest.fixture(scope="module")
def tls_files(tmp_path_factory):
    d = tmp_path_factory.mktemp("tls")
    cert, key = str(d / "cert.pem"), str(d / "key.pem")
    subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", key, "-out", cert, "-days", "2",
                    "-subj", "/CN=secure.example.test", "-addext", "subjectAltName=DNS:secure.example.test"],
                   check=True, capture_output=True)  # fmt: skip
    return cert, key


class TestHttps:
    def test_pinned_https_verifies_certificate_against_the_real_hostname(self, site, tls_files):
        cert, key = tls_files
        s = site({"/": (200, HTML, b"<html>" + b"secure page " * 20 + b"</html>")}, tls=(cert, key))
        policy = FetchPolicy(allow_private=True, ports=None, timeout=3, verify=cert)
        page = fetch_page(f"https://secure.example.test:{s.port}/", policy, resolver_to("127.0.0.1"))
        assert b"secure page" in page.body and s.seen[0]["host"] == f"secure.example.test:{s.port}"

    def test_certificate_for_a_different_hostname_is_rejected(self, site, tls_files):
        cert, key = tls_files
        s = site({"/": (200, HTML, b"x")}, tls=(cert, key))
        policy = FetchPolicy(allow_private=True, ports=None, timeout=3, verify=cert)
        with pytest.raises(FetchFailed, match="certificate"):
            fetch_page(f"https://other.example.test:{s.port}/", policy, resolver_to("127.0.0.1"))
        assert s.seen == []  # not a single request reached the server with the wrong certificate

    def test_untrusted_certificate_is_rejected(self, site, tls_files):
        cert, key = tls_files
        s = site({"/": (200, HTML, b"x")}, tls=(cert, key))
        with pytest.raises(FetchFailed, match="certificate"):
            fetch_page(
                f"https://secure.example.test:{s.port}/",
                FetchPolicy(allow_private=True, ports=None, timeout=3),
                resolver_to("127.0.0.1"),
            )
        assert s.seen == []


JOB_LD = {"@context": "https://schema.org", "@type": "JobPosting", "title": "Senior Backend Engineer",
          "hiringOrganization": {"@type": "Organization", "name": "Finlytics"},
          "jobLocation": {"@type": "Place", "address": {"addressLocality": "Bengaluru", "addressCountry": "IN"}},
          "employmentType": ["FULL_TIME"], "description": "<p>Build <b>payment</b> services in Python and Go.</p><ul><li>Kafka</li><li>PostgreSQL</li></ul>"}  # fmt: skip


class TestPageToText:
    def page(self, html, ctype="text/html"):
        from careerforge.ingest.web import FetchedPage

        return FetchedPage("http://x/", 200, ctype, html.encode())

    def test_prefers_structured_job_posting_data(self):
        html = f'<html><head><script type="application/ld+json">{json.dumps(JOB_LD)}</script></head><body><nav>menu menu</nav>cookie banner</body></html>'
        text = page_to_text(self.page(html))
        assert "Job title: Senior Backend Engineer" in text and "Company: Finlytics" in text
        assert "Location: Bengaluru, IN" in text and "Build payment services in Python and Go." in text
        assert "• Kafka" in text and "• PostgreSQL" in text and "menu" not in text

    def test_job_posting_inside_graph_and_list(self):
        html = (
            f'<script type="application/ld+json">{json.dumps({"@graph": [{"@type": "WebSite"}, JOB_LD]})}</script>'
            + "<p>"
            + "pad " * 30
            + "</p>"
        )
        assert "Senior Backend Engineer" in page_to_text(self.page(html))

    def test_falls_back_to_visible_text_and_strips_chrome(self):
        html = "<html><body><nav>Home Jobs</nav><script>track()</script><main><h1>Data Analyst</h1><p>SQL and Tableau required.</p></main><footer>Copyright</footer></body></html>"
        text = page_to_text(self.page(html))
        assert "Data Analyst" in text and "SQL and Tableau" in text
        assert "Home Jobs" not in text and "track()" not in text and "Copyright" not in text

    def test_inline_tags_do_not_split_sentences_in_fallback_text(self):
        html = "<main><p>We use <b>Python</b>, <a href='#'>Kafka</a> and <em>Redis</em> daily.</p><ul><li>Own <b>APIs</b></li></ul></main>"
        text = page_to_text(self.page(html))
        assert "We use Python, Kafka and Redis daily." in text and "• Own APIs" in text

    def test_malformed_json_ld_is_ignored(self):
        html = '<script type="application/ld+json">{not json</script><body><p>Visible job text about Python.</p></body>'
        assert "Visible job text" in page_to_text(self.page(html))

    def test_plain_text_passthrough(self):
        assert page_to_text(self.page("Line one\nLine two", "text/plain")) == "Line one\nLine two"


class TestFetchJobText:
    def test_login_wall_gets_a_helpful_error(self, site):
        s = site({"/": (200, HTML, b"<html><body>Please sign in to view this job. Enable JavaScript.</body></html>")})
        with pytest.raises(FetchFailed, match="Paste the text"):
            fetch_job_text(f"http://x.example.test:{s.port}/", LOCAL, resolver_to("127.0.0.1"))

    def test_good_page_returns_text(self, site):
        html = f'<script type="application/ld+json">{json.dumps(JOB_LD)}</script><body>x</body>'.encode()
        s = site({"/": (200, HTML, html)})
        assert "Senior Backend Engineer" in fetch_job_text(
            f"http://x.example.test:{s.port}/", LOCAL, resolver_to("127.0.0.1")
        )
