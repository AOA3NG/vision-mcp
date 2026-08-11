from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
import urllib.request
import uuid
import webbrowser
from pathlib import Path
import tkinter as tk
from tkinter import messagebox, ttk

from . import __version__
from . import agents as agent_ops
from .cli import server_executable
from .config import PRESETS, load_config, save_config
from .credentials import delete_key, get_key, migrate_legacy, set_key
from .logging_setup import redact_text, setup_logging
from .processes import isolated_subprocess_kwargs

RELEASES_API_URL = os.environ.get("VISION_MCP_RELEASES_API", "")

COLORS = {
    "window": "#f5f6f8",
    "background": "#ffffff",
    "surface": "#ffffff",
    "raised": "#f8f9fb",
    "hover": "#eef4ff",
    "border": "#e1e5ea",
    "border_strong": "#cbd1d9",
    "text": "#17191c",
    "muted": "#68707c",
    "subtle": "#8d95a1",
    "primary": "#2563eb",
    "primary_hover": "#1d4ed8",
    "primary_text": "#ffffff",
    "success": "#198754",
    "success_soft": "#edf9f2",
    "danger": "#c73b3b",
    "danger_soft": "#fff1f1",
    "log": "#f5f7fa",
}

PROVIDER_LABELS = {
    "": "请选择服务商",
    "zhipu": "智谱开放平台 API",
    "bailian": "阿里云百炼 Coding Plan",
}
LABEL_TO_PROVIDER = {label: key for key, label in PROVIDER_LABELS.items()}
KEY_URLS = {
    "zhipu": "https://docs.bigmodel.cn/cn/guide/models/free/glm-4.6v-flash",
    "bailian": "https://help.aliyun.com/zh/model-studio/coding-plan",
}


class PlaceholderEntry(ttk.Entry):
    def __init__(self, master, *, value="", placeholder="", masked=False, **kwargs):
        self.variable = tk.StringVar(value=value)
        self.placeholder = placeholder
        self.masked = masked
        self._showing_placeholder = False
        super().__init__(master, textvariable=self.variable, **kwargs)
        self.bind("<FocusIn>", self._focus_in)
        self.bind("<FocusOut>", self._focus_out)
        self._refresh_display()

    def _refresh_display(self):
        if self.variable.get():
            self._showing_placeholder = False
            self.configure(style="TEntry", show="●" if self.masked else "")
        else:
            self._showing_placeholder = True
            self.variable.set(self.placeholder)
            self.configure(style="Placeholder.TEntry", show="")

    def _focus_in(self, _event=None):
        if self._showing_placeholder:
            self.variable.set("")
            self._showing_placeholder = False
            self.configure(style="TEntry", show="●" if self.masked else "")

    def _focus_out(self, _event=None):
        if not self.variable.get():
            self._refresh_display()

    def get_value(self) -> str:
        return "" if self._showing_placeholder else self.variable.get()

    def set_value(self, value: str):
        self._showing_placeholder = False
        self.variable.set(value)
        self._refresh_display()

    def set_masked(self, masked: bool):
        self.masked = masked
        if not self._showing_placeholder:
            self.configure(show="●" if masked else "")


class Manager(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"Vision MCP 管理器 {__version__}")
        self.geometry("1060x760")
        self.minsize(820, 620)
        self.configure(background=COLORS["window"])
        self.cfg = load_config(create=True)
        migrate_legacy(self.cfg)
        self.provider_rows: list[dict] = []
        self.removed_provider_ids: set[str] = set()
        self.agent_vars: dict[str, tk.BooleanVar] = {}
        self.stage_labels: dict[str, tuple[ttk.Label, ttk.Label]] = {}
        self._ui_queue: queue.Queue[tuple] = queue.Queue()
        self._configure_theme()
        self._build()
        self.after(50, self._drain_ui_queue)

    def _configure_theme(self):
        style = ttk.Style(self)
        style.theme_use("clam")
        font = ("Microsoft YaHei UI", 10)
        self.option_add("*Font", font)
        self.option_add("*TCombobox*Listbox.font", font)
        self.option_add("*TCombobox*Listbox.background", COLORS["background"])
        self.option_add("*TCombobox*Listbox.foreground", COLORS["text"])
        self.option_add("*TCombobox*Listbox.selectBackground", COLORS["primary"])
        self.option_add("*TCombobox*Listbox.selectForeground", COLORS["primary_text"])

        style.configure("TFrame", background=COLORS["background"])
        style.configure("App.TFrame", background=COLORS["window"])
        style.configure("Header.TFrame", background=COLORS["background"])
        style.configure("Card.TFrame", background=COLORS["surface"])
        style.configure("Model.TFrame", background=COLORS["raised"])
        style.configure("Footer.TFrame", background=COLORS["background"])
        style.configure("TLabel", background=COLORS["background"], foreground=COLORS["text"])
        style.configure("Title.TLabel", background=COLORS["background"], foreground=COLORS["text"], font=("Microsoft YaHei UI", 18, "bold"))
        style.configure("Subtitle.TLabel", background=COLORS["background"], foreground=COLORS["muted"], font=("Microsoft YaHei UI", 9))
        style.configure("Section.TLabel", background=COLORS["surface"], foreground=COLORS["text"], font=("Microsoft YaHei UI", 12, "bold"))
        style.configure("Hint.TLabel", background=COLORS["surface"], foreground=COLORS["subtle"], font=("Microsoft YaHei UI", 8))
        style.configure("Model.TLabel", background=COLORS["raised"], foreground=COLORS["muted"])
        style.configure("ModelTitle.TLabel", background=COLORS["raised"], foreground=COLORS["text"], font=("Microsoft YaHei UI", 10, "bold"))
        style.configure("Agent.TLabel", background=COLORS["raised"], foreground=COLORS["text"])
        style.configure("Ready.TLabel", background=COLORS["success_soft"], foreground=COLORS["success"], padding=(12, 7), font=("Microsoft YaHei UI", 9, "bold"))
        style.configure("Success.TLabel", background=COLORS["background"], foreground=COLORS["success"], font=("Microsoft YaHei UI", 9))
        style.configure("Muted.TLabel", background=COLORS["background"], foreground=COLORS["subtle"], font=("Microsoft YaHei UI", 9))
        style.configure("Danger.TLabel", background=COLORS["background"], foreground=COLORS["danger"], font=("Microsoft YaHei UI", 9))
        style.configure("Stage.TLabel", background=COLORS["surface"], foreground=COLORS["muted"], font=("Microsoft YaHei UI", 9))
        style.configure("StageSuccess.TLabel", background=COLORS["surface"], foreground=COLORS["success"], font=("Microsoft YaHei UI", 9, "bold"))
        style.configure("StageDanger.TLabel", background=COLORS["surface"], foreground=COLORS["danger"], font=("Microsoft YaHei UI", 9, "bold"))

        style.configure("TEntry", fieldbackground=COLORS["background"], foreground=COLORS["text"], insertcolor=COLORS["text"], bordercolor=COLORS["border"], lightcolor=COLORS["border"], darkcolor=COLORS["border"], padding=(8, 6))
        style.configure("Placeholder.TEntry", fieldbackground=COLORS["background"], foreground=COLORS["subtle"], insertcolor=COLORS["text"], bordercolor=COLORS["border"], lightcolor=COLORS["border"], darkcolor=COLORS["border"], padding=(8, 6))
        style.map("TEntry", bordercolor=[("focus", COLORS["primary"])], lightcolor=[("focus", COLORS["primary"])], darkcolor=[("focus", COLORS["primary"])])
        style.configure("TCombobox", fieldbackground=COLORS["background"], background=COLORS["raised"], foreground=COLORS["text"], arrowcolor=COLORS["muted"], bordercolor=COLORS["border"], padding=(7, 5))
        style.map("TCombobox", fieldbackground=[("readonly", COLORS["background"])], foreground=[("readonly", COLORS["text"])], bordercolor=[("focus", COLORS["primary"])])
        style.configure("TCheckbutton", background=COLORS["background"], foreground=COLORS["text"], padding=2)
        style.map("TCheckbutton", background=[("active", COLORS["background"])], foreground=[("active", COLORS["text"])], indicatorcolor=[("selected", COLORS["primary"]), ("!selected", COLORS["background"])])

        style.configure("TButton", background=COLORS["raised"], foreground=COLORS["text"], bordercolor=COLORS["border"], padding=(11, 7), font=("Microsoft YaHei UI", 9, "bold"))
        style.map("TButton", background=[("active", COLORS["hover"]), ("disabled", COLORS["surface"])], foreground=[("disabled", COLORS["subtle"])], bordercolor=[("active", COLORS["border_strong"])])
        style.configure("Primary.TButton", background=COLORS["primary"], foreground=COLORS["primary_text"], bordercolor=COLORS["primary"], padding=(16, 8))
        style.map("Primary.TButton", background=[("active", COLORS["primary_hover"]), ("disabled", COLORS["border_strong"])], foreground=[("disabled", COLORS["muted"])])
        style.configure("Danger.TButton", background=COLORS["background"], foreground=COLORS["danger"], bordercolor="#efb8b8", padding=(9, 6))
        style.map("Danger.TButton", background=[("active", COLORS["danger_soft"])], bordercolor=[("active", COLORS["danger"])])
        style.configure("Icon.TButton", background=COLORS["raised"], foreground=COLORS["muted"], bordercolor=COLORS["border"], padding=(5, 5), font=("Segoe UI Symbol", 10, "bold"))
        style.map("Icon.TButton", background=[("active", COLORS["hover"])], foreground=[("active", COLORS["primary"])])

    def _build(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        titlebar = ttk.Frame(self, style="Header.TFrame", padding=(18, 10))
        titlebar.grid(row=0, column=0, sticky="ew")
        mark = tk.Label(titlebar, text="V", width=2, background=COLORS["primary"], foreground="#ffffff", font=("Microsoft YaHei UI", 9, "bold"))
        mark.pack(side="left")
        ttk.Label(titlebar, text="Vision MCP 管理器", style="TLabel").pack(side="left", padx=(8, 0))

        viewport = ttk.Frame(self, style="App.TFrame")
        viewport.grid(row=1, column=0, sticky="nsew")
        viewport.grid_columnconfigure(0, weight=1)
        viewport.grid_rowconfigure(0, weight=1)
        self.content_canvas = tk.Canvas(viewport, background=COLORS["background"], highlightthickness=0, borderwidth=0)
        scrollbar = ttk.Scrollbar(viewport, orient="vertical", command=self.content_canvas.yview)
        self.content_canvas.configure(yscrollcommand=scrollbar.set)
        self.content_canvas.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.content = ttk.Frame(self.content_canvas, style="Header.TFrame", padding=(54, 24, 54, 30))
        self.content_window = self.content_canvas.create_window((0, 0), window=self.content, anchor="nw")
        self.content.bind("<Configure>", self._on_content_configure)
        self.content_canvas.bind("<Configure>", self._on_canvas_configure)
        self.bind_all("<MouseWheel>", self._on_mousewheel)

        header = ttk.Frame(self.content, style="Header.TFrame")
        header.pack(fill="x", pady=(0, 22))
        brand = ttk.Frame(header, style="Header.TFrame")
        brand.pack(side="left")
        ttk.Label(brand, text="配置视觉能力", style="Title.TLabel").pack(anchor="w")
        ttk.Label(brand, text="连接视觉模型，并将 Vision MCP 添加到你的 Agent", style="Subtitle.TLabel").pack(anchor="w", pady=(4, 0))
        self.status_label = ttk.Label(header, text="●  MCP 服务已就绪 · stdio", style="Ready.TLabel")
        self.status_label.pack(side="right")

        models = tk.Frame(self.content, background=COLORS["surface"], highlightbackground=COLORS["border"], highlightcolor=COLORS["border"], highlightthickness=1, padx=16, pady=14)
        models.pack(fill="x", pady=(0, 16))
        ttk.Label(models, text="01  视觉模型", style="Section.TLabel").pack(anchor="w")
        ttk.Label(models, text="按顺序调用，第一项优先；至少保留一个模型配置。", style="Hint.TLabel").pack(anchor="w", pady=(4, 12))
        self.model_frame = ttk.Frame(models, style="Card.TFrame")
        self.model_frame.pack(fill="x")
        for provider in self.cfg["providers"]:
            self._add_provider_row(provider)
        ttk.Button(models, text="＋ 添加模型配置", command=lambda: self._add_provider_row()).pack(anchor="w", pady=(10, 0))

        agent_box = tk.Frame(self.content, background=COLORS["surface"], highlightbackground=COLORS["border"], highlightcolor=COLORS["border"], highlightthickness=1, padx=16, pady=14)
        agent_box.pack(fill="x", pady=(0, 16))
        ttk.Label(agent_box, text="02  选择 Agent", style="Section.TLabel").pack(anchor="w")
        ttk.Label(agent_box, text="选择需要配置视觉能力的 Agent。", style="Hint.TLabel").pack(anchor="w", pady=(4, 12))
        self._build_agent_list(agent_box)

        self.results_frame = tk.Frame(self.content, background=COLORS["surface"], highlightbackground=COLORS["border"], highlightcolor=COLORS["border"], highlightthickness=1, padx=16, pady=14)
        ttk.Label(self.results_frame, text="配置与测试结果", style="Section.TLabel").pack(anchor="w", pady=(0, 8))
        for key, label in (("agent", "Agent 配置"), ("protocol", "MCP 协议"), ("model", "视觉模型")):
            line = ttk.Frame(self.results_frame, style="Card.TFrame", padding=(0, 7))
            line.pack(fill="x")
            ttk.Label(line, text=label, style="Stage.TLabel", width=16).pack(side="left")
            icon = ttk.Label(line, text="○", style="Stage.TLabel", width=3)
            icon.pack(side="left")
            message = ttk.Label(line, text="等待开始", style="Stage.TLabel")
            message.pack(side="left", fill="x", expand=True)
            self.stage_labels[key] = (icon, message)
        self.details_button = ttk.Button(self.results_frame, text="查看详细日志", command=self._toggle_log)
        self.details_button.pack(anchor="w", pady=(8, 0))
        self.log_widget = tk.Text(self.results_frame, height=7, state="disabled", wrap="word", font=("Cascadia Mono", 9), background=COLORS["log"], foreground=COLORS["muted"], insertbackground=COLORS["text"], selectbackground=COLORS["primary"], selectforeground=COLORS["primary_text"], relief="flat", borderwidth=0, padx=12, pady=10)
        self.log("就绪。API Key 保存到 Windows 凭据管理器，不写入配置文件。")

        footer_border = tk.Frame(self, background=COLORS["border"], height=1)
        footer_border.grid(row=2, column=0, sticky="ew")
        actions = ttk.Frame(self, style="Footer.TFrame", padding=(54, 14))
        actions.grid(row=3, column=0, sticky="ew")
        self.run_button = ttk.Button(actions, text="一键配置并测试", style="Primary.TButton", command=self.configure_and_test)
        self.run_button.pack(side="left")
        ttk.Button(actions, text="仅保存", command=self.save_models).pack(side="left", padx=(10, 0))
        more = ttk.Menubutton(actions, text="更多操作")
        menu = tk.Menu(more, tearoff=False, font=("Microsoft YaHei UI", 9))
        menu.add_command(label="恢复最近备份", command=self.restore_backups)
        menu.add_separator()
        menu.add_command(label="从所选 Agent 移除", command=self.remove_agents)
        menu.add_command(label="卸载程序", command=self.uninstall_program)
        more.configure(menu=menu)
        more.pack(side="left", padx=(10, 0))
        self.save_state = ttk.Label(actions, text="所有更改仅保存在当前页面", style="Subtitle.TLabel")
        self.save_state.pack(side="right")

    def _on_content_configure(self, _event=None):
        self.content_canvas.configure(scrollregion=self.content_canvas.bbox("all"))

    def _on_canvas_configure(self, event):
        self.content_canvas.itemconfigure(self.content_window, width=event.width)

    def _on_mousewheel(self, event):
        self.content_canvas.yview_scroll(int(-event.delta / 120), "units")

    def _build_agent_list(self, parent):
        table = ttk.Frame(parent, style="Card.TFrame")
        table.pack(fill="x")
        for column, (text, weight) in enumerate((("", 0), ("Agent", 3), ("安装状态", 2), ("配置状态", 2))):
            table.columnconfigure(column, weight=weight)
            ttk.Label(table, text=text, style="Hint.TLabel").grid(row=0, column=column, sticky="w", padx=(0, 8), pady=(0, 6))
        server = server_executable()
        for row_index, (key, agent) in enumerate(agent_ops.agents().items(), 1):
            installed = agent_ops.detected(agent)
            state = agent_ops.status(key, server)
            var = tk.BooleanVar(value=installed)
            self.agent_vars[key] = var
            check = ttk.Checkbutton(table, variable=var)
            check.grid(row=row_index, column=0, sticky="w", padx=(0, 8), pady=7)
            if not installed:
                check.configure(state="disabled")
            ttk.Label(table, text=agent.name).grid(row=row_index, column=1, sticky="w", padx=(0, 8), pady=7)
            ttk.Label(table, text="已安装" if installed else "未安装", style="Success.TLabel" if installed else "Muted.TLabel").grid(row=row_index, column=2, sticky="w", padx=(0, 8), pady=7)
            status_text = {"configured": "已配置", "conflict": "存在冲突", "invalid_config": "配置损坏"}.get(state, "未配置" if installed else "不可配置")
            status_style = "Success.TLabel" if state == "configured" else "Danger.TLabel" if state in {"conflict", "invalid_config"} else "Muted.TLabel"
            ttk.Label(table, text=status_text, style=status_style).grid(row=row_index, column=3, sticky="w", pady=7)
        other_row = len(agent_ops.agents()) + 1
        ttk.Label(table, text="···", style="Muted.TLabel").grid(row=other_row, column=0, sticky="w", pady=7)
        ttk.Label(table, text="其他 Agent").grid(row=other_row, column=1, sticky="w", padx=(0, 8), pady=7)
        ttk.Label(table, text="手动接入", style="Muted.TLabel").grid(row=other_row, column=2, sticky="w", padx=(0, 8), pady=7)
        ttk.Button(table, text="复制 MCP 配置", command=self.copy_manual_config).grid(row=other_row, column=3, sticky="w", pady=7)

    def _toggle_log(self):
        if self.log_widget.winfo_manager():
            self.log_widget.pack_forget()
            self.details_button.configure(text="查看详细日志")
        else:
            self.log_widget.pack(fill="x", pady=(8, 0))
            self.details_button.configure(text="收起详细日志")

    def _add_provider_row(self, provider=None):
        provider = provider or {"id": str(uuid.uuid4()), "preset_id": "", "enabled": True, "name": "", "model": "", "api_base": "", "api_protocol": "openai", "image_format": "auto"}
        frame = tk.Frame(self.model_frame, background=COLORS["raised"], highlightbackground=COLORS["border"], highlightcolor=COLORS["border"], highlightthickness=1, padx=12, pady=10)
        frame.pack(fill="x", pady=5)
        preset_id = provider.get("preset_id", "")
        preset_label = PROVIDER_LABELS.get(preset_id, "自定义（现有配置）")
        values = {
            "id": provider["id"],
            "enabled": tk.BooleanVar(value=provider.get("enabled", True)),
            "preset_id": preset_id,
            "preset_label": tk.StringVar(value=preset_label),
            "api_protocol": tk.StringVar(value=provider["api_protocol"]),
            "show": tk.BooleanVar(value=False),
            "frame": frame,
        }
        frame.columnconfigure(1, weight=2)
        frame.columnconfigure(2, weight=2)
        frame.columnconfigure(3, weight=3)
        number_label = ttk.Label(frame, text="", style="ModelTitle.TLabel", width=3, anchor="center")
        number_label.grid(row=0, column=0, padx=(0, 8), sticky="s")
        values["number_label"] = number_label

        provider_cell = ttk.Frame(frame, style="Model.TFrame")
        provider_cell.grid(row=0, column=1, padx=(0, 10), sticky="ew")
        ttk.Label(provider_cell, text="服务商", style="Model.TLabel").pack(anchor="w", pady=(0, 5))
        choices = [PROVIDER_LABELS["zhipu"], PROVIDER_LABELS["bailian"]]
        if preset_label not in choices:
            choices.append(preset_label)
        preset = ttk.Combobox(provider_cell, textvariable=values["preset_label"], values=choices, state="readonly")
        preset.pack(fill="x")

        model_cell = ttk.Frame(frame, style="Model.TFrame")
        model_cell.grid(row=0, column=2, padx=(0, 10), sticky="ew")
        ttk.Label(model_cell, text="模型", style="Model.TLabel").pack(anchor="w", pady=(0, 5))
        model_entry = PlaceholderEntry(model_cell, value=provider["model"], placeholder="请输入模型 ID")
        model_entry.pack(fill="x")
        values["model"] = model_entry

        key_cell = ttk.Frame(frame, style="Model.TFrame")
        key_cell.grid(row=0, column=3, padx=(0, 8), sticky="ew")
        key_header = ttk.Frame(key_cell, style="Model.TFrame")
        key_header.pack(fill="x", pady=(0, 5))
        ttk.Label(key_header, text="API Key", style="Model.TLabel").pack(side="left")
        key_link = tk.Label(key_header, text="获取 API Key", background=COLORS["raised"], foreground=COLORS["primary"], font=("Microsoft YaHei UI", 8, "underline"), cursor="hand2")
        key_link.pack(side="right")
        key_link.bind("<Button-1>", lambda _event, row=values: self._open_key_url(row))
        values["key_link"] = key_link
        key_line = ttk.Frame(key_cell, style="Model.TFrame")
        key_line.pack(fill="x")
        key_entry = PlaceholderEntry(key_line, value=get_key(provider["id"]), placeholder="请输入 API Key", masked=True)
        key_entry.pack(side="left", fill="x", expand=True)
        values["key"] = key_entry
        ttk.Checkbutton(key_line, text="显示", variable=values["show"], command=lambda: key_entry.set_masked(not values["show"].get())).pack(side="left", padx=(6, 0))

        controls = ttk.Frame(frame, style="Model.TFrame")
        controls.grid(row=0, column=4, sticky="s")
        up_button = ttk.Button(controls, text="↑", width=2, style="Icon.TButton", command=lambda: self._move_row(values, -1))
        up_button.pack(side="left")
        down_button = ttk.Button(controls, text="↓", width=2, style="Icon.TButton", command=lambda: self._move_row(values, 1))
        down_button.pack(side="left", padx=4)
        delete_button = ttk.Button(controls, text="删除", style="Danger.TButton", command=lambda: self._delete_row(values))
        delete_button.pack(side="left")
        values.update({"up_button": up_button, "down_button": down_button, "delete_button": delete_button})

        advanced_button = ttk.Button(frame, text="高级设置  ›", command=lambda: self._toggle_advanced_row(values))
        advanced_button.grid(row=1, column=1, columnspan=4, sticky="w", pady=(9, 0))
        values["advanced_button"] = advanced_button
        advanced = ttk.Frame(frame, style="Model.TFrame", padding=(0, 10, 0, 0))
        advanced.grid(row=2, column=1, columnspan=4, sticky="ew")
        advanced.columnconfigure(0, weight=3)
        advanced.columnconfigure(1, weight=1)
        advanced.columnconfigure(2, weight=2)
        api_cell = ttk.Frame(advanced, style="Model.TFrame")
        api_cell.grid(row=0, column=0, padx=(0, 10), sticky="ew")
        ttk.Label(api_cell, text="API 地址", style="Model.TLabel").pack(anchor="w", pady=(0, 5))
        api_entry = PlaceholderEntry(api_cell, value=provider["api_base"], placeholder="请输入 API 地址")
        api_entry.pack(fill="x")
        values["api_base"] = api_entry
        protocol_cell = ttk.Frame(advanced, style="Model.TFrame")
        protocol_cell.grid(row=0, column=1, padx=(0, 10), sticky="ew")
        ttk.Label(protocol_cell, text="协议", style="Model.TLabel").pack(anchor="w", pady=(0, 5))
        ttk.Combobox(protocol_cell, textvariable=values["api_protocol"], values=["openai", "anthropic"], state="readonly").pack(fill="x")
        name_cell = ttk.Frame(advanced, style="Model.TFrame")
        name_cell.grid(row=0, column=2, sticky="ew")
        ttk.Label(name_cell, text="显示名称", style="Model.TLabel").pack(anchor="w", pady=(0, 5))
        name_entry = PlaceholderEntry(name_cell, value=provider["name"], placeholder="请输入显示名称")
        name_entry.pack(fill="x")
        values["name"] = name_entry
        values["advanced"] = advanced
        advanced.grid_remove()
        preset.bind("<<ComboboxSelected>>", lambda _e: self._apply_preset(values))
        self.provider_rows.append(values)
        self._update_key_link(values)
        self._refresh_provider_numbers()

    def _refresh_provider_numbers(self):
        for index, item in enumerate(self.provider_rows, 1):
            item["number_label"].configure(text=f"#{index}")
            if item.get("up_button"):
                item["up_button"].configure(state="disabled" if index == 1 else "normal")
            if item.get("down_button"):
                item["down_button"].configure(state="disabled" if index == len(self.provider_rows) else "normal")
            if item.get("delete_button"):
                item["delete_button"].configure(state="disabled" if len(self.provider_rows) == 1 else "normal")

    def _apply_preset(self, row):
        preset_id = LABEL_TO_PROVIDER.get(row["preset_label"].get(), "")
        row["preset_id"] = preset_id
        preset = PRESETS.get(preset_id)
        if preset:
            row["name"].set_value(preset["name"])
            row["model"].set_value(preset["model"] if preset_id == "zhipu" else "")
            row["api_base"].set_value(preset["api_base"])
            row["api_protocol"].set(preset["api_protocol"])
        else:
            row["name"].set_value("")
            row["model"].set_value("")
            row["api_base"].set_value("")
        self._update_key_link(row)

    def _update_key_link(self, row):
        if row.get("preset_id") in KEY_URLS:
            row["key_link"].pack(side="right")
        else:
            row["key_link"].pack_forget()

    def _open_key_url(self, row):
        url = KEY_URLS.get(row.get("preset_id"))
        if url:
            webbrowser.open(url)

    def _toggle_advanced_row(self, row):
        if row["advanced"].winfo_ismapped():
            row["advanced"].grid_remove()
            row["advanced_button"].configure(text="高级设置  ›")
        else:
            row["advanced"].grid()
            row["advanced_button"].configure(text="高级设置  ⌄")

    def _delete_row(self, row):
        if len(self.provider_rows) == 1:
            messagebox.showwarning("无法删除", "至少保留一个模型。")
            return
        row["frame"].destroy()
        self.provider_rows.remove(row)
        self.removed_provider_ids.add(row["id"])
        self._refresh_provider_numbers()

    def _move_row(self, row, delta):
        index = self.provider_rows.index(row)
        target = index + delta
        if not 0 <= target < len(self.provider_rows):
            return
        self.provider_rows[index], self.provider_rows[target] = self.provider_rows[target], self.provider_rows[index]
        for item in self.provider_rows:
            item["frame"].pack_forget()
            item["frame"].pack(fill="x", pady=5)
        self._refresh_provider_numbers()

    def _collect(self):
        providers = []
        for row in self.provider_rows:
            providers.append({
                "id": row["id"], "preset_id": row["preset_id"], "enabled": row["enabled"].get(),
                "name": row["name"].get_value().strip(), "model": row["model"].get_value().strip(),
                "api_base": row["api_base"].get_value().strip(), "api_protocol": row["api_protocol"].get(), "image_format": "auto",
            })
        return {"version": 1, "defaults_revision": self.cfg.get("defaults_revision", 2), "timeout": self.cfg.get("timeout", 180), "providers": providers}

    def save_models(self, require_key=False):
        cfg = self._collect()
        missing = [index for index, row in enumerate(self.provider_rows, 1) if not row["key"].get_value().strip()]
        if require_key and missing:
            message = f"第 {'、'.join(str(index) for index in missing)} 个模型未填写 API Key"
            messagebox.showwarning("API Key 未填写", message)
            self._show_toast(message, error=True)
            return False
        try:
            save_config(cfg)
            for row in self.provider_rows:
                set_key(row["id"], row["key"].get_value())
            for provider_id in self.removed_provider_ids:
                delete_key(provider_id)
            self.removed_provider_ids.clear()
        except Exception as exc:
            messagebox.showerror("保存失败", str(exc))
            self.log(f"模型配置：失败 - {exc}")
            return False
        self.cfg = cfg
        self.log("模型配置：已保存")
        if hasattr(self, "save_state"):
            self.save_state.configure(text="模型配置已保存")
        if missing:
            self._show_toast(f"模型配置已保存；第 {'、'.join(str(index) for index in missing)} 个模型未填写 API Key", error=True)
        else:
            self._show_toast("模型配置已保存；API Key 已安全保存到 Windows 凭据管理器")
        return True

    def log(self, text):
        self.log_widget.configure(state="normal")
        self.log_widget.insert("end", text + "\n")
        self.log_widget.see("end")
        self.log_widget.configure(state="disabled")

    def _set_status(self, text):
        self.status_label.configure(text=f"●  {text}")

    def _show_toast(self, message, error=False):
        current = getattr(self, "_toast_window", None)
        if current and current.winfo_exists():
            current.destroy()
        toast = tk.Toplevel(self)
        self._toast_window = toast
        toast.overrideredirect(True)
        toast.attributes("-topmost", True)
        background = COLORS["danger_soft"] if error else COLORS["success_soft"]
        foreground = COLORS["danger"] if error else COLORS["success"]
        label = tk.Label(toast, text=message, background=background, foreground=foreground, font=("Microsoft YaHei UI", 9, "bold"), padx=16, pady=10, relief="solid", borderwidth=1)
        label.pack()
        toast.update_idletasks()
        x = self.winfo_rootx() + max(0, (self.winfo_width() - toast.winfo_width()) // 2)
        y = self.winfo_rooty() + 72
        toast.geometry(f"+{x}+{y}")
        toast.after(2400, toast.destroy)

    def _show_results(self):
        if not self.results_frame.winfo_manager():
            self.results_frame.pack(fill="x", pady=(0, 16))
        self.update_idletasks()
        self.content_canvas.configure(scrollregion=self.content_canvas.bbox("all"))

    def _set_stage(self, name, state, message):
        icon, text = self.stage_labels[name]
        if state == "success":
            icon.configure(text="✓", style="StageSuccess.TLabel")
            text.configure(text=message, style="StageSuccess.TLabel")
        elif state == "failed":
            icon.configure(text="×", style="StageDanger.TLabel")
            text.configure(text=message, style="StageDanger.TLabel")
        elif state == "running":
            icon.configure(text="…", style="Stage.TLabel")
            text.configure(text=message, style="Stage.TLabel")
        else:
            icon.configure(text="○", style="Stage.TLabel")
            text.configure(text="等待开始", style="Stage.TLabel")

    def _reset_stages(self):
        for name in self.stage_labels:
            self._set_stage(name, "waiting", "等待开始")

    def _queue_ui(self, callback, *args, **kwargs):
        self._ui_queue.put((callback, args, kwargs))

    def _drain_ui_queue(self):
        while True:
            try:
                callback, args, kwargs = self._ui_queue.get_nowait()
            except queue.Empty:
                break
            callback(*args, **kwargs)
        self.after(50, self._drain_ui_queue)

    def _server_cmd(self, *args):
        server = server_executable()
        if server.endswith(".py"):
            return [sys.executable, server, *args]
        return [server, *args]

    def configure_and_test(self):
        if not self.save_models(require_key=True):
            return
        selected = [key for key, value in self.agent_vars.items() if value.get()]
        if not selected:
            messagebox.showwarning("请选择 Agent", "至少选择一个 Agent。")
            return
        self._show_results()
        self._reset_stages()
        self._set_stage("agent", "running", "正在配置所选 Agent")
        self.run_button.configure(state="disabled")
        self._set_status("正在配置与测试…")
        self.save_state.configure(text="正在执行三阶段检查")
        self.log("──────── 开始一键配置与测试 ────────")
        threading.Thread(target=self._configure_worker, args=(selected,), daemon=True).start()

    def _configure_worker(self, selected):
        try:
            server = server_executable()
            agent_failed = False
            for key in selected:
                try:
                    backup = agent_ops.configure_preferred(key, server)
                    self._queue_ui(self.log, f"{agent_ops.agents()[key].name}：配置成功" + (f"，备份 {backup}" if backup else ""))
                except Exception as exc:
                    agent_failed = True
                    self._queue_ui(self.log, f"{agent_ops.agents()[key].name}：失败 - {redact_text(exc, 500)}")
            self._queue_ui(self._set_stage, "agent", "failed" if agent_failed else "success", "部分 Agent 配置失败" if agent_failed else "所选 Agent 配置完成")
            for stage_name, label, args in (("protocol", "MCP 协议", ("protocol-test",)), ("model", "视觉模型", ("self-test",))):
                self._queue_ui(self._set_stage, stage_name, "running", f"正在检查{label}")
                try:
                    run = subprocess.run(
                        self._server_cmd(*args), capture_output=True, text=True,
                        encoding="utf-8", timeout=210,
                        **isolated_subprocess_kwargs(),
                    )
                    output = redact_text((run.stdout or run.stderr).strip())
                    self._queue_ui(self.log, f"{label}自检：{'通过' if run.returncode == 0 else '失败'} {output}")
                    self._queue_ui(self._set_stage, stage_name, "success" if run.returncode == 0 else "failed", "检查通过" if run.returncode == 0 else "检查失败，请查看详细日志")
                except Exception as exc:
                    self._queue_ui(self.log, f"{label}自检：失败 {redact_text(exc, 500)}")
                    self._queue_ui(self._set_stage, stage_name, "failed", "检查失败，请查看详细日志")
        finally:
            self._queue_ui(self.run_button.configure, state="normal")
            self._queue_ui(self._set_status, "MCP 服务已就绪 · stdio")
            self._queue_ui(self.save_state.configure, text="配置与测试已完成")

    def remove_agents(self):
        selected = [key for key, value in self.agent_vars.items() if value.get()]
        if not selected:
            messagebox.showwarning("请选择 Agent", "至少选择一个 Agent。")
            return
        names = "、".join(agent_ops.agents()[key].name for key in selected)
        if not messagebox.askyesno("移除配置", f"确认从以下 Agent 移除 Vision MCP 配置？\n\n{names}\n\n不会卸载 Agent，也不会删除模型凭据。"):
            return
        for key, value in self.agent_vars.items():
            if value.get():
                try:
                    changed = agent_ops.remove(key, server_executable())
                    self.log(f"{agent_ops.agents()[key].name}：{'已移除' if changed else '未修改（不是本程序配置）'}")
                except Exception as exc:
                    self.log(f"{agent_ops.agents()[key].name}：移除失败 - {exc}")
        self._show_toast("已处理所选 Agent 的移除操作")

    def restore_backups(self):
        for key, value in self.agent_vars.items():
            if value.get():
                try:
                    backup = agent_ops.restore_latest(key)
                    self.log(f"{agent_ops.agents()[key].name}：已从 {backup} 恢复")
                except Exception as exc:
                    self.log(f"{agent_ops.agents()[key].name}：恢复失败 - {exc}")
        self._show_toast("已处理所选 Agent 的备份恢复")

    def copy_manual_config(self):
        server = str(Path(server_executable()).resolve())
        text = json.dumps({"mcpServers": {"vision": {"command": server, "args": ["stdio"]}}}, ensure_ascii=False, indent=2)
        self.clipboard_clear()
        self.clipboard_append(text)
        self.log("手动配置已复制到剪贴板。")
        self._show_toast("MCP 配置已复制到剪贴板")

    def uninstall_program(self):
        install_dir = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(server_executable()).resolve().parent
        candidates = sorted(install_dir.glob("unins*.exe"))
        if not candidates:
            messagebox.showinfo("卸载程序", "开发环境中没有卸载程序。安装后可从这里打开卸载向导。")
            return
        if not messagebox.askyesno("卸载 Vision MCP", "确认打开 Vision MCP 卸载向导？\n\n卸载向导中可选择是否删除个人配置和凭据。"):
            return
        subprocess.Popen([str(candidates[0])], **isolated_subprocess_kwargs())
        self.after(200, self.destroy)

    def check_update(self):
        def worker():
            try:
                with urllib.request.urlopen(RELEASES_API_URL, timeout=8) as response:
                    raw = response.read(1024 * 1024 + 1)
                    if len(raw) > 1024 * 1024:
                        raise ValueError("更新信息响应过大")
                    release = json.loads(raw.decode("utf-8"))
                latest = str(release.get("tag_name", "")).lstrip("v")
                page = release.get("html_url")
                self._queue_ui(self._show_update_result, latest, page, None)
            except Exception as exc:
                self._queue_ui(self._show_update_result, "", None, redact_text(exc, 500))
        threading.Thread(target=worker, daemon=True).start()

    def _show_update_result(self, latest, page, error):
        if error:
            messagebox.showerror("检查更新失败", error)
        elif latest and latest != __version__ and page:
            if messagebox.askyesno("发现新版本", f"当前 {__version__}，最新 {latest}。打开下载页？"):
                webbrowser.open(page)
        else:
            messagebox.showinfo("检查更新", "当前已是最新版本。")


def main():
    setup_logging("manager")
    try:
        Manager().mainloop()
    except Exception as exc:
        messagebox.showerror("Vision MCP 启动失败", str(exc))
        raise


if __name__ == "__main__":
    main()
