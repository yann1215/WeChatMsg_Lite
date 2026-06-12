# wxManager/decrypt_runner.py
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from wxManager import Me
from wxManager.decrypt import get_info_v4, get_info_v3
from wxManager.decrypt.decrypt_dat import get_decode_code_v4
from wxManager.decrypt import decrypt_v4, decrypt_v3


WX_MANAGER_DIR = Path(__file__).resolve().parent


def _get_decrypt_cache_path(output_root: str | os.PathLike | None = None) -> Path:
    """
    缓存文件保存到 decrypt_output_root 中。
    如果 output_root 为空，则兜底保存到 ./wxManager/decrypt_cache.json
    """
    if output_root:
        return Path(output_root).expanduser().resolve() / "decrypt_cache.json"

    return WX_MANAGER_DIR / "decrypt_cache.json"


def _norm_path(path: str | os.PathLike | None) -> str | None:
    if not path:
        return None
    try:
        return str(Path(path).expanduser().resolve())
    except Exception:
        return str(path)


def _load_decrypt_cache(output_root: str | os.PathLike | None = None) -> dict:
    cache_path = _get_decrypt_cache_path(output_root)

    if not cache_path.exists():
        return {}

    try:
        with open(cache_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_decrypt_cache(
    data: dict,
    output_root: str | os.PathLike | None = None,
) -> None:
    cache_path = _get_decrypt_cache_path(output_root)
    cache_path.parent.mkdir(parents=True, exist_ok=True)

    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _update_decrypt_cache(
    output_root: str | os.PathLike | None = None,
    **kwargs,
) -> None:
    cache = _load_decrypt_cache(output_root)

    cache.update({k: v for k, v in kwargs.items() if v is not None})
    cache["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    _save_decrypt_cache(cache, output_root)


def clear_decrypt_cache(output_root: str | os.PathLike | None = None) -> None:
    """
    清除 decrypt_output_root 里的解密缓存。
    """
    cache_path = _get_decrypt_cache_path(output_root)

    if cache_path.exists():
        cache_path.unlink()


def _db_dir_is_ready(db_dir: str | os.PathLike | None, db_version: int = 4) -> bool:
    """
    判断缓存的 db_dir 是否看起来可用。
    不做重度数据库连接，只做轻量路径检查。
    """
    if not db_dir:
        return False

    db_path = Path(db_dir)

    if not db_path.exists() or not db_path.is_dir():
        return False

    if db_version == 4:
        required_any = [
            db_path / "contact" / "contact.db",
            db_path / "session" / "session.db",
            db_path / "message" / "message_0.db",
        ]

        # DataBaseV4.init_database() 会读取 info.json
        if not (db_path / "info.json").exists():
            return False

        return any(p.exists() for p in required_any)

    # v3 兜底：目录里至少要有 db 文件
    return any(db_path.rglob("*.db"))


def _get_cached_db_dir(
    db_version: int = 4,
    source_dir: str | None = None,
    output_root: str | os.PathLike | None = None,
) -> str | None:
    cache = _load_decrypt_cache(output_root)

    cached_db_version = cache.get("db_version")
    cached_source_dir = cache.get("source_dir")
    cached_db_dir = cache.get("db_dir")

    if cached_db_version is not None and int(cached_db_version) != int(db_version):
        return None

    # 如果本次手动传了 source_dir，则要求缓存来源一致，避免拿错微信账号目录
    if source_dir:
        if cached_source_dir and _norm_path(cached_source_dir) != _norm_path(source_dir):
            return None

    if _db_dir_is_ready(cached_db_dir, db_version=db_version):
        return str(Path(cached_db_dir).resolve())

    return None


def decrypt_wechat_database_uncached(
    db_version: int = 4,
    source_dir: str | None = None,
    output_root: str = ".",
) -> dict[str, Any]:
    """
    自动解析/解密微信数据库。

    Parameters
    ----------
    db_version:
        微信数据库版本。微信 4.0 用 4，微信 3.x 用 3。

    source_dir:
        微信原始数据库目录。
        None 表示自动检测当前登录微信的数据库目录。

    output_root:
        解密后数据库的输出根目录。

    Returns
    -------
    dict:
        {
            "ok": bool,
            "message": str,
            "db_dir": str | None,
            "wxid": str | None,
            "source_dir": str | None,
        }
    """

    try:
        output_root_path = Path(output_root).resolve()
        output_root_path.mkdir(parents=True, exist_ok=True)

        if db_version == 4:
            return _dump_v4(
                source_dir=source_dir,
                output_root=output_root_path,
            )

        if db_version == 3:
            return _dump_v3(
                source_dir=source_dir,
                output_root=output_root_path,
            )

        return _fail(f"不支持的 db_version：{db_version}")

    except FileNotFoundError as e:
        return _fail(f"文件不存在：{e}")
    except PermissionError as e:
        return _fail(f"没有权限访问文件：{e}")
    except Exception as e:
        return _fail(f"数据库解析失败：{e}")


def decrypt_wechat_database(
    db_version: int = 4,
    source_dir: str | None = None,
    output_root: str = ".",
    use_cache: bool = True,
    force_refresh: bool = False,
) -> dict:
    """
    带缓存的微信数据库解密入口。

    缓存文件保存位置：
        {output_root}/decrypt_cache.json

    逻辑：
    1. 优先读取 decrypt_output_root/decrypt_cache.json
    2. 如果缓存 db_dir 可用，直接返回，不再检测 key
    3. 如果缓存不可用，再执行原始解密逻辑
    4. 解密成功后，把 db_dir 写入 decrypt_output_root/decrypt_cache.json
    """

    cache_path = _get_decrypt_cache_path(output_root)

    if use_cache and not force_refresh:
        cached_db_dir = _get_cached_db_dir(
            db_version=db_version,
            source_dir=source_dir,
            output_root=output_root,
        )

        if cached_db_dir:
            return {
                "ok": True,
                "message": "使用缓存 db_dir，跳过 key 检测和重复解密",
                "db_dir": cached_db_dir,
                "cache_path": str(cache_path),
                "from_cache": True,
            }

    result = decrypt_wechat_database_uncached(
        db_version=db_version,
        source_dir=source_dir,
        output_root=output_root,
    )

    if result and result.get("ok"):
        db_dir = result.get("db_dir")

        _update_decrypt_cache(
            output_root=output_root,
            db_version=db_version,
            source_dir=_norm_path(source_dir),
            db_dir=_norm_path(db_dir),
            from_cache=False,

            wxid=result.get("wxid"),
            name=result.get("name"),
            account=result.get("account"),
            wx_dir=_norm_path(result.get("wx_dir")),

            # 如果你不想把 key 写入缓存，可以删掉这一行
            key=result.get("key"),
        )

        result["from_cache"] = False
        result["cache_path"] = str(cache_path)

    return result


def _dump_v4(
    source_dir: str | None,
    output_root: Path,
) -> dict[str, Any]:
    """解析微信 4.0 数据库。"""

    wx_info_list = get_info_v4()

    if not wx_info_list:
        return _fail("未检测到微信 4.0 信息。请确认微信已登录，或手动传入 source_dir。")

    wx_info = _select_wx_info(wx_info_list, source_dir)

    if wx_info is None:
        return _fail(f"未找到匹配的微信原始目录：{source_dir}")

    key = wx_info.key
    if not key:
        return _fail("未找到数据库 key，请重启微信后再试。")

    wx_dir = source_dir or wx_info.wx_dir

    me = Me()
    me.wx_dir = wx_dir
    me.wxid = wx_info.wxid
    me.name = wx_info.nick_name
    me.xor_key = get_decode_code_v4(wx_dir)

    output_dir = output_root / wx_info.wxid

    decrypt_v4.decrypt_db_files(
        key,
        src_dir=wx_dir,
        dest_dir=str(output_dir),
    )

    db_dir = output_dir / "db_storage"
    info_path = db_dir / "info.json"

    with open(info_path, "w", encoding="utf-8") as f:
        json.dump(me.to_json(), f, ensure_ascii=False, indent=4)

    return _success(
        message="微信 4.0 数据库解析成功",
        db_dir=db_dir,
        wxid=wx_info.wxid,
        source_dir=wx_dir,
    )


def _dump_v3(
    source_dir: str | None,
    output_root: Path,
) -> dict[str, Any]:
    """解析微信 3.x 数据库。"""

    version_list_path = Path(__file__).parent / "decrypt" / "version_list.json"

    with open(version_list_path, "r", encoding="utf-8") as f:
        version_list = json.loads(f.read())

    wx_info_list = get_info_v3(version_list)

    if not wx_info_list:
        return _fail("未检测到微信 3.x 信息。请确认微信已登录，或手动传入 source_dir。")

    wx_info = _select_wx_info(wx_info_list, source_dir)

    if wx_info is None:
        return _fail(f"未找到匹配的微信原始目录：{source_dir}")

    key = wx_info.key
    if not key:
        return _fail("未找到数据库 key，请重启微信后再试。")

    wx_dir = source_dir or wx_info.wx_dir

    me = Me()
    me.wx_dir = wx_dir
    me.wxid = wx_info.wxid
    me.name = wx_info.nick_name

    output_dir = output_root / wx_info.wxid

    decrypt_v3.decrypt_db_files(
        key,
        src_dir=wx_dir,
        dest_dir=str(output_dir),
    )

    db_dir = output_dir / "Msg"
    info_path = db_dir / "info.json"

    with open(info_path, "w", encoding="utf-8") as f:
        json.dump(me.to_json(), f, ensure_ascii=False, indent=4)

    return _success(
        message="微信 3.x 数据库解析成功",
        db_dir=db_dir,
        wxid=wx_info.wxid,
        source_dir=wx_dir,
    )


def _select_wx_info(
    wx_info_list: list[Any],
    source_dir: str | None,
) -> Any | None:
    """
    如果 source_dir 为空，默认选择第一个检测到的微信账号。
    如果 source_dir 不为空，则匹配 wx_info.wx_dir。
    """

    if not source_dir:
        return wx_info_list[0]

    source_path = Path(source_dir).resolve()

    for wx_info in wx_info_list:
        wx_dir = Path(wx_info.wx_dir).resolve()
        if wx_dir == source_path:
            return wx_info

    return None


def _success(
    message: str,
    db_dir: Path,
    wxid: str | None,
    source_dir: str | None,
) -> dict[str, Any]:
    return {
        "ok": True,
        "message": message,
        "db_dir": str(db_dir.resolve()),
        "wxid": wxid,
        "source_dir": source_dir,
    }

def debug_wechat_info(db_version: int = 4) -> None:
    """
    诊断当前是否能检测到微信账号、微信目录和 key。
    不要打印 key 内容，只打印 key 是否存在。
    """
    if db_version == 4:
        wx_info_list = get_info_v4()
    elif db_version == 3:
        version_list_path = Path(__file__).parent / "decrypt" / "version_list.json"
        with open(version_list_path, "r", encoding="utf-8") as f:
            version_list = json.loads(f.read())
        wx_info_list = get_info_v3(version_list)
    else:
        print(f"不支持的 db_version: {db_version}")
        return

    print(f"检测到微信账号数量: {len(wx_info_list)}")

    for i, wx_info in enumerate(wx_info_list):
        print("=" * 60)
        print(f"index: {i}")
        print(f"wxid: {getattr(wx_info, 'wxid', None)}")
        print(f"nick_name: {getattr(wx_info, 'nick_name', None)}")
        print(f"wx_dir: {getattr(wx_info, 'wx_dir', None)}")
        print(f"has_key: {bool(getattr(wx_info, 'key', None))}")


def _fail(message: str) -> dict[str, Any]:
    return {
        "ok": False,
        "message": message,
        "db_dir": None,
        "wxid": None,
        "source_dir": None,
    }