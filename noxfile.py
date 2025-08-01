import nox

# With pyenv we need to make the environments discoverable with
# `pyenv global 3.12 3.13`
# @nox.session(python=["3.10", "3.11", "3.12", "3.13"])
@nox.session(python=["3.12", "3.13"])
def tests(session):
    session.install(".")
    session.run("make", "clean")
    session.run("make", "test")
