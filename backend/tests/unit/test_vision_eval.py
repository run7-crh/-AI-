"""视觉观察评估口径回归测试（纯函数，不触网）。"""

from eval.run_vision_eval import (
    _case_damage_cue_hit,
    _case_damage_false_positive,
    _case_image_type_correct,
    _case_text_recall,
)


def _observation(**overrides) -> dict:
    base = {
        "image_type": "screenshot",
        "visible_text": "ERROR 30010\nMotor overload detected",
        "objects": [],
        "damage_signals": [],
        "notes": "",
        "uncertain": "",
    }
    base.update(overrides)
    return base


def test_text_recall_is_case_insensitive_and_bounded():
    recall, denominator = _case_text_recall(_observation(), ["ERROR 30010", "motor overload"])
    assert (recall, denominator) == (1.0, 2)
    recall, denominator = _case_text_recall(_observation(), ["ERROR 30010", "missing line"])
    assert (recall, denominator) == (0.5, 2)
    # 无 gold 时无失败，也不冒充满分（分母为 0 由调用方汇总处理）
    assert _case_text_recall(_observation(), []) == (1.0, 0)


def test_damage_false_positive_flags_only_unexpected_signals():
    assert _case_damage_false_positive(_observation(damage_signals=["电池鼓包"])) is True
    assert _case_damage_false_positive(_observation()) is False


def test_damage_cue_hit_requires_all_keywords():
    hit, denominator = _case_damage_cue_hit(_observation(damage_signals=["桨叶末端缺口"]), ["桨叶末端缺口"])
    assert (hit, denominator) == (True, 1)
    hit, _ = _case_damage_cue_hit(_observation(damage_signals=["缺口"]), ["桨叶末端缺口"])
    assert hit is False
    assert _case_damage_cue_hit(_observation(), [])[0] is False


def test_damage_cue_hit_tolerates_inserted_auxiliary_chars():
    # 模型改写"桨叶末端缺口"→"桨叶末端有缺口"：语义一致，字符覆盖 6/6，不应误判未命中
    hit, denominator = _case_damage_cue_hit(_observation(damage_signals=["桨叶末端有缺口"]), ["桨叶末端缺口"])
    assert (hit, denominator) == (True, 1)
    # 完全无关的信号：覆盖率应低于阈值
    hit, _ = _case_damage_cue_hit(_observation(damage_signals=["外观正常"]), ["电池鼓包"])
    assert hit is False


def test_image_type_check_is_none_when_gold_absent():
    assert _case_image_type_correct(_observation(), None) is None
    assert _case_image_type_correct(_observation(), "screenshot") is True
    assert _case_image_type_correct(_observation(image_type="physical"), "screenshot") is False
