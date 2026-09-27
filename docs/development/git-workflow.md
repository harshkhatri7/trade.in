# Git workflow

---

## 1. Branches

| Branch   | Role                                                       |
| -------- | ---------------------------------------------------------- |
| `main`   | Stable. Always passes the full validation gate.            |
| others   | Short-lived: `phase-<n>/…`, `fix/…`, `docs/…`, `chore/…`   |

Phase 0 starts with a single `main`. There is **no remote configured** and
nothing is pushed automatically.

---

## 2. Commits

[Conventional Commits](https://www.conventionalcommits.org/):

```text
<type>: <short imperative summary>

<body: why, what changed, anything left open>

<footer: BREAKING CHANGE, issue refs>
```

Types used here: `feat`, `fix`, `docs`, `test`, `chore`, `refactor`, `ci`,
`perf`, `build`.

Rules:

- One logical change per commit.
- No formatting churn mixed with behaviour changes.
- No secrets, credentials, personal data or generated datasets.
- No repository-wide reformat inside an unrelated commit.
- Never rewrite published history; never `git push --force` on `main`.

---

## 3. Pre-commit gate

Run before every commit:

```powershell
npm run check
```

Which is: Prettier → ESLint → `tsc --noEmit` → Vitest → pytest.

Optional but recommended: `npm run health` to confirm the environment itself
is still sound.

---

## 4. What must never be committed

Enforced by `.gitignore` and by `tests/security/test_no_secrets_committed.py`:

- `.env` and any real credential;
- `node_modules/`, `.venv/`, build output, coverage;
- datasets (`data/raw`, `data/clean`, `data/features`, parquet/feather/h5);
- local databases, logs, caches, notebooks' checkpoint state;
- OS and IDE droppings (`Thumbs.db`, `.DS_Store`, `.idea/`).

If you need to share a dataset, share the **manifest and recipe**, not the
bytes.

---

## 5. Review checklist

For every change:

- [ ] In scope for the current phase; no out-of-scope directories touched.
- [ ] Full validation gate green locally.
- [ ] New behaviour has tests; bug fixes have regression tests.
- [ ] No secret, no personal data, no generated artefact.
- [ ] Safety invariants intact: live trading still disabled, risk still
      independent, gate still refusing `live`.
- [ ] Documentation updated with the behaviour it describes.
- [ ] Changelog entry if the change is user- or operator-visible.
- [ ] Honest description of anything unfinished.

---

## 6. Releases

- Versions live in `package.json`, `pyproject.toml`,
  `src/harsh_quant_os/version.py` and `CHANGELOG.md`, and must agree.
- The display version (`0.1.0-alpha`) and the PEP 440 form (`0.1.0a0`)
  describe the same release.
- Tags are created only after a green CI run on `main`.

---

## 7. Recovering from mistakes

| Mistake                          | Correct response                                  |
| -------------------------------- | ------------------------------------------------- |
| Committed to the wrong branch    | Move the commit forward; do not rewrite `main`    |
| Committed a secret               | Rotate the credential first, then remove it, then report the exposure |
| Bad merge on `main`              | Revert commit; never force-push                   |
| History needs rewriting          | **Stop and ask** — history rewriting is prohibited |

Rotating a leaked credential is always more important than cleaning the
repository. Do both, in that order.
