import queue

from vision_mcp.manager import KEY_URLS, PROVIDER_LABELS, Manager


def test_worker_ui_calls_are_queued_not_executed_directly():
    manager = object.__new__(Manager)
    manager._ui_queue = queue.Queue()
    called = []

    manager._queue_ui(called.append, "main-thread")

    assert called == []
    callback, args, kwargs = manager._ui_queue.get_nowait()
    callback(*args, **kwargs)
    assert called == ["main-thread"]


class DummyWidget:
    def __init__(self):
        self.options = {}

    def configure(self, **kwargs):
        self.options.update(kwargs)


def test_provider_numbers_follow_current_visual_order():
    manager = object.__new__(Manager)
    labels = [DummyWidget(), DummyWidget(), DummyWidget()]
    manager.provider_rows = [{"number_label": label} for label in labels]

    manager._refresh_provider_numbers()

    assert [label.options["text"] for label in labels] == ["#1", "#2", "#3"]


def test_status_label_uses_stdio_wording():
    manager = object.__new__(Manager)
    manager.status_label = DummyWidget()

    manager._set_status("stdio 模式 · 已就绪")

    assert manager.status_label.options["text"] == "●  stdio 模式 · 已就绪"


def test_supported_provider_labels_and_key_links_are_explicit():
    assert PROVIDER_LABELS["zhipu"] == "智谱开放平台 API"
    assert PROVIDER_LABELS["bailian"] == "阿里云百炼 Coding Plan"
    assert KEY_URLS["zhipu"].startswith("https://docs.bigmodel.cn/")
    assert KEY_URLS["bailian"].startswith("https://help.aliyun.com/")
