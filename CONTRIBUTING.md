# Contributing

Small app, small rules. The most useful thing you can do is run the suites before you push —
they take about four minutes in total and they catch more than they look like they should.

## Getting it running

```bash
python3 -m venv backend/.venv
backend/.venv/bin/pip install -r backend/requirements-dev.txt   # runtime + tests
bash scripts/setup_frontend.sh                                  # npm install + build
bash run.sh                                                     # serves everything on :6770
```

If your shell exports a `PYTHONPATH`, run every `pip` line as `env -u PYTHONPATH …`: an inherited
one makes pip install into a hollow venv that silently imports another interpreter's packages.

## What CI runs, and what to run yourself

| command | what it covers |
|---|---|
| `cd backend && ../backend/.venv/bin/python -m pytest -q` | the API, the calendar rules, backup and restore |
| `python scripts/smoke_release.py` | a fresh database, an upgrade over real plans, a restore |
| `cd frontend && npm test` | the day arithmetic, the write queue, the all-clear rule |
| `cd frontend && npm run check:ui -- http://127.0.0.1:6770` | the browser: drags, keyboard, focus, axe, artwork, icons |
| `python scripts/make_art.py --check` | the artwork: budgets, dimensions, page grounds, source hashes |
| `python scripts/make_icons.py --check` | the icons: every size, both safe zones, the favicon |

Both CI jobs must pass before a pull request can merge into `main`. The two job names —
**API and calendar rules** and **Browser checks** — are the required checks, so if you rename a
job in `.github/workflows/tests.yml`, update the branch protection in the same breath or merges
will wait forever.

## Branches

`main` is what the Pi runs; `development` is where work lands first. The owner pushes to both
directly; everyone else opens a pull request against `main` from a branch of their own. Merges
into `main` use `--no-ff`, so the history shows what arrived together — which is why linear
history is deliberately off.

## The house rules

These are features, and a change that breaks one is a bug even if the tests pass:

- **Nothing signals lateness.** No red, no urgency, no "you missed three tasks". A task from this
  morning you never got to simply sits there.
- **No streaks, no scores, no confetti, no mascot.** Completion is a square that fills.
- **Empty states are honest.** Say what is true, quietly, in a sentence. Never show a placeholder
  progress bar or a fake number.
- **44px touch targets**, and every primary action reachable with one thumb.
- **Dark mode, larger text and reduced motion are honoured.** Sizes are in `rem`; a fixed-width
  container that holds text has to grow with the reader's setting.
- **Colour is data.** The eight task colours are chosen by the user and validated by the API.
- **No AI in the product.** No co-planner, no automatic prioritising. Point an assistant at the
  API if you want one — it is a `POST /api/blocks`.

## How to write a check

The suites are the specification, so they are held to the same standard as the code:

- **Reproduce the bug first.** A regression test that fails on the current code, then the fix.
- **Falsify the check before trusting it.** Delete the migration, drop the header line, put the
  bug back — and confirm the check goes red. A gate nobody has seen fail is a gate nobody knows
  works. Every check added recently has a falsification recorded in its commit message.
- **Poll for outcomes, never bet on speed.** A check that asserts 300ms after a click measures
  the runner, not the app. `until()` exists for this; it fails rather than hangs. Fixed waits are
  only for checks where timing *is* the subject.
- **A missing element fails its check, not the run.** One unguarded `innerText()` on an absent
  element once took out every check after it; `textOf()` and `until()` exist so a failure stays a
  failure.
- **A README claim is an acceptance criterion.** If the docs say larger text is honoured, that is
  a test. If it says the artwork sits on the page, measure the pixels.

## Regenerating the artwork or the icons

Both are generated from committed sources by committed scripts, and CI checks the output:

```bash
env -u PYTHONPATH backend/.venv/bin/pip install -r scripts/requirements-art.txt
env -u PYTHONPATH backend/.venv/bin/python scripts/make_art.py      # empty states, card, banner
env -u PYTHONPATH backend/.venv/bin/python scripts/make_icons.py    # the icon, both layouts
```

Read the docstrings first. Two things there are load-bearing: the artwork is matched to the page
colour it sits on (an opaque illustration on the wrong ground shows as a rectangle), and the
sundial's ground is keyed to transparency so the hour rules run underneath it. `--check` measures
all of it and fails loudly.

`art/source/` holds the as-received copies, **not** the artist's masters — the files' own EXIF
says a photo manager re-encoded them. See `art/source/README.md`; `make_art.py` records their
hashes and refuses to let one be swapped quietly.

## Deploying

The Pi runs `sundial.service` (a systemd **user** unit) from a checkout of `main`, serving the
built app and the API from one process on `:6770`, proxied to the tailnet. To deploy:
`npm run build` in `frontend/`, then `systemctl --user restart sundial`.

The tree you edit is the tree that restarts, so do not develop on the deployed checkout. And set
`VITE_APP_URL` in `frontend/.env.local` (gitignored) at deploy time if you want the social-preview
tags absolute — leave it empty in the repo, because a wrong public URL baked into a build is worse
than a missing preview.
