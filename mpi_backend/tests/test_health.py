def test_health_ok(client):
    res = client.get("/health")
    assert res.status_code == 200
    data = res.json()
    assert data.get("status") == "healthy"
    assert data.get("message") == "MPI Backend is running"


def test_health_method_not_allowed(client):
    # Ensure non-GET returns 405 or 404 depending on router config
    res = client.post("/health")
    assert res.status_code in (404, 405)


def test_system_health_endpoint(client):
    """Test the new system health endpoint"""
    res = client.get("/health/system")
    assert res.status_code == 200
    data = res.json()
    assert data.get("status") == "success"
    assert "data" in data


def test_jobs_health_endpoint(client):
    """Test the new jobs health endpoint"""
    res = client.get("/health/jobs")
    assert res.status_code == 200
    data = res.json()
    assert data.get("status") == "success"
    assert "data" in data
    assert "active_jobs" in data["data"]
    assert "circuit_breaker" in data["data"]
    assert "recent_jobs" in data["data"]


def test_reset_circuit_breaker_endpoint(client):
    """Test the circuit breaker reset endpoint"""
    # Test with a non-existent job ID
    res = client.post("/health/jobs/nonexistent_job/reset")
    assert res.status_code == 200
    data = res.json()
    assert data.get("status") == "success"
    assert "no circuit breaker to reset" in data.get("message", "")
