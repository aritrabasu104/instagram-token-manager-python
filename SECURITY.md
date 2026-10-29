# Security

Credentials belong in an application-owned vault. Keep access tokens, app
secrets, passwords, cookies, OAuth codes and callback URLs out of source control,
command arguments, logs and issue reports. Never include private account IDs,
local directories or production configuration in public examples.

The package ships no credentials or account configuration. HTTP errors retain
sanitized categories/numeric codes, and credential objects expose redacted
representations and safe serialization. Request URLs containing token exchange
parameters must not be logged by an external transport. Do not enable HTTP debug
logging around exchanges.

A grant requires its original durable intent; an unknown response is never an
automatic retry. Preserve existing access/security refusals and original consent
attempts. The package does not automate password login or bypass MFA/CAPTCHA.

When reporting a bug, use synthetic data and remove credentials, authorization
headers, full callback URLs, private account details and environment dumps.
