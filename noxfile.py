import nox

# With pyenv we need to make the environments discoverable with
# `pyenv global 3.12 3.13`
@nox.session(python=["3.12", "3.13"])
def tests(session):
    session.install(".")
    session.run("make", "test")
