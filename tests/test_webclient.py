import unittest

from kpnetwatch.webclient import USER_AGENT, BlockedRequest, Client, FetchError

from support import FakeFetch, Sequence, fake_client


class ClientTests(unittest.TestCase):
    def test_refuses_hosts_outside_the_allow_list(self):
        fetch = FakeFetch([])
        client = Client(fetch, sleep=lambda seconds: None)
        for url in (
            "https://175.45.176.71/",
            "http://stat.ripe.net/data/x",
            "https://kcna.kp/",
            "https://www.naenara.com.kp/index.php",
            "https://example.org/",
        ):
            with self.assertRaises(BlockedRequest, msg=url):
                client.get_json(url)
        self.assertEqual(fetch.calls, [])

    def test_retries_with_exponential_backoff(self):
        route = Sequence(FetchError("HTTP 502", status=502), FetchError("timed out"), b'["ok"]')
        client, fetch = fake_client([("crt.sh", route)])
        self.assertEqual(client.get_json("https://crt.sh/?q=x", backoff=2.0), ["ok"])
        self.assertEqual(len(fetch.calls), 3)
        self.assertEqual(client.sleeps, [2.0, 4.0])

    def test_gives_up_after_the_last_attempt(self):
        client, fetch = fake_client([("crt.sh", FetchError("HTTP 502", status=502))])
        with self.assertRaises(FetchError):
            client.get_json("https://crt.sh/?q=x", attempts=3)
        self.assertEqual(len(fetch.calls), 3)

    def test_does_not_retry_client_errors(self):
        client, fetch = fake_client([("crt.sh", FetchError("HTTP 403", status=403))])
        with self.assertRaises(FetchError):
            client.get_json("https://crt.sh/?q=x")
        self.assertEqual(len(fetch.calls), 1)

    def test_invalid_json_is_retried_then_reported(self):
        client, fetch = fake_client([("crt.sh", b"<html>bad gateway</html>")])
        with self.assertRaises(FetchError) as caught:
            client.get_json("https://crt.sh/?q=x")
        self.assertIn("invalid JSON", str(caught.exception))
        self.assertEqual(len(fetch.calls), 3)

    def test_user_agent_is_generic(self):
        self.assertEqual(USER_AGENT, "kp-netwatch/0.1")


if __name__ == "__main__":
    unittest.main()
