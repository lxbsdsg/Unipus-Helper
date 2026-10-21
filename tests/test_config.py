def test_ports_and_buffer_defaults():
    from unipus_web import config

    assert config.DEFAULT_PORT == 8765
    assert list(config.PORT_RANGE)[0] == 8765
    assert list(config.PORT_RANGE)[-1] == 8799
    assert config.LOG_BUFFER_SIZE == 5000
    assert config.DATA_DIR.is_absolute()


def test_annotator_constants_are_stable():
    from unipus_web import config

    assert config.ANNOTATOR_SECRET == "a824b379f126b8b7aa5e33dee83fb0a05aa7462c"
    assert config.ANNOTATOR_ISSUER == "c4f772063dcfa98e9c50"
    assert config.ANNOTATOR_AUDIENCE == "edx.unipus.cn"


def test_hosts_and_limits_are_stable():
    from unipus_web import config

    assert config.MAIN_HOST == "uai.unipus.cn"
    assert config.SSO_HOST == "sso.unipus.cn"
    assert config.CONTENT_HOST == "ucontent.unipus.cn"
    assert config.MAX_SUBMITS_PER_MINUTE == 5
    assert config.SUBMIT_RATE_COOLDOWN_MS == 120_000
    assert config.DEFAULT_TASK_END == 32503651200
