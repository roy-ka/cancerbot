"""Regression test for a real bug: .dockerignore was missing .venv/,
.venv-nlp/, and pyvenv.cfg, so `COPY . .` in the root Dockerfile shipped
local dev virtualenvs into the built image — 1.2GB -> 3.3GB, and every
"vulnerable dependency" Trivy found (cryptography, msgpack, pyasn1,
setuptools, urllib3) turned out to be a stale package bundled inside one of
those copied-in venvs, not anything actually installed into /opt/venv at
build time. .gitignore already excluded these from source control; Docker
doesn't consult .gitignore, so .dockerignore needs its own copy of the same
entries.
"""
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def _read_lines(path: Path) -> set[str]:
    return {
        line.strip()
        for line in path.read_text().splitlines()
        if line.strip() and not line.strip().startswith("#")
    }


class TestDockerignoreExcludesLocalVenvs:
    def test_the_exact_regression_is_covered(self):
        """The specific entries whose absence caused the bug."""
        dockerignore = _read_lines(REPO_ROOT / ".dockerignore")
        for entry in (".venv/", ".venv-nlp/", "pyvenv.cfg"):
            assert entry in dockerignore, (
                f"{entry!r} is missing from .dockerignore — local dev "
                "virtualenvs would leak into the built Docker image again "
                "(see this test's module docstring)."
            )

    def test_every_gitignored_venv_entry_is_also_dockerignored(self):
        """Generalizes the fix: any local-virtualenv-style entry added to
        .gitignore's "Python virtual environments" section in the future
        must get a matching .dockerignore entry too, since `COPY . .` in
        the root Dockerfile doesn't consult .gitignore at all — this is
        the actual class of bug, not just the one instance of it."""
        gitignore_lines = REPO_ROOT.joinpath(".gitignore").read_text().splitlines()

        venv_entries: list[str] = []
        in_section = False
        for line in gitignore_lines:
            stripped = line.strip()
            if stripped.startswith("# ---"):
                in_section = "python virtual environments" in stripped.lower()
                continue
            if in_section and stripped:
                venv_entries.append(stripped)

        assert venv_entries, "Could not find the 'Python virtual environments' section in .gitignore"

        dockerignore = _read_lines(REPO_ROOT / ".dockerignore")
        missing = [e for e in venv_entries if e not in dockerignore]
        assert not missing, (
            f".gitignore excludes {missing} as local virtualenvs but .dockerignore "
            "doesn't — Docker's COPY . . doesn't read .gitignore, so these would "
            "leak into the built image."
        )
