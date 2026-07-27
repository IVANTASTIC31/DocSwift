from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from domain import CardStatus
from project_store import ProjectStore


class ProjectStoreTest(unittest.TestCase):
    def test_task_and_cards_are_restored_in_natural_order(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            directory = Path(temporary_directory)
            database = directory / "docswift.db"
            cards = [directory / name for name in ("B.10.docx", "B.2.docx")]
            for card in cards:
                card.write_bytes(card.name.encode())

            with ProjectStore(database) as store:
                task = store.get_or_create_active_task()
                store.add_cards(task.id, cards)

            with ProjectStore(database) as reloaded:
                task = reloaded.get_or_create_active_task()
                restored = reloaded.list_cards(task.id)
                self.assertEqual(["B.2.docx", "B.10.docx"], [c.display_name for c in restored])
                self.assertTrue(all(c.status == CardStatus.UNRECOGNIZED for c in restored))

    def test_recognition_edits_and_confirmation_persist(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            directory = Path(temporary_directory)
            card_path = directory / "B.1.docx"
            card_path.write_bytes(b"docx placeholder")

            with ProjectStore(directory / "docswift.db") as store:
                task = store.get_or_create_active_task()
                card = store.add_cards(task.id, [card_path])[0]
                store.replace_recognition(
                    card.id,
                    route_no="B.1",
                    route_name="测试件",
                    operations=[
                        {
                            "operation_no": "4",
                            "original_range": "4～5",
                            "work_type": "车",
                            "content": "第一步\n第二步",
                        },
                        {
                            "operation_no": "6",
                            "original_range": "6",
                            "work_type": "检验",
                            "content": "检验",
                        },
                    ],
                    original_snapshot=[],
                    excluded_snapshot=[],
                )
                operation = store.list_operations(card.id)[0]
                store.update_operation(operation.id, content="人工修改")
                confirmed = store.confirm_card(card.id)

                self.assertEqual(CardStatus.CONFIRMED, confirmed.status)
                self.assertEqual("人工修改", store.list_operations(card.id)[0].content)

    def test_source_change_blocks_confirmation_until_user_accepts(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            directory = Path(temporary_directory)
            card_path = directory / "B.1.docx"
            card_path.write_bytes(b"first")
            with ProjectStore(directory / "docswift.db") as store:
                task = store.get_or_create_active_task()
                card = store.add_cards(task.id, [card_path])[0]
                store.replace_recognition(
                    card.id,
                    route_no="B.1",
                    route_name="测试件",
                    operations=[
                        {
                            "operation_no": "1",
                            "original_range": "1",
                            "work_type": "检验",
                            "content": "检验",
                        }
                    ],
                    original_snapshot=[],
                    excluded_snapshot=[],
                )
                card_path.write_bytes(b"second version")
                changed = store.list_cards(task.id)[0]
                self.assertEqual(CardStatus.SOURCE_CHANGED, changed.status)
                with self.assertRaises(ValueError):
                    store.confirm_card(card.id)

                store.continue_with_changed_source(card.id)
                self.assertEqual(CardStatus.CONFIRMED, store.confirm_card(card.id).status)

    def test_built_in_exclusion_cannot_be_deleted(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            with ProjectStore(Path(temporary_directory) / "docswift.db") as store:
                built_in = next(
                    rule for rule in store.list_exclusion_rules() if rule.term == "待焊"
                )
                with self.assertRaises(ValueError):
                    store.remove_exclusion_rule(built_in.id)
                custom = store.add_exclusion_rule("外协")
                store.remove_exclusion_rule(custom.id)
                self.assertNotIn("外协", store.enabled_exclusion_terms())

    def test_insert_merge_and_split_keep_operation_order(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            directory = Path(temporary_directory)
            card_path = directory / "B.1.docx"
            card_path.write_bytes(b"content")
            with ProjectStore(directory / "docswift.db") as store:
                task = store.get_or_create_active_task()
                card = store.add_cards(task.id, [card_path])[0]
                store.replace_recognition(
                    card.id,
                    route_no="B.1",
                    route_name="测试件",
                    operations=[
                        {
                            "operation_no": "1",
                            "original_range": "1",
                            "work_type": "车",
                            "content": "步骤一",
                        },
                        {
                            "operation_no": "2",
                            "original_range": "2",
                            "work_type": "检验",
                            "content": "步骤二",
                        },
                    ],
                    original_snapshot=[],
                    excluded_snapshot=[],
                )
                inserted = store.add_operation(
                    card.id,
                    position=1,
                    operation_no="1.5",
                    work_type="清洗",
                    content="中间步骤",
                )
                operations = store.list_operations(card.id)
                self.assertEqual(["1", "1.5", "2"], [op.operation_no for op in operations])

                store.merge_operations([operations[0].id, inserted.id])
                merged = store.list_operations(card.id)
                self.assertEqual(["1", "2"], [op.operation_no for op in merged])

                store.split_operation(
                    merged[0].id,
                    first_content="步骤一",
                    second_operation_no="1.5",
                    second_work_type="清洗",
                    second_content="中间步骤",
                )
                split = store.list_operations(card.id)
                self.assertEqual(["1", "1.5", "2"], [op.operation_no for op in split])


if __name__ == "__main__":
    unittest.main()
