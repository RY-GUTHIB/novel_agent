"""tests/test_file_utils.py - 文件工具单元测试"""

from novel_agent.core.file_utils import parse_chinese_number, parse_travel_time


def test_parse_chinese_number_arabic():
    assert parse_chinese_number("123") == 123


def test_parse_chinese_number_simple():
    assert parse_chinese_number("三") == 3


def test_parse_chinese_number_compound():
    assert parse_chinese_number("十二") == 12


def test_parse_chinese_number_hundred():
    assert parse_chinese_number("一百二十三") == 123


def test_parse_chinese_number_empty():
    assert parse_chinese_number("") == 0


def test_parse_travel_time_half_day():
    assert parse_travel_time("半日") == 0.5


def test_parse_travel_time_next_day():
    assert parse_travel_time("次日") == 1


def test_parse_travel_time_number_days():
    assert parse_travel_time("3日") == 3


def test_parse_travel_time_days_after():
    assert parse_travel_time("三日后") == 3


def test_parse_travel_time_shi_chen():
    assert parse_travel_time("两个时辰") == 0.25
