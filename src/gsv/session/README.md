# `gsv.session`

`gsv.session` restores or establishes one authenticated browser context using a site-provided `SiteAuthAdapter`.
The framework owns the state machine; apps only provide URLs, selector fallback lists, predicates, optional init scripts, and credentials from their own source.

```
start
  -> BrowserManager.start
  -> GET auth_marker_url
  -> authenticated URL? yes: restored, no: caller may login

login
  -> GET login_url, or auth_marker_url for no-auth adapters
  -> cookie consent selectors
  -> variant trigger selectors
  -> username/password selector fallback
  -> submit selector fallback
  -> completion: auth marker, challenge policy, or diagnostics failure

post_login_warmup
  -> one-shot, gated by visitor.pacing.post_login_warmup and adapter.warmup_url
```

Selector fields are tuples and are tried in order so apps can tolerate markup variants without changing framework code.
On failure, diagnostics log per-selector counts for username, password, submit, cookie-consent, and variant-trigger selectors.

See `docs/ARCHITECTURE.md` section 4.2 for the session/auth contract.
