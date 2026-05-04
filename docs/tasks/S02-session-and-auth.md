# S2 — Session + auth

> **Slice:** S2 of 10. See [IMPLEMENTATION_PLAN.md](../IMPLEMENTATION_PLAN.md).
> **Architecture refs:** [ARCHITECTURE.md §4.2](../ARCHITECTURE.md#42-session--auth-layer-gsvsession).
> **Status:** Implemented in the S2 session/auth branch. **Depends on S1.**

---

## 1. Goal

Generalize CareerExplorer's `LinkedInSession` into a site-agnostic `Session` driven by a `SiteAuthAdapter`. Preserve the working state machine (cookie consent → variant detection → credential entry → submit → completion classification) and the verification escalation policy (headed wait / headless fail-fast). Add idempotent `post_login_warmup`.

After this slice, an integration test should be able to:

1. Construct a `Session` from a `BrowserManager` + `SiteAuthAdapter`.
2. Call `session.start()` and either restore an authenticated session or return `False`.
3. Call `session.login(email, password)` against the fixture server and observe the saved `storage_state`.
4. Trigger a "challenge" URL on the fixture server and observe `ChallengePolicy.handle()` waiting (headed) or failing fast (headless).
5. Run `session.post_login_warmup()` exactly once per process even when called twice.

S2 ships **no** real-site integration; the reference app comes in S9.

---

## 2. Deliverables

### 2.1 New modules

| Path | Source | Notes |
|---|---|---|
| `src/gsv/session/__init__.py` | new | Re-export `Session`, `SiteAuthAdapter`, `ChallengePolicy`, `SessionAuthError`. |
| `src/gsv/session/adapter.py` | new (referencing CE `auth.py` constants) | `SiteAuthAdapter` dataclass per [ARCHITECTURE.md §4.2](../ARCHITECTURE.md#42-session--auth-layer-gsvsession). |
| `src/gsv/session/runner.py` | from CE `src/scraper/auth.py` (Reference bucket) | `Session` class with the five-stage flow. |
| `src/gsv/session/challenge.py` | from CE `auth.py` lines 197–230 | `ChallengePolicy` (`headed_wait`, `headless_fail`), with `handle(page) -> bool`. |
| `src/gsv/session/warmup.py` | from CE `auth.py` lines 252–273 | `post_login_warmup(page, warmup_url, scroll_count_range, idle_delay_range)`. |
| `src/gsv/session/diagnostics.py` | from CE `auth.py` lines 121–146 | `log_login_diagnostics(page, adapter, reason)` — generic, no LinkedIn strings. |

Extend `src/gsv/config/model.py`: add the auth-relevant fields S2 needs:

- `VisitorConfig.manual_verification_timeout_seconds: int = 300`
- `VisitorConfig.pacing.post_login_warmup: bool = True` (already in S1 sketch — confirm)
- `SiteConfig.auth: SiteAuthConfig` (the YAML sub-block from [ARCHITECTURE.md §4.8](../ARCHITECTURE.md#48-configuration-gsvconfig))
- `SiteAuthConfig`: dataclass mirroring the YAML keys (login_url, auth_marker_url, selector lists, warmup_url).

### 2.2 New tests

| Path | Purpose |
|---|---|
| `tests/session/test_adapter.py` | `SiteAuthAdapter` defaults, predicate composition, validation. |
| `tests/session/test_runner.py` | Full flow against fixture server: cookie click, variant detection, credential entry (using `human_type` mocks for speed), success classification, failure-still-on-login classification. |
| `tests/session/test_challenge.py` | Headed mode polls until URL changes; headless mode returns `False` immediately. Use a fake `Page` that mutates `url` after N polls. |
| `tests/session/test_warmup.py` | Idempotent: second invocation is a no-op. |
| `tests/session/test_diagnostics.py` | Per-selector counts logged at error level when login fails. |
| `tests/fixtures/server.py` | Extend with `/login`, `/login?challenge=1`, `/feed`, `/cookie-consent` routes that simulate the CE login flow shape. |

---

## 3. Reuse map

| CE source | CE lines | Bucket | Becomes | Generalization |
|---|---|---|---|---|
| `src/scraper/auth.py` | 23–48 (URL + selector constants) | **Skip** | — | LinkedIn-specific. The values seed the `apps/example/auth.py` adapter in S9 (or seed a public test fixture in S2's tests). |
| `src/scraper/auth.py` | 51–82 (`__init__`, `start`, `_check_authenticated`) | **Adapt** | `gsv/session/runner.py` `Session` class | Replace `LOG.info("Restored authenticated session")` with framework-neutral wording. Replace `CHECK_URL` → `adapter.auth_marker_url`. Replace `"/feed" in url and "/login" not in url` → `adapter.auth_marker_predicate(url)`. |
| `src/scraper/auth.py` | 84–94 (`is_authenticated`, `_is_feed_url`, `_is_verification_url`) | **Adapt** | `gsv/session/runner.py` | `_is_feed_url` → `_is_authenticated_url`, sources predicate from adapter. `_is_verification_url` → `adapter.challenge_url_predicate(url)` (default: contains `checkpoint` or `challenge`, kept verbatim from CE). |
| `src/scraper/auth.py` | 96–127 (`_try_click`, `_try_type`, `_selector_count`) | **Copy** | `gsv/session/runner.py` (private helpers) | Mechanical only. The selector list comes from `adapter.*_selectors` instead of module constants. |
| `src/scraper/auth.py` | 129–146 (`_log_login_diagnostics`) | **Adapt** | `gsv/session/diagnostics.py` `log_login_diagnostics` | Iterate `adapter.username_selectors`, `password_selectors`, etc., to count visible matches. The logged message is keyed by selector name, not LinkedIn-specific. |
| `src/scraper/auth.py` | 148–163 (`_prepare_login_page`) | **Adapt** | `gsv/session/runner.py` | Replace `COOKIE_BUTTON_SELECTORS` → `adapter.cookie_consent_selectors`. Replace `ALT_ACCOUNT_SELECTORS` → `adapter.variant_trigger_selectors`. Wait selector becomes `adapter.username_selectors`. |
| `src/scraper/auth.py` | 165–195 (`_fill_credentials`, `_submit_login_form`) | **Copy** (selector lists from adapter) | `gsv/session/runner.py` | The post-submit `random_delay(self.config.min_delay, self.config.max_delay)` becomes `await self._auth_delay_profile.sleep()` — ties to S3's `DelayProfile`. **In S2, hardcode a temporary `random_delay(0.5, 1.0)` and add a TODO referencing S3.** |
| `src/scraper/auth.py` | 197–230 (`_wait_for_manual_verification`, `_handle_verification_checkpoint`) | **Adapt** | `gsv/session/challenge.py` `ChallengePolicy.handle(page) -> bool` | Inputs: `page`, `mode: "headed"|"headless"`, `timeout_seconds`, `auth_marker_predicate`. Polls URL once per second; returns `True` on success. Headless: log + return `False`. Drop "LinkedIn" from strings. |
| `src/scraper/auth.py` | 232–250 (`_wait_for_login_completion`) | **Adapt** | `gsv/session/runner.py` `_wait_for_login_completion` | Replace `wait_for_url("**/feed/**", timeout=15000)` with `wait_for_url(adapter.auth_marker_wait_glob, timeout=...)` where `auth_marker_wait_glob` defaults to a glob built from `auth_marker_url`. Replace LinkedIn-specific strings. |
| `src/scraper/auth.py` | 252–273 (`post_login_warmup`) | **Copy** | `gsv/session/warmup.py` | Replace `FEED_URL` → `adapter.warmup_url`. If `warmup_url is None`, the warmup is a no-op. Idempotency latch (`_warmup_done`) lives on `Session`, not in the helper. |
| `src/scraper/auth.py` | 275–317 (`login`) | **Adapt** | `gsv/session/runner.py` `login(credentials)` | `email`/`password` come from a `Credentials` object passed to `login`, not from `self.config.linkedin_email`. Configuration of credentials is the application's responsibility (Open question Q1 below). |
| `src/scraper/auth.py` | 319–329 (`new_page`, `close`) | **Copy** | `gsv/session/runner.py` | None. |

---

## 4. Step-by-step

### Step 2.1 — Define the adapter

Implement `gsv/session/adapter.py`:

```python
@dataclass(frozen=True)
class SiteAuthAdapter:
    auth_marker_url: str
    login_url: str
    cookie_consent_selectors: tuple[str, ...] = ()
    variant_trigger_selectors: tuple[str, ...] = ()
    username_selectors: tuple[str, ...] = ()
    password_selectors: tuple[str, ...] = ()
    submit_selectors: tuple[str, ...] = ()
    warmup_url: str | None = None
    extra_init_scripts: tuple[str, ...] = ()
    allowed_host_globs: tuple[str, ...] = ()
    auth_marker_predicate: Callable[[str], bool] | None = None
    challenge_url_predicate: Callable[[str], bool] = lambda url: "checkpoint" in url or "challenge" in url
    auth_marker_wait_glob: str | None = None
```

`auth_marker_predicate=None` defaults to a substring match against `auth_marker_url`'s path.

### Step 2.2 — Loader changes

Extend `gsv/config/loader.py` to parse the `sites.<name>.auth` block into a `SiteAuthConfig` (raw fields). Then `SiteAuthAdapter.from_config(site_auth_config) -> SiteAuthAdapter` builds the runtime object (allowing `extra_init_scripts` to come from a list of inline JS strings or file paths).

### Step 2.3 — Diagnostics helper

Lift `_log_login_diagnostics`, but iterate the adapter's selector tuples. Output schema:

```
session.login.diagnostics reason=<r> url=<u> title=<t>
  username_selectors={<sel>: <count>, ...}
  password_selectors=...
  submit_selectors=...
  cookie_consent_selectors=...
  variant_trigger_selectors=...
```

Tests assert per-selector counts appear in the log record.

### Step 2.4 — Challenge policy

`gsv/session/challenge.py`:

```python
class ChallengePolicy:
    def __init__(self, *, mode: Literal["headed", "headless"], timeout_seconds: int): ...
    async def handle(self, page: Page, auth_marker_predicate: Callable[[str], bool]) -> bool: ...
```

`mode` is derived from `visitor.headless` at construction. Tests stub `Page` and verify polling cadence.

### Step 2.5 — Warmup

`gsv/session/warmup.py`:

```python
async def post_login_warmup(
    page: Page,
    warmup_url: str | None,
    *,
    initial_delay_range: tuple[float, float] = (3.0, 6.0),
    scroll_count_range: tuple[int, int] = (1, 3),
    closing_delay_range: tuple[float, float] = (2.0, 5.0),
) -> bool: ...
```

Returns `True` if warmup ran; `False` if `warmup_url is None`. Caller is responsible for idempotency (Session keeps the latch).

### Step 2.6 — Session class

Implement `gsv/session/runner.py`:

```python
class Session:
    def __init__(self, browser: BrowserManager, adapter: SiteAuthAdapter, config: VisitorConfig): ...
    async def start(self) -> None: ...
    async def login(self, credentials: Credentials) -> bool: ...
    async def post_login_warmup(self) -> None: ...
    async def new_page(self) -> Page: ...
    async def close(self) -> None: ...

    @property
    def is_authenticated(self) -> bool: ...
```

Internal flow mirrors CE `LinkedInSession.login` line-for-line; only constants and selector sources change.

### Step 2.7 — Credentials

Add `gsv/session/credentials.py`:

```python
@dataclass(frozen=True)
class Credentials:
    username: str
    password: str

    @classmethod
    def from_env(cls, prefix: str) -> Credentials:
        return cls(
            username=os.environ[f"{prefix}_USERNAME"],
            password=os.environ[f"{prefix}_PASSWORD"],
        )
```

Apps construct `Credentials.from_env("EXAMPLE_SITE")`. The framework never reads credentials from YAML.

### Step 2.8 — Tests

- Extend `tests/fixtures/server.py` with the auth flow shape (cookie banner page, login form, feed page, challenge page that flips back to feed after N requests).
- `tests/session/test_runner.py::test_login_happy_path` runs the full flow against headless Chromium.
- `tests/session/test_runner.py::test_login_diagnostics_emitted_on_failure` deletes the username selector from the fixture and asserts the diagnostics log shows zero counts.
- `tests/session/test_challenge.py::test_headed_completes_when_url_flips` and `::test_headless_returns_false`.

### Step 2.9 — Documentation

- `src/gsv/session/README.md`: state machine diagram (ASCII), one-liner per stage, link to architecture §4.2.
- Update [ARCHITECTURE.md §14](../ARCHITECTURE.md#14-open-questions) if Q1 below is resolved differently than recommended.

---

## 5. Acceptance criteria

- [ ] `pytest tests/session` is green; coverage ≥ 90% on new modules.
- [ ] No `linkedin`, `feed`, or `checkpoint` strings appear in `src/gsv/session/` (the substring `"checkpoint"` may appear only as the default value in `challenge_url_predicate` — and that default is in `adapter.py`).
- [ ] `Session.login` falls back through every selector in the adapter's tuple before failing.
- [ ] `Session.post_login_warmup` is idempotent: a second invocation is a no-op (no extra page, no extra navigation).
- [ ] `ChallengePolicy(headless).handle(...)` returns `False` and logs at WARN exactly once.
- [ ] `Session.start()` correctly classifies an existing storage state as authenticated when fixture server returns the auth marker URL.
- [ ] `mypy src/gsv/session` passes strict.

---

## 6. Out of scope (deferred)

- `DelayProfile.auth` — S3. Until S3 lands, S2 uses bare `random_delay(0.5, 1.0)` with a `# TODO(S3)` marker.
- 2FA / OTP entry — never. The skeleton's policy is "manual escalation only".
- Credential rotation, vault integration — out of scope. Apps can subclass `Credentials.from_env` if they need a vault.
- Re-login after session expiry mid-run — handled by `RunController` retry policy in S7. S2 only handles login at session start.

---

## 7. Dependencies

- Upstream: **S1** (`gsv.browser`, `gsv.config`).
- Downstream blockers: S4 (visit runner uses `Session.new_page`), S7 (run controller orchestrates auth + execute).

---

## 8. Open questions

| ID | Question | Recommendation | Resolve in |
|---|---|---|---|
| Q1 | Where do credentials live? `.env` only? `Credentials.from_env`? Pluggable provider? | `.env` for v0 with a prefix-per-site convention (`EXAMPLE_USERNAME`, `EXAMPLE_PASSWORD`). Pluggable provider can wait until a real second site demands it. | S2 |
| Q2 | Should `auth_marker_wait_glob` default to deriving from `auth_marker_url`, or require explicit specification? | Auto-derive: `f"{urlparse(auth_marker_url).scheme}://{netloc}{path_prefix}/**"`. Adapters can override. | S2 |
| Q3 | What is the right behavior when neither positive nor negative URL match fires after `_check_authenticated`? CE returns `False` (treat as unauthenticated). Keep that? | Yes — false negative is safer than a false positive. Document explicitly. | S2 |
| Q4 | Should `post_login_warmup` be controlled by `visitor.pacing.post_login_warmup` or by `site.auth.warmup_url is not None`? | Both: warmup runs only if BOTH the visitor flag is true AND the site provides a warmup URL. | S2 |

---

## 9. Reviewer checklist

- [ ] All login-flow constants come from `SiteAuthAdapter`, not module-level globals.
- [ ] No site-specific URLs in `src/gsv/session/`.
- [ ] `Session.login` carries `Credentials`, not raw strings.
- [ ] Diagnostics log emits the selector tuple by name in a single record (not multiple logs).
- [ ] `ChallengePolicy` mode is wired from `visitor.headless`, not a separate flag.
- [ ] Test coverage exercises every selector-fallback path (username, password, submit, cookie, variant).
