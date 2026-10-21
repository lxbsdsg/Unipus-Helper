import asyncio
import threading

from unipus_web.events import EventBus


def test_event_bus_delivers_from_thread_safely():
    async def scenario():
        bus = EventBus()
        bus.bind_loop(asyncio.get_running_loop())
        queue = bus.subscribe()
        bus.publish("task.updated", {"id": "t1"})
        event = await asyncio.wait_for(queue.get(), timeout=1)
        assert event["type"] == "task.updated"
        assert event["data"]["id"] == "t1"
        assert event["seq"] == 1

    asyncio.run(scenario())


def test_event_bus_accepts_publish_from_worker_thread():
    async def scenario():
        bus = EventBus()
        bus.bind_loop(asyncio.get_running_loop())
        queue = bus.subscribe()
        thread = threading.Thread(target=lambda: bus.publish("log.append", {"x": 1}))
        thread.start()
        thread.join()
        event = await asyncio.wait_for(queue.get(), timeout=1)
        assert event["type"] == "log.append"

    asyncio.run(scenario())


def test_publish_without_loop_is_a_noop():
    EventBus().publish("task.updated", {})  # 不应抛异常
