# Testing EZ360PM

EZ360PM separates fast deterministic backend checks from opt-in rendered-browser
checks. Neither suite uses Render secrets, sends customer email, calls OpenAI, or
creates a real Stripe charge.

## Backend suite

```powershell
python manage.py test --parallel 4 -v 1
```

The backend suite covers services, forms, views, permissions, webhook contracts,
financial invariants, migrations, and operational checks. Run migration and lint
gates separately:

```powershell
ruff check accounts assistant browser_tests clients config core documents intake projects
python manage.py makemigrations --check --dry-run
python manage.py deployment_check
python manage.py data_audit --fail-on-warning
```

## Browser suite

Install the isolated browser dependencies once:

```powershell
python -m pip install -r requirements-browser.txt
python -m playwright install chromium
```

Then run the critical rendered workflows:

```powershell
python manage.py test browser_tests.critical_workflows -v 1
```

If the Playwright browser download is unavailable but Google Chrome is installed,
use the explicit local channel without weakening TLS verification:

```powershell
$env:PLAYWRIGHT_BROWSER_CHANNEL='chrome'
python manage.py test browser_tests.critical_workflows -v 1
```

Set `PLAYWRIGHT_HEADLESS=0` for local visual debugging. Each browser test writes a
trace to the ignored `test-results/` directory. GitHub Actions retains those
traces for seven days only when its browser job fails.

## CI structure

The `Quality` workflow runs independent backend and browser jobs in parallel.
The browser job installs a pinned Chromium version and uses disposable PostgreSQL
and email configuration. Live Stripe, Resend, OpenAI, DNS, backup, and restore
behavior remains an explicit operational acceptance check.

The current coverage map and remaining browser priorities are maintained in
[FEATURE_TEST_MATRIX.md](FEATURE_TEST_MATRIX.md). Every bug fix should add a
regression test that fails before the fix and passes afterward.
