from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from core import generate_template, output_row_count, parse_many_cards, preview_rows


APP_TITLE = "工艺卡转工艺路线模板"


class ProcessTemplateApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("1080x680")
        self.minsize(920, 560)

        self.card_paths: list[Path] = []
        self.parsed_cards = []
        self.message_queue: queue.Queue[tuple[str, object]] = queue.Queue()

        self.template_var = tk.StringVar()
        self.output_var = tk.StringVar()
        self.start_row_var = tk.StringVar(value="2")
        self.append_var = tk.BooleanVar(value=False)
        self.status_var = tk.StringVar(value="请选择工艺卡和 Excel 模板。")

        self._build_ui()
        self.after(120, self._drain_queue)

    def _build_ui(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        top = ttk.Frame(self, padding=(14, 12, 14, 8))
        top.grid(row=0, column=0, sticky="ew")
        top.columnconfigure(1, weight=1)

        ttk.Label(top, text="工艺卡 Word").grid(row=0, column=0, sticky="w", padx=(0, 8), pady=4)
        self.card_entry = ttk.Entry(top)
        self.card_entry.grid(row=0, column=1, sticky="ew", pady=4)
        ttk.Button(top, text="选择工艺卡", command=self._choose_cards).grid(row=0, column=2, padx=(8, 0), pady=4)

        ttk.Label(top, text="Excel 模板").grid(row=1, column=0, sticky="w", padx=(0, 8), pady=4)
        ttk.Entry(top, textvariable=self.template_var).grid(row=1, column=1, sticky="ew", pady=4)
        ttk.Button(top, text="选择模板", command=self._choose_template).grid(row=1, column=2, padx=(8, 0), pady=4)

        ttk.Label(top, text="输出文件").grid(row=2, column=0, sticky="w", padx=(0, 8), pady=4)
        ttk.Entry(top, textvariable=self.output_var).grid(row=2, column=1, sticky="ew", pady=4)
        ttk.Button(top, text="另存为", command=self._choose_output).grid(row=2, column=2, padx=(8, 0), pady=4)

        options = ttk.Frame(top)
        options.grid(row=3, column=1, sticky="w", pady=(8, 0))
        ttk.Label(options, text="起始行").grid(row=0, column=0, sticky="w")
        spin = ttk.Spinbox(options, from_=2, to=9999, width=8, textvariable=self.start_row_var)
        spin.grid(row=0, column=1, padx=(8, 18))
        ttk.Button(options, text="解析预览", command=self._parse_async).grid(row=0, column=2, padx=(0, 8))
        ttk.Button(options, text="生成 Excel", command=self._generate_async).grid(row=0, column=3, padx=(0, 14))
        ttk.Checkbutton(options, text="追加到已有输出文件", variable=self.append_var).grid(row=0, column=4)

        main = ttk.PanedWindow(self, orient=tk.VERTICAL)
        main.grid(row=1, column=0, sticky="nsew", padx=14, pady=(0, 10))

        preview_frame = ttk.Labelframe(main, text="预览")
        preview_frame.columnconfigure(0, weight=1)
        preview_frame.rowconfigure(0, weight=1)
        self.tree = ttk.Treeview(
            preview_frame,
            columns=("file", "route", "no", "work", "content"),
            show="headings",
            height=14,
        )
        self.tree.heading("file", text="来源")
        self.tree.heading("route", text="工艺路线编号/名称")
        self.tree.heading("no", text="工序号")
        self.tree.heading("work", text="工序/工艺路线列表")
        self.tree.heading("content", text="工序内容")
        self.tree.column("file", width=180, minwidth=120)
        self.tree.column("route", width=180, minwidth=120)
        self.tree.column("no", width=70, minwidth=60, anchor="center")
        self.tree.column("work", width=150, minwidth=80)
        self.tree.column("content", width=540, minwidth=260)
        yscroll = ttk.Scrollbar(preview_frame, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=yscroll.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        yscroll.grid(row=0, column=1, sticky="ns")
        main.add(preview_frame, weight=4)

        log_frame = ttk.Labelframe(main, text="日志")
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)
        self.log = tk.Text(log_frame, height=7, wrap="word")
        self.log.configure(state="disabled")
        log_scroll = ttk.Scrollbar(log_frame, orient=tk.VERTICAL, command=self.log.yview)
        self.log.configure(yscrollcommand=log_scroll.set)
        self.log.grid(row=0, column=0, sticky="nsew")
        log_scroll.grid(row=0, column=1, sticky="ns")
        main.add(log_frame, weight=1)

        status = ttk.Frame(self, padding=(14, 0, 14, 12))
        status.grid(row=2, column=0, sticky="ew")
        ttk.Label(status, textvariable=self.status_var).grid(row=0, column=0, sticky="w")

    def _choose_cards(self) -> None:
        paths = filedialog.askopenfilenames(
            title="选择一个或多个工艺卡 Word 文件",
            filetypes=[("Word 文档", "*.docx"), ("所有文件", "*.*")],
        )
        if not paths:
            return
        self.card_paths = [Path(path) for path in paths]
        self.card_entry.delete(0, tk.END)
        self.card_entry.insert(0, "; ".join(str(path) for path in self.card_paths))
        if not self.output_var.get() and self.card_paths:
            stem = self.card_paths[0].stem
            self.output_var.set(str(self.card_paths[0].with_name(f"{stem}_工艺路线导入.xlsx")))

    def _choose_template(self) -> None:
        path = filedialog.askopenfilename(
            title="选择 Excel 流程模板",
            filetypes=[("Excel 工作簿", "*.xlsx"), ("所有文件", "*.*")],
        )
        if path:
            self.template_var.set(path)

    def _choose_output(self) -> None:
        initial = self.output_var.get() or str(Path.home() / "Desktop" / "工艺路线导入.xlsx")
        path = filedialog.asksaveasfilename(
            title="保存生成的 Excel",
            initialfile=Path(initial).name,
            initialdir=str(Path(initial).parent),
            defaultextension=".xlsx",
            filetypes=[("Excel 工作簿", "*.xlsx")],
        )
        if path:
            self.output_var.set(path)

    def _validate_inputs(self, need_output: bool) -> tuple[list[Path], Path, Path | None, int, bool]:
        if not self.card_paths:
            raise ValueError("请先选择工艺卡 Word 文件。")
        template = Path(self.template_var.get().strip())
        if not template.exists():
            raise ValueError("请选择有效的 Excel 模板。")
        output = Path(self.output_var.get().strip()) if self.output_var.get().strip() else None
        if need_output and output is None:
            raise ValueError("请选择输出文件。")
        try:
            start_row = int(self.start_row_var.get())
        except ValueError as exc:
            raise ValueError("起始行必须是数字。") from exc
        return self.card_paths, template, output, start_row, self.append_var.get()

    def _parse_async(self) -> None:
        try:
            paths, _template, _output, _start_row, _append = self._validate_inputs(need_output=False)
        except ValueError as exc:
            messagebox.showwarning(APP_TITLE, str(exc))
            return
        self._run_worker("正在解析工艺卡...", self._parse_worker, paths)

    def _generate_async(self) -> None:
        try:
            paths, template, output, start_row, append = self._validate_inputs(need_output=True)
        except ValueError as exc:
            messagebox.showwarning(APP_TITLE, str(exc))
            return
        self._run_worker("正在生成 Excel...", self._generate_worker, paths, template, output, start_row, append)

    def _run_worker(self, status: str, target, *args) -> None:
        self.status_var.set(status)
        thread = threading.Thread(target=target, args=args, daemon=True)
        thread.start()

    def _parse_worker(self, paths: list[Path]) -> None:
        try:
            cards = parse_many_cards(paths)
            self.message_queue.put(("parsed", cards))
        except Exception as exc:
            self.message_queue.put(("error", exc))

    def _generate_worker(self, paths: list[Path], template: Path, output: Path, start_row: int, append: bool) -> None:
        try:
            cards = parse_many_cards(paths)
            generated = generate_template(cards, template, output, start_row=start_row, append=append)
            self.message_queue.put(("generated", (cards, generated)))
        except Exception as exc:
            self.message_queue.put(("error", exc))

    def _drain_queue(self) -> None:
        try:
            while True:
                kind, payload = self.message_queue.get_nowait()
                if kind == "parsed":
                    self.parsed_cards = payload
                    self._fill_preview(payload)
                    source_count = sum(len(card.operations) for card in payload)
                    count = output_row_count(payload)
                    self._write_log(
                        f"解析完成：{len(payload)} 个工艺卡，{source_count} 道工序，合并后 {count} 行。"
                    )
                    self.status_var.set("解析完成。")
                elif kind == "generated":
                    cards, generated = payload
                    self.parsed_cards = cards
                    self._fill_preview(cards)
                    count = output_row_count(cards)
                    self._write_log(f"生成完成：{generated}，共写入 {count} 行。")
                    self.status_var.set(f"生成完成：{generated}")
                    messagebox.showinfo(APP_TITLE, f"生成完成：\n{generated}")
                elif kind == "error":
                    self._write_log(f"错误：{payload}")
                    self.status_var.set("处理失败。")
                    messagebox.showerror(APP_TITLE, str(payload))
        except queue.Empty:
            pass
        self.after(120, self._drain_queue)

    def _fill_preview(self, cards) -> None:
        for item in self.tree.get_children():
            self.tree.delete(item)
        for row in preview_rows(cards):
            self.tree.insert("", tk.END, values=row)

    def _write_log(self, message: str) -> None:
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log.configure(state="normal")
        self.log.insert(tk.END, f"[{timestamp}] {message}\n")
        self.log.see(tk.END)
        self.log.configure(state="disabled")


def run_cli(args: argparse.Namespace) -> None:
    cards = parse_many_cards(args.card)
    output = generate_template(
        cards,
        args.template,
        args.output,
        start_row=args.start_row,
        append=args.append and not args.replace,
    )
    count = output_row_count(cards)
    print(f"生成完成：{output}")
    print(f"写入工艺卡：{len(cards)} 个，工序：{count} 行")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=APP_TITLE)
    parser.add_argument("--card", nargs="+", help="工艺卡 Word 文件，可传入多个")
    parser.add_argument("--template", help="Excel 模板文件")
    parser.add_argument("--output", help="输出 Excel 文件")
    parser.add_argument("--start-row", type=int, default=2, help="写入起始行，默认 2")
    parser.add_argument("--append", action="store_true", help="追加到已有输出文件；默认重新生成")
    parser.add_argument("--replace", action="store_true", help=argparse.SUPPRESS)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.card or args.template or args.output:
        if not (args.card and args.template and args.output):
            raise SystemExit("命令行模式需要同时提供 --card、--template 和 --output。")
        run_cli(args)
        return

    app = ProcessTemplateApp()
    app.mainloop()


if __name__ == "__main__":
    main()
