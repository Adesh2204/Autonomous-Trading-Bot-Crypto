"""Retired Angel One login utility; the competition clone cannot authenticate."""
from disabled_angel_client import DisabledAngelOneClient


def run_login_test() -> None:
    DisabledAngelOneClient()


if __name__ == "__main__":
    run_login_test()
