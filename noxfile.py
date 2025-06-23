import nox

# With pyenv we need to make the environments discoverable with
# `pyenv global 3.10.8 3.11.13 3.12.4`
@nox.session(python=["3.10.18", "3.11.13", "3.12.4"])
def tests(session):
    session.install(".")
    session.run("make", "test")
