import pytest

try:
    from locust import HttpUser, task, between  # type: ignore
    LOCUST_AVAILABLE = True
except Exception:  # pragma: no cover - optional dep
    LOCUST_AVAILABLE = False

if not LOCUST_AVAILABLE:  # pragma: no cover
    import pytest
    pytest.skip(
        "locust is not installed; skipping load test file",
        allow_module_level=True,
    )


class WebsiteUser(HttpUser):  # type: ignore[name-defined]
    wait_time = between(0.1, 0.3)  # type: ignore[name-defined]

    @task(3)  # type: ignore[name-defined]
    def health(self):
        self.client.get("/health")

    @task(2)  # type: ignore[name-defined]
    def filter_empty(self):
        self.client.post(
            "/filter",
            json={"filters": {}, "comparison_filters": []},
        )

