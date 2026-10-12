from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from phone_watch.dingtalk_sync import row_form_values


class RowFormValuesTests(unittest.TestCase):
    def test_tipo_field_can_be_mapped_to_dingtalk_open_mold_marker(self) -> None:
        row = {
            "model": "HUAWEI 11111",
            "price": None,
            "source_url": "https://www.ithome.com/0/972/902.htm",
            "source_name": "IT之家",
        }

        with patch.dict(os.environ, {"DINGTALK_TIPO_FIELD": "标记开模"}, clear=False):
            values = row_form_values(
                row,
                model_field="Modelos型号",
                price_field="价格Precio de Celular",
                page_field="网站链接Pagina",
                sales_channel_field="销售渠道 Canales venta",
                tipo_value="幻影Fantasía Case",
                tipo_field="Tipo类型",
            )

        self.assertIn({"name": "标记开模", "value": "幻影Fantasía Case"}, values)
        self.assertNotIn({"name": "Tipo类型", "value": "幻影Fantasía Case"}, values)


if __name__ == "__main__":
    unittest.main()
