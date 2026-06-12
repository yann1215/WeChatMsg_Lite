# msg.py
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from wxManager import DatabaseConnection
from wxManager.decrypt_runner import decrypt_wechat_database
from exporter.exporter_csv import CSVExporter
from exporter.config import FileType


def run_msg(
    group_name: str,
    start_time: str,
    end_time: str,
    options: dict[str, Any] | None = None,
    output_format: str = "csv",
    db_dir: str | None = None,
    output_dir: str = "./output",
    db_version: int = 4,
    auto_decrypt: bool = True,
    source_dir: str | None = None,
    decrypt_output_root: str = ".",
) -> dict[str, Any]:
    """
    自动解析/解密微信数据库，并导出指定群聊的聊天记录。

    第一版功能：
    1. 支持 db_dir=None 时自动调用 decrypt_wechat_database()
    2. 支持按群聊名称查找群聊
    3. 支持按时间范围导出 CSV
    4. 文件或目录不可访问时直接返回失败
    """

    options = options or {}

    if output_format.lower() != "csv":
        return _fail(f"第一版暂时只支持 csv，当前输入为：{output_format}")

    # 1. 如果 db_dir 为空，自动解密
    if not db_dir:
        if not auto_decrypt:
            return _fail("db_dir 为空，且 auto_decrypt=False，无法继续运行")

        decrypt_result = decrypt_wechat_database(
            db_version=db_version,
            source_dir=source_dir,
            output_root=decrypt_output_root,
        )

        print("[DEBUG] decrypt_result =", decrypt_result)

        if not decrypt_result.get("ok"):
            return _fail(f"自动解密失败：{decrypt_result.get('message')}")

        db_dir = decrypt_result.get("db_dir")
        print("[DEBUG] db_dir used by DatabaseConnection =", db_dir)

    # 2. 检查解密后的 db_dir
    db_path = Path(db_dir)

    if not db_path.exists():
        return _fail(f"数据库目录不存在：{db_path}")

    if not db_path.is_dir():
        return _fail(f"db_dir 不是文件夹：{db_path}")

    if not os.access(db_path, os.R_OK):
        return _fail(f"数据库目录不可读：{db_path}")

    # 3. 检查输出目录
    out_path = Path(output_dir)

    try:
        out_path.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        return _fail(f"无法创建输出目录：{out_path}；原因：{e}")

    if not os.access(out_path, os.W_OK):
        return _fail(f"输出目录不可写：{out_path}")

    # 4. 初始化数据库
    try:
        conn = DatabaseConnection(str(db_path), db_version)
        database = conn.get_interface()
    except Exception as e:
        return _fail(f"数据库初始化失败：{e}")

    # 5. 查找群聊
    try:
        contact = _find_group_by_name(database, group_name)
    except Exception as e:
        if "file is not a database" in str(e):
            return _fail(
                "读取联系人失败：当前 db_dir 不是有效解密数据库目录。"
                "请检查自动解密是否成功，以及 db_version 是否正确。"
            )
        return _fail(f"查找群聊失败：{e}")

    if contact is None:
        return _fail(f"未找到群聊：{group_name}")

    # 6. 导出 CSV
    try:
        exporter = CSVExporter(
            database,
            contact,
            output_dir=str(out_path),
            type_=FileType.CSV,
            message_types=None,
            time_range=[start_time, end_time],
            group_members=None,
        )

        exporter.start()

    except FileNotFoundError as e:
        return _fail(f"文件不可访问，导出终止：{e}")
    except PermissionError as e:
        return _fail(f"没有文件访问权限，导出终止：{e}")
    except Exception as e:
        return _fail(f"导出失败：{e}")

    return {
        "ok": True,
        "message": "导出成功",
        "group_name": _get_contact_name(contact),
        "csv_path": getattr(exporter, "csv_path", None),
    }


def _find_group_by_name(database: Any, group_name: str) -> Any | None:
    contacts = database.get_contacts()

    exact_matches = []
    fuzzy_matches = []

    target = group_name.strip().lower()

    for contact in contacts:
        wxid = str(getattr(contact, "wxid", "") or "")
        nickname = str(getattr(contact, "nickname", "") or "")
        alias = str(getattr(contact, "alias", "") or "")

        if not wxid.endswith("@chatroom"):
            continue

        # 精确匹配：推荐用 wxid，最稳定
        if target in {
            wxid.strip().lower(),
            nickname.strip().lower(),
            alias.strip().lower(),
        }:
            exact_matches.append(contact)
            continue

        # 模糊匹配：用于 nickname 搜索
        search_text = f"{wxid} {nickname} {alias}".lower()
        if target and target in search_text:
            fuzzy_matches.append(contact)

    if len(exact_matches) == 1:
        return exact_matches[0]

    if len(exact_matches) > 1:
        names = [_get_contact_name(c) for c in exact_matches]
        raise ValueError(f"找到多个完全匹配群聊：{names}")

    if len(fuzzy_matches) == 1:
        return fuzzy_matches[0]

    if len(fuzzy_matches) > 1:
        names = [_get_contact_name(c) for c in fuzzy_matches]
        raise ValueError(f"找到多个模糊匹配群聊，请输入更完整的群名或 wxid：{names}")

    return None


def _get_contact_name(contact: Any) -> str:
    nickname = str(getattr(contact, "nickname", "") or "")
    alias = str(getattr(contact, "alias", "") or "")
    wxid = str(getattr(contact, "wxid", "") or "")

    return nickname or alias or wxid


def _fail(message: str) -> dict[str, Any]:
    def _fail(message: str) -> dict[str, Any]:
        return {
            "ok": False,
            "message": message,
            "group_name": None,
            "csv_path": None,
        }


if __name__ == "__main__":
    from multiprocessing import freeze_support

    freeze_support()

    result = run_msg(
        group_name="淼群",
        start_time="2026-01-01 00:00:00",
        end_time="2026-06-2 00:00:00",
        options={},
        output_format="csv",

        db_dir=None,  # 不手动传解密后目录
        auto_decrypt=True,

        source_dir=None,  # 不手动传微信原始目录，自动检测
        decrypt_output_root=r"D:\2_PycharmTestData\temp",

        output_dir=r"D:\2_PycharmTestData\output",
        db_version=4,

    )

    print(result)

    # from wxManager.decrypt_runner import debug_wechat_info
    # debug_wechat_info(db_version=4)
