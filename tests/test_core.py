from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from openpyxl import Workbook, load_workbook

from core import (
    OperationRow,
    ProcessCard,
    generate_template_atomic,
    generate_template,
    group_operations,
    output_row_count,
    preview_rows,
)


class CoreRulesTest(unittest.TestCase):
    def make_card(self, operations: list[OperationRow]) -> ProcessCard:
        return ProcessCard(
            source_path=Path("sample.docx"),
            part_no="B.0001",
            part_name="测试件",
            operations=operations,
        )

    def test_single_blank_continuation_is_grouped(self) -> None:
        card = self.make_card(
            [
                OperationRow("钻", "14", "第一步"),
                OperationRow("", "15", "第二步"),
                OperationRow("检验", "16", "检验"),
            ]
        )

        rows = preview_rows([card])

        self.assertEqual(2, len(rows))
        self.assertEqual(("14", "钻", "第一步\n第二步"), rows[0][2:])
        self.assertEqual(("16", "检验", "检验"), rows[1][2:])

    def test_multiple_blank_continuations_are_grouped(self) -> None:
        card = self.make_card(
            [
                OperationRow("车", "4", "步骤一"),
                OperationRow("", "5", "步骤二"),
                OperationRow("", "6", "步骤三"),
            ]
        )

        rows = preview_rows([card])

        self.assertEqual(1, len(rows))
        self.assertEqual("4", rows[0][2])
        self.assertEqual("步骤一\n步骤二\n步骤三", rows[0][4])

    def test_wait_weld_is_always_excluded(self) -> None:
        card = self.make_card(
            [
                OperationRow("清洗", "34", "清洗"),
                OperationRow("", "35", "待焊。"),
            ]
        )

        self.assertEqual(1, output_row_count([card]))
        self.assertNotIn("待焊", preview_rows([card])[0][4])

    def test_custom_exclusion_and_original_range(self) -> None:
        result = group_operations(
            [
                OperationRow("车", "4", "第一步"),
                OperationRow("", "5", "第二步"),
                OperationRow("外协", "6", "送外加工"),
                OperationRow("检验", "7", "检验"),
            ],
            ("待焊", "外协"),
        )

        self.assertEqual(2, len(result.operations))
        self.assertEqual("4～5", result.operations[0].original_range)
        self.assertEqual(["外协"], [operation.work_type for operation in result.excluded])

    def test_generation_fills_blank_operation_header_and_formats_cells(self) -> None:
        card = self.make_card(
            [
                OperationRow("钻", "12", "第一步"),
                OperationRow("", "13", "第二步"),
                OperationRow("检验", "14", "检验"),
            ]
        )

        with TemporaryDirectory() as temporary_directory:
            directory = Path(temporary_directory)
            template = directory / "template.xlsx"
            output = directory / "output.xlsx"

            workbook = Workbook()
            sheet = workbook.active
            sheet.append(
                [
                    "工艺路线编号",
                    "工艺路线名称",
                    "工序/工艺路线列表",
                    "",
                    "工序内容",
                    "类型",
                    "报工数配比",
                    "是否锁定为最后一道工序",
                    "工时/分钟",
                ]
            )
            sheet.append([None] * 9)
            workbook.save(template)

            generate_template([card], template, output, start_row=2)
            generated = load_workbook(output).active

            self.assertEqual("工序号", generated["D1"].value)
            self.assertEqual("12", generated["D2"].value)
            self.assertEqual("第一步\n第二步", generated["E2"].value)
            self.assertEqual("14", generated["D3"].value)
            for row in range(1, 4):
                for column in range(1, 10):
                    cell = generated.cell(row, column)
                    self.assertEqual("center", cell.alignment.horizontal)
                    self.assertEqual("center", cell.alignment.vertical)
                    if row >= 2:
                        self.assertTrue(
                            all(
                                getattr(cell.border, side).style == "thin"
                                for side in ("left", "right", "top", "bottom")
                            )
                        )

    def test_atomic_export_replaces_route_without_duplicate_rows(self) -> None:
        original = self.make_card([OperationRow("车", "1", "旧内容")])
        updated = self.make_card([OperationRow("车", "1", "新内容")])

        with TemporaryDirectory() as temporary_directory:
            directory = Path(temporary_directory)
            template = directory / "template.xlsx"
            output = directory / "output.xlsx"
            workbook = Workbook()
            sheet = workbook.active
            sheet.append(
                [
                    "工艺路线编号",
                    "工艺路线名称",
                    "工序/工艺路线列表",
                    "工序号",
                    "工序内容",
                    "类型",
                    "报工数配比",
                    "是否锁定为最后一道工序",
                    "工时/分钟",
                ]
            )
            sheet.append([None] * 9)
            workbook.save(template)

            generate_template_atomic([original], template, output)
            generate_template_atomic(
                [updated],
                template,
                output,
                replace_route_texts=[original.route_text],
            )

            generated = load_workbook(output).active
            values = [
                generated.cell(row, 5).value
                for row in range(2, generated.max_row + 1)
                if generated.cell(row, 1).value
            ]
            self.assertEqual(["新内容"], values)


if __name__ == "__main__":
    unittest.main()
