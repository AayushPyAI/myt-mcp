import pytest


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture(autouse=True)
def server_browser_tools_on(monkeypatch):
    """The TAP, SATA, Viator, GetYourGuide and Ofran server tools are off in production (Chrome recipes replace them); the tests of those tools turn them on."""
    monkeypatch.setenv("TAP_SERVER_BROWSER", "1")
    monkeypatch.setenv("SATA_SERVER_BROWSER", "1")
    monkeypatch.setenv("VIATOR_SERVER_BROWSER", "1")
    monkeypatch.setenv("GYG_SERVER_BROWSER", "1")
    monkeypatch.setenv("OFRAN_SERVER_SEARCH", "1")


@pytest.fixture(autouse=True)
def _reset_server_read_state(tmp_path, monkeypatch):
    """The server-side page reads keep a cache, an hourly count and a pause list in the module (and a pause file): every test starts clean."""
    import myt_mcp.sites as sites
    monkeypatch.setattr(sites, "PAUSE_FILE", tmp_path / "paused_sites.json")
    from myt_mcp import answer_watch
    answer_watch._PENDING.clear()
    sites._CACHE.clear(); sites._READS.clear(); sites._PAUSED_UNTIL.clear(); sites._LAST_READ.clear()
    from myt_mcp.composed import COMPOSED
    from myt_mcp.ingest import STORE
    COMPOSED.clear()
    STORE.clear()
    sites._PART_FAILS.clear()
    yield
