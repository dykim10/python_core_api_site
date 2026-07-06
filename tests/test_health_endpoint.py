def test_health_endpoint_defined_in_main():
    main = open("main.py", encoding="utf-8").read()
    assert '@app.get("/health")' in main
    assert 'def health():' in main
