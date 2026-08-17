"""url_parser 模块单元测试（阶段一）。

运行：python -m unittest discover -s tests -v
"""

import sys
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from url_parser import (  # noqa: E402
    MAJSOUL_DOMAINS,
    PaipuIdError,
    PaipuUrlError,
    decode_anonymous_uuid,
    encode_anonymous_uuid,
    extract_paipu_value,
    parse_paipu_url,
    validate_paipu,
)

# 社区公开的真实牌谱数据（普通/匿名成对）
PLAIN_UUID = "200515-cfbe0120-c92c-44ad-bdfc-ebfef3a33a10"
ANON_UUID = "jijpmr-0415suwv-971c-67ei-ilom-qottvksmnvnn"
MATCH_ID = "89702544"

PLAIN_URL = (
    f"https://game.maj-soul.com/1/?paipu={PLAIN_UUID}_a{MATCH_ID}"
)
ANON_URL = (
    f"https://game.maj-soul.com/1/?paipu={ANON_UUID}_a{MATCH_ID}_2"
)
# 旧式链接（2019 年，无 _a 后缀）
OLD_URL = "https://www.majsoul.com/1/?paipu=191105-de74c8bc-1725-4171-9587-9b91d0c6dddf"


class TestPaipuIdValidation(unittest.TestCase):
    def test_valid_plain_uuid(self):
        self.assertEqual(validate_paipu(PLAIN_UUID), PLAIN_UUID)

    def test_valid_with_match_id(self):
        self.assertEqual(validate_paipu(f"{PLAIN_UUID}_a{MATCH_ID}"), PLAIN_UUID)

    def test_valid_anonymous(self):
        self.assertEqual(validate_paipu(f"{ANON_UUID}_a{MATCH_ID}_2"), ANON_UUID)

    def test_valid_anonymous_without_match_id(self):
        self.assertEqual(validate_paipu(f"{ANON_UUID}_2"), ANON_UUID)

    def test_strip_whitespace(self):
        self.assertEqual(validate_paipu(f"  {PLAIN_UUID}  "), PLAIN_UUID)

    def test_empty_raises(self):
        with self.assertRaises(PaipuIdError):
            validate_paipu("")

    def test_wrong_segments_raises(self):
        for bad in (
            "200515-cfbe0120-c92c-44ad-bdfc",          # 段数不足
            "200515-cfbe0120-c92c-44ad-bdfc-ebfef3a33a1",  # 末段长度不足
            "200515-CFBE0120-c92c-44ad-bdfc-ebfef3a33a10",  # 大写字母
            "200515-cfbe0120-c92c-44ad-bdfc-ebfef3a33a10_x",  # 非法后缀
            "200515-cfbe0120-c92c-44ad-bdfc-ebfef3a33a10_a12x",  # match_id 非数字
            "200515-cfbe0120-c92c-44ad-bdfc-ebfef3a33a10_2_2",  # 重复后缀
            "200515_cfbe0120_c92c_44ad_bdfc_ebfef3a33a10",  # 分隔符错误
        ):
            with self.assertRaises(PaipuIdError, msg=bad):
                validate_paipu(bad)


class TestExtractPaipuValue(unittest.TestCase):
    def test_query_first(self):
        self.assertEqual(extract_paipu_value(PLAIN_URL), f"{PLAIN_UUID}_a{MATCH_ID}")

    def test_paipu_not_first_param(self):
        url = f"https://game.maj-soul.com/1/?foo=bar&paipu={PLAIN_UUID}"
        self.assertEqual(extract_paipu_value(url), PLAIN_UUID)

    def test_fragment_ignored(self):
        url = f"https://game.maj-soul.com/1/?paipu={PLAIN_UUID}#section"
        self.assertEqual(extract_paipu_value(url), PLAIN_UUID)

    def test_missing_param_raises(self):
        with self.assertRaises(PaipuUrlError):
            extract_paipu_value("https://game.maj-soul.com/1/")

    def test_empty_raises(self):
        with self.assertRaises(PaipuUrlError):
            extract_paipu_value("   ")


class TestParsePaipuUrl(unittest.TestCase):
    def test_plain_url(self):
        info = parse_paipu_url(PLAIN_URL)
        self.assertEqual(info.uuid, PLAIN_UUID)
        self.assertEqual(info.match_id, MATCH_ID)
        self.assertFalse(info.anonymous)
        self.assertEqual(info.date, date(2020, 5, 15))
        self.assertEqual(info.paipu, f"{PLAIN_UUID}_a{MATCH_ID}")

    def test_anonymous_url(self):
        info = parse_paipu_url(ANON_URL)
        self.assertEqual(info.uuid, ANON_UUID)
        self.assertEqual(info.match_id, MATCH_ID)
        self.assertTrue(info.anonymous)
        self.assertIsNone(info.date)

    def test_old_style_url(self):
        info = parse_paipu_url(OLD_URL)
        self.assertEqual(info.uuid, "191105-de74c8bc-1725-4171-9587-9b91d0c6dddf")
        self.assertIsNone(info.match_id)
        self.assertFalse(info.anonymous)
        self.assertEqual(info.date, date(2019, 11, 5))

    def test_century_interpretation(self):
        # 70 以上按 19xx 处理（1900 年代），以下按 20xx
        self.assertEqual(parse_paipu_url(
            f"https://game.maj-soul.com/1/?paipu=991231-abcdef01-2345-6789-abcd-ef0123456789"
        ).date, date(1999, 12, 31))
        self.assertEqual(parse_paipu_url(
            f"https://game.maj-soul.com/1/?paipu=200515-cfbe0120-c92c-44ad-bdfc-ebfef3a33a10"
        ).date, date(2020, 5, 15))

    def test_invalid_date_raises(self):
        # 200230 = 2020-02-30，不存在的日期
        with self.assertRaises(PaipuUrlError):
            parse_paipu_url(
                f"https://game.maj-soul.com/1/?paipu=200230-cfbe0120-c92c-44ad-bdfc-ebfef3a33a10"
            )

    def test_foreign_host_raises(self):
        with self.assertRaises(PaipuUrlError):
            parse_paipu_url(f"https://evil.example.com/1/?paipu={PLAIN_UUID}")

    def test_check_host_disabled(self):
        info = parse_paipu_url(
            f"https://localhost:8000/1/?paipu={PLAIN_UUID}", check_host=False
        )
        self.assertEqual(info.uuid, PLAIN_UUID)

    def test_bare_paipu_accepted(self):
        info = parse_paipu_url(f"paipu={PLAIN_UUID}")
        self.assertEqual(info.uuid, PLAIN_UUID)

    def test_empty_url_raises(self):
        with self.assertRaises(PaipuUrlError):
            parse_paipu_url("")

    def test_majsoul_domains(self):
        self.assertIn("majsoul.com", MAJSOUL_DOMAINS)
        self.assertIn("maj-soul.com", MAJSOUL_DOMAINS)


class TestAnonUuidCodec(unittest.TestCase):
    def test_encode_known_pair(self):
        self.assertEqual(encode_anonymous_uuid(PLAIN_UUID), ANON_UUID)

    def test_decode_known_pair(self):
        self.assertEqual(decode_anonymous_uuid(ANON_UUID), PLAIN_UUID)

    def test_roundtrip(self):
        self.assertEqual(decode_anonymous_uuid(encode_anonymous_uuid(PLAIN_UUID)), PLAIN_UUID)

    def test_encode_invalid_raises(self):
        with self.assertRaises(PaipuIdError):
            encode_anonymous_uuid("not-a-valid-uuid")
        with self.assertRaises(PaipuIdError):
            decode_anonymous_uuid("not-a-valid-uuid")


if __name__ == "__main__":
    unittest.main()
