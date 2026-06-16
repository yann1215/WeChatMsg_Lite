# member.py
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from wxManager import DatabaseConnection
from wxManager.decrypt_runner import decrypt_wechat_database


def get_member(
    group_name: str,

    db_dir: str | None = None,
    db_version: int = 4,

    auto_decrypt: bool = True,
    source_dir: str | None = None,
    decrypt_output_root: str = ".",

    use_cache_db: bool = True,
    use_cache_key: bool = True,
    force_decrypt: bool = False,
    force_find_key: bool = False,
) -> dict[str, Any]:

    """
    根据微信群聊名称查询群成员名单。

    返回：
    {
        "群聊名称": "...",
        "chatroom_wxid": "...@chatroom",
        "member_count": 123,
        "members": [
            {
                "wxid": "...",
                "备注": "...",
                "群昵称": "...",
                "昵称": "..."
            }
        ]
    }
    """

    group_name = (group_name or "").strip()
    if not group_name:
        return _fail("群聊名称不能为空", group_name)

    # 1. 如果没有传入 db_dir，则自动解密
    if not db_dir:
        if not auto_decrypt:
            return _fail("db_dir 为空，且 auto_decrypt=False，无法查询群成员", group_name)

        decrypt_result = decrypt_wechat_database(
            db_version=db_version,
            source_dir=source_dir,
            output_root=decrypt_output_root,
            use_cache_db=use_cache_db,
            use_cache_key=use_cache_key,
            force_decrypt=force_decrypt,
            force_find_key=force_find_key,
        )

        if not decrypt_result.get("ok"):
            return _fail(f"自动解密失败：{decrypt_result.get('message')}", group_name)

        db_dir = decrypt_result.get("db_dir")

    # 2. 检查数据库目录
    db_path = Path(db_dir)
    if not db_path.exists():
        return _fail(f"数据库目录不存在：{db_path}", group_name)

    if not db_path.is_dir():
        return _fail(f"db_dir 不是文件夹：{db_path}", group_name)

    if not os.access(db_path, os.R_OK):
        return _fail(f"数据库目录不可读：{db_path}", group_name)

    # 3. 初始化数据库
    try:
        conn = DatabaseConnection(str(db_path), db_version)
        database = conn.get_interface()
    except Exception as e:
        return _fail(f"数据库初始化失败：{e}", group_name)

    if database is None:
        return _fail("数据库初始化失败：database is None", group_name)

    # 4. 根据群聊名称查找群聊
    try:
        chatroom_contact = _find_group_by_name(database, group_name)
    except Exception as e:
        if "file is not a database" in str(e):
            return _fail(
                "读取联系人失败：当前 db_dir 不是有效解密数据库目录。"
                "请检查自动解密是否成功，以及 db_version 是否正确。",
                group_name,
            )
        return _fail(f"查找群聊失败：{e}", group_name)

    if chatroom_contact is None:
        return _fail(f"未找到群聊：{group_name}", group_name)

    chatroom_wxid = str(getattr(chatroom_contact, "wxid", "") or "")
    if not chatroom_wxid.endswith("@chatroom"):
        return _fail(f"查找到的对象不是群聊：{chatroom_wxid}", group_name)

    real_group_name = _get_contact_name(chatroom_contact)

    # 5. 获取群成员
    try:
        members_dict = database.get_chatroom_members(chatroom_wxid)
    except Exception as e:
        return _fail(f"获取群成员失败：{e}", real_group_name, chatroom_wxid)

    member_list = []
    for wxid, contact in members_dict.items():
        member_list.append({
            "wxid": str(wxid or ""),
            "备注": str(getattr(contact, "contact_remark", "") or ""),
            "群昵称": str(getattr(contact, "group_nickname", "") or ""),
            "昵称": str(getattr(contact, "nickname", "") or ""),
        })

    # 可选：让输出更稳定，优先按群昵称/备注/昵称/wxid排序
    member_list.sort(
        key=lambda x: (
            x["群昵称"] or x["备注"] or x["昵称"] or x["wxid"]
        ).lower()
    )

    return {
        "ok": True,
        "message": "获取群成员成功",
        "群聊名称": real_group_name,
        "chatroom_wxid": chatroom_wxid,
        "member_count": len(member_list),
        "members": member_list,
    }


def _find_group_by_name(database: Any, group_name: str) -> Any | None:
    """
    根据群聊名称查找群聊。
    支持：
    1. 精确匹配 wxid
    2. 精确匹配 nickname
    3. 精确匹配 alias
    4. 精确匹配 remark
    5. 模糊匹配上述字段
    """

    contacts = database.get_contacts()

    exact_matches = []
    fuzzy_matches = []

    target = group_name.strip().lower()

    for contact in contacts:
        wxid = str(getattr(contact, "wxid", "") or "")
        nickname = str(getattr(contact, "nickname", "") or "")
        alias = str(getattr(contact, "alias", "") or "")
        remark = str(getattr(contact, "remark", "") or "")

        if not wxid.endswith("@chatroom"):
            continue

        exact_fields = {
            wxid.strip().lower(),
            nickname.strip().lower(),
            alias.strip().lower(),
            remark.strip().lower(),
        }

        if target in exact_fields:
            exact_matches.append(contact)
            continue

        search_text = f"{wxid} {nickname} {alias} {remark}".lower()
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
    remark = str(getattr(contact, "remark", "") or "")
    alias = str(getattr(contact, "alias", "") or "")
    wxid = str(getattr(contact, "wxid", "") or "")

    return nickname or remark or alias or wxid


def _fail(
    message: str,
    group_name: str | None = None,
    chatroom_wxid: str | None = None,
) -> dict[str, Any]:
    """
    失败时也返回同样的主结构，方便上层代码处理。
    """

    return {
        "ok": False,
        "message": message,
        "群聊名称": group_name,
        "chatroom_wxid": chatroom_wxid,
        "member_count": 0,
        "members": [],
    }


if __name__ == "__main__":
    from multiprocessing import freeze_support

    freeze_support()

    result = get_member(
        group_name="临时喵喵",

        db_dir=None,
        db_version=4,

        auto_decrypt=True,
        source_dir=None,
        decrypt_output_root=r"D:\2_PycharmTestData\temp",

        use_cache_db=False,
        use_cache_key=True,
        force_decrypt=True,
        force_find_key=False,
    )

    print(result)