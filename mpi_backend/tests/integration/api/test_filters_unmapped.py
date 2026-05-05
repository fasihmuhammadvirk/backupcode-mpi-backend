def test_unmapped_items_validation(client):
    # Missing required body
    res = client.post("/filter/unmapped-items")
    assert res.status_code in (400, 422)

    # Invalid item_type
    res = client.post("/filter/unmapped-items", json={"item_type": "invalid"})
    assert res.status_code == 400 or res.status_code == 422
