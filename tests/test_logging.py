import logging

from unipus_web.logging_setup import BusLogHandler, LogStore


def test_log_store_keeps_capacity_and_filters_and_sequences():
    store = LogStore(capacity=3)
    for i, level in enumerate(["INFO", "ERROR", "DEBUG", "WARN"]):
        store.add(level, "test", f"m{i}")

    assert [r["message"] for r in store.query()] == ["m1", "m2", "m3"]
    # min_level 语义是“至少该级别”，因此 WARN 会把 ERROR 一起带出
    assert [r["level"] for r in store.query(min_level="WARN")] == ["ERROR", "WARN"]
    assert store.query(after_seq=2)[0]["message"] == "m2"


def test_bus_log_handler_captures_message_and_task_id():
    store = LogStore()
    handler = BusLogHandler(store)
    logger = logging.getLogger("unipus-test-logger")
    logger.handlers = [handler]
    logger.setLevel(logging.DEBUG)
    logger.propagate = False

    logger.info("hello", extra={"task_id": "t1"})

    record = store.query()[-1]
    assert record["message"] == "hello"
    assert record["task_id"] == "t1"
    assert record["level"] == "INFO"


def test_clear_empties_the_store():
    store = LogStore()
    store.add("INFO", "t", "x")
    store.clear()
    assert store.query() == []
