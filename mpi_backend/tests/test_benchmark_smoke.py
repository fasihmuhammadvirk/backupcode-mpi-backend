import pytest

pytest.importorskip("pytest_benchmark", reason="pytest-benchmark not installed")


@pytest.mark.benchmark(group="health")
def test_health_benchmark(client, benchmark):
    def _call():
        res = client.get("/health")
        assert res.status_code == 200
        return res

    benchmark(_call)

