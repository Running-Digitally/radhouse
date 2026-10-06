import test from 'node:test';
import assert from 'node:assert/strict';
import { environment, privacyRequested, safeUrl, redact, eventProperties, SITE, TOKEN } from '../public/analytics-policy.js';

test('production and explicit loopback preview are separate; other hosts do not collect', () => {
  assert.equal(environment(SITE, true), 'production');
  for (const hostname of ['127.0.0.1', 'localhost', '[::1]']) {
    assert.equal(environment(hostname, true), 'preview');
    assert.equal(environment(hostname, false), null);
  }
  for (const hostname of ['posthog.sati.sh', 'risewithme.ai', 'radhouserunningdigitallycom.connect-a95.workers.dev', 'evil.example']) assert.equal(environment(hostname, true), null);
});

test('DNT and global privacy preferences suppress collection', () => {
  assert.equal(privacyRequested({ globalPrivacyControl: true }, null), true);
  assert.equal(privacyRequested({ doNotTrack: '1' }, null), true);
  assert.equal(privacyRequested({}, '1'), true);
  assert.equal(privacyRequested({ doNotTrack: '0' }, null), false);
});

test('URLs drop credentials, adjacent private parameters and fragments', () => {
  assert.equal(safeUrl('https://person:secret@example.com/path?token=secret&code=private&state=private&utm_source=example#private'), 'https://example.com/path?utm_source=example');
  assert.equal(safeUrl('/?analytics=preview&email=private'), `https://${SITE}/`);
  assert.equal(safeUrl('javascript:alert(1)'), '');
  assert.equal(safeUrl('mailto:private@example.com'), '');
  assert.equal(safeUrl('$direct'), '$direct');
});

test('nested properties redact private keys and retain Radhouse provenance', () => {
  const properties = { email: 'private', nested: [{ token: 'secret', destination_url: 'https://example.com/?token=secret' }], site: 'other-site', environment: 'other', page_path: 'other' };
  assert.deepEqual(redact(properties).nested, [{ destination_url: 'https://example.com/' }]);
  const event = eventProperties(properties, 'preview', '/');
  assert.equal(event.email, undefined);
  assert.equal(event.token, TOKEN);
  assert.equal(event.site, SITE);
  assert.equal(event.environment, 'preview');
  assert.equal(event.page_path, '/');
});
