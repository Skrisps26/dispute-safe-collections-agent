import pytest


def pytest_addoption(parser):
    parser.addoption("--prompt-version", choices=["v1", "v2"], default="v2")


@pytest.hookimpl(optionalhook=True)
def pytest_json_runtest_metadata(item, call):
    if call.when == "call" and hasattr(item, "conversation"):
        return {"conversation":item.conversation}
    return {}
