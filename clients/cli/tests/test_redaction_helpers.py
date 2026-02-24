import unittest

from cli_app.redact import redact_mapping, redact_text


class TestRedactionHelpers(unittest.TestCase):
    def test_redact_text_redacts_bearer_and_known_keys(self):
        text = (
            'Authorization: Bearer abc123 session_token=secret '
            'resume_token:"resume-secret" /ws?token=urltok&credential=credtok'
        )
        redacted = redact_text(text)
        self.assertIn('Bearer [REDACTED]', redacted)
        self.assertIn('session_token=[REDACTED]', redacted)
        self.assertIn('resume_token:"[REDACTED]"', redacted)
        self.assertIn('token=[REDACTED]', redacted)
        self.assertIn('credential=[REDACTED]', redacted)
        self.assertNotIn('abc123', redacted)
        self.assertNotIn('secret', redacted)

    def test_redact_mapping_replaces_sensitive_values(self):
        payload = {
            'session_token': 'secret-session',
            'nested': {
                'resume_token': 'secret-resume',
                'safe': 'value',
            },
            'items': [
                {'device_credential': 'cred'},
                {'other': 'ok'},
            ],
        }
        redacted = redact_mapping(payload)
        self.assertEqual(redacted['session_token'], '[REDACTED]')
        self.assertEqual(redacted['nested']['resume_token'], '[REDACTED]')
        self.assertEqual(redacted['nested']['safe'], 'value')
        self.assertEqual(redacted['items'][0]['device_credential'], '[REDACTED]')
        self.assertEqual(redacted['items'][1]['other'], 'ok')


if __name__ == '__main__':
    unittest.main()
