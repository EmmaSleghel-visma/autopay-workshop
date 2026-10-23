from fraud_detection.web import create_app


def test_app_starts_and_reports_health(tmp_path):
    app = create_app(str(tmp_path / "fraud.db"))
    response = app.test_client().get("/health")
    assert response.status_code == 200
    assert response.get_json() == {"ok": True}
