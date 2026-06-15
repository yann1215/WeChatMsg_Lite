from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from wxManager import Me
from wxManager.decrypt import get_info_v4
from wxManager.decrypt.decrypt_dat import get_decode_code_v4
from wxManager.decrypt import decrypt_v4


def decrypt_wechat_database(
    db_version: int = 4,
    source_dir: str | None = None,
    output_root: str = ".",
    use_cache_db: bool = True,
    use_cache_key: bool = True,
    force_decrypt: bool = False,
    force_find_key: bool = False,
) -> dict[str, Any]:
    """
    自动解析/解密微信数据库，支持两层缓存。

    两层缓存：
    1. 缓存 db_dir：
       用于快速重复导出旧数据，不重新解密。

    2. 缓存 key：
       用于重新解密最新数据库，但跳过重新检测 key。

    Parameters
    ----------
    db_version:
        微信数据库版本。微信 4.0 用 4，微信 3.x 用 3。

    source_dir:
        微信原始数据库目录。
        None 表示自动检测，或优先使用缓存中的 source_dir。

    output_root:
        解密后数据库输出根目录。
        缓存文件 decrypt_cache.json 也保存在这个目录下。

    use_cache_db:
        True 时，如果缓存 db_dir 可用，直接返回旧解密目录。

    use_cache_key:
        True 时，如果需要重新解密，优先使用缓存 key。

    force_decrypt:
        True 时，即使缓存 db_dir 可用，也重新解密数据库。

    force_find_key:
        True 时，强制重新从微信检测 key，不使用缓存 key。
    """

    try:
        output_root_path = Path(output_root).expanduser().resolve()
        output_root_path.mkdir(parents=True, exist_ok=True)

        cache_path = _get_cache_path(output_root_path)
        cache = _load_cache(output_root_path)

        # 第一层缓存：直接使用已经解密好的 db_dir
        if use_cache_db and not force_decrypt:
            cached_db_dir = _get_cached_db_dir(
                cache=cache,
                db_version=db_version,
                source_dir=source_dir,
            )

            if cached_db_dir:
                return _success(
                    message="使用缓存 db_dir，跳过 key 检测和重复解密",
                    db_dir=Path(cached_db_dir),
                    wxid=cache.get("wxid"),
                    source_dir=cache.get("source_dir"),
                    from_cache_db=True,
                    from_cache_key=False,
                    cache_path=str(cache_path),
                )

        # print("[DEBUG] use_cache_key =", use_cache_key)
        # print("[DEBUG] force_find_key =", force_find_key)
        # print("[DEBUG] will_try_cache_key =", use_cache_key and not force_find_key)

        # 第二层缓存：用缓存 key 重新解密最新数据库
        if use_cache_key and not force_find_key:
            cached_key_info = _get_cached_key_info(
                cache=cache,
                db_version=db_version,
                source_dir=source_dir,
            )

            if cached_key_info:
                if db_version == 4:
                    result = _dump_v4_with_key(
                        key=cached_key_info["key"],
                        wxid=cached_key_info["wxid"],
                        wx_dir=cached_key_info["source_dir"],
                        nick_name=cached_key_info.get("nick_name"),
                        output_root=output_root_path,
                    )
                else:
                    return _fail(f"不支持的 db_version：{db_version}")

                if result.get("ok"):
                    _update_cache(
                        output_root_path,
                        db_version=db_version,
                        wxid=result.get("wxid"),
                        nick_name=cached_key_info.get("nick_name"),
                        source_dir=_norm_path(result.get("source_dir")),
                        db_dir=_norm_path(result.get("db_dir")),
                        key=cached_key_info["key"],
                    )

                    result["message"] = "使用缓存 key 重新解密成功，跳过重新检测 key"
                    result["from_cache_db"] = False
                    result["from_cache_key"] = True
                    result["cache_path"] = str(cache_path)
                    return result

                # 缓存 key 解密失败时，不直接失败，继续尝试重新检测 key
                print("[decrypt cache] 缓存 key 解密失败，尝试重新检测 key")

        # 第三步：重新检测 key，并解密
        if db_version == 4:
            result = _dump_v4_find_key(
                source_dir=source_dir,
                output_root=output_root_path,
            )
        else:
            return _fail(f"不支持的 db_version：{db_version}")

        # 重新检测成功后，写入缓存
        if result.get("ok"):
            key = result.pop("_key", None)
            nick_name = result.pop("_nick_name", None)

            _update_cache(
                output_root_path,
                db_version=db_version,
                wxid=result.get("wxid"),
                nick_name=nick_name,
                source_dir=_norm_path(result.get("source_dir")),
                db_dir=_norm_path(result.get("db_dir")),
                key=key,
            )

            result["from_cache_db"] = False
            result["from_cache_key"] = False
            result["cache_path"] = str(cache_path)

        return result

    except FileNotFoundError as e:
        return _fail(f"文件不存在：{e}")
    except PermissionError as e:
        return _fail(f"没有权限访问文件：{e}")
    except Exception as e:
        return _fail(f"数据库解析失败：{e}")


# =========================
# cache helpers
# =========================

def _get_cache_path(output_root: Path) -> Path:
    return output_root / "decrypt_cache.json"


def _load_cache(output_root: Path) -> dict[str, Any]:
    cache_path = _get_cache_path(output_root)

    if not cache_path.exists():
        return {}

    try:
        with open(cache_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        return data if isinstance(data, dict) else {}

    except Exception:
        return {}


def _save_cache(output_root: Path, cache: dict[str, Any]) -> None:
    cache_path = _get_cache_path(output_root)
    cache_path.parent.mkdir(parents=True, exist_ok=True)

    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)


def _update_cache(output_root: Path, **kwargs: Any) -> None:
    cache = _load_cache(output_root)

    for key, value in kwargs.items():
        if value is not None:
            cache[key] = value

    cache["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    _save_cache(output_root, cache)


def clear_decrypt_cache(output_root: str | os.PathLike = ".") -> None:
    output_root_path = Path(output_root).expanduser().resolve()
    cache_path = _get_cache_path(output_root_path)

    if cache_path.exists():
        cache_path.unlink()


def _norm_path(path: str | os.PathLike | None) -> str | None:
    if not path:
        return None

    try:
        return str(Path(path).expanduser().resolve())
    except Exception:
        return str(path)


def _same_path(path1: str | os.PathLike | None, path2: str | os.PathLike | None) -> bool:
    if not path1 or not path2:
        return False

    return _norm_path(path1) == _norm_path(path2)


def _cache_matches(
    cache: dict[str, Any],
    db_version: int,
    source_dir: str | None,
) -> bool:
    cached_db_version = cache.get("db_version")

    if cached_db_version is None:
        return False

    if int(cached_db_version) != int(db_version):
        return False

    # 如果本次传了 source_dir，则必须和缓存一致
    if source_dir:
        cached_source_dir = cache.get("source_dir")

        if not _same_path(cached_source_dir, source_dir):
            return False

    return True


def _get_cached_db_dir(
    cache: dict[str, Any],
    db_version: int,
    source_dir: str | None,
) -> str | None:
    if not _cache_matches(cache, db_version, source_dir):
        return None

    cached_db_dir = cache.get("db_dir")

    if _db_dir_is_ready(cached_db_dir):
        return str(Path(cached_db_dir).resolve())

    return None


def _get_cached_key_info(
    cache: dict[str, Any],
    db_version: int,
    source_dir: str | None,
) -> dict[str, Any] | None:
    if not _cache_matches(cache, db_version, source_dir):
        return None

    key = cache.get("key")
    wxid = cache.get("wxid")
    cached_source_dir = cache.get("source_dir")

    if not key:
        return None

    if not wxid:
        return None

    if not cached_source_dir:
        return None

    if not Path(cached_source_dir).exists():
        return None

    return {
        "key": key,
        "wxid": wxid,
        "source_dir": str(Path(cached_source_dir).resolve()),
        "nick_name": cache.get("nick_name"),
    }


def _db_dir_is_ready(db_dir: str | os.PathLike | None) -> bool:
    """
    宽松判断 db_dir 是否可用：
    1. 路径存在
    2. 是文件夹
    3. 有 info.json 或至少一个 .db 文件
    """

    if not db_dir:
        return False

    db_path = Path(db_dir)

    if not db_path.exists():
        return False

    if not db_path.is_dir():
        return False

    has_info = (db_path / "info.json").exists()
    has_db = any(db_path.rglob("*.db"))

    return has_info or has_db


# =========================
# dump with cached key
# =========================

def _dump_v4_with_key(
    key: str,
    wxid: str,
    wx_dir: str,
    nick_name: str | None,
    output_root: Path,
) -> dict[str, Any]:
    wx_dir_path = Path(wx_dir).resolve()

    if not wx_dir_path.exists():
        return _fail(f"缓存的微信原始目录不存在：{wx_dir_path}")

    me = Me()
    me.wx_dir = str(wx_dir_path)
    me.wxid = wxid
    me.name = nick_name or ""
    me.xor_key = get_decode_code_v4(str(wx_dir_path))

    output_dir = output_root / wxid

    decrypt_v4.decrypt_db_files(
        key,
        src_dir=str(wx_dir_path),
        dest_dir=str(output_dir),
    )

    db_dir = output_dir / "db_storage"
    db_dir.mkdir(parents=True, exist_ok=True)

    info_path = db_dir / "info.json"
    with open(info_path, "w", encoding="utf-8") as f:
        json.dump(me.to_json(), f, ensure_ascii=False, indent=4)

    return _success(
        message="微信 4.0 数据库解析成功",
        db_dir=db_dir,
        wxid=wxid,
        source_dir=str(wx_dir_path),
    )


# =========================
# dump by finding key
# =========================

def _dump_v4_find_key(
    source_dir: str | None,
    output_root: Path,
) -> dict[str, Any]:
    """
    重新检测微信 4.0 key，并解密数据库。
    """

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

    result = _dump_v4_with_key(
        key=key,
        wxid=wx_info.wxid,
        wx_dir=wx_dir,
        nick_name=wx_info.nick_name,
        output_root=output_root,
    )

    if result.get("ok"):
        result["_key"] = key
        result["_nick_name"] = wx_info.nick_name

    return result


# =========================
# misc helpers
# =========================

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
    **extra: Any,
) -> dict[str, Any]:
    result = {
        "ok": True,
        "message": message,
        "db_dir": str(db_dir.resolve()),
        "wxid": wxid,
        "source_dir": source_dir,
    }

    result.update(extra)

    return result


def _fail(message: str) -> dict[str, Any]:
    return {
        "ok": False,
        "message": message,
        "db_dir": None,
        "wxid": None,
        "source_dir": None,
    }


def debug_wechat_info(db_version: int = 4) -> None:
    """
    诊断当前是否能检测到微信账号、微信目录和 key。
    不要打印 key 内容，只打印 key 是否存在。
    """

    if db_version == 4:
        wx_info_list = get_info_v4()

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