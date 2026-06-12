from pathlib import Path
import sqlite3

db_root = Path(r"D:\2_PycharmTestData\temp\wxid_iyxaccobdc7v22\db_storage")

print("检查目录:", db_root)
print("存在:", db_root.exists())

ok_files = []
bad_files = []
skipped_files = []

for p in db_root.rglob("*"):
    if not p.is_file():
        continue

    # info.json 本来就不是数据库
    if p.name.lower() == "info.json":
        skipped_files.append(p)
        continue

    try:
        with open(p, "rb") as f:
            header = f.read(16)
    except Exception as e:
        bad_files.append((p, f"无法读取: {e}"))
        continue

    # 不是 SQLite 文件头的，先标出来
    if header != b"SQLite format 3\x00":
        bad_files.append((p, header))
        continue

    # 文件头是 SQLite，再尝试真正连接
    try:
        conn = sqlite3.connect(str(p))
        conn.execute("SELECT name FROM sqlite_master LIMIT 1;")
        conn.close()
        ok_files.append(p)
    except Exception as e:
        bad_files.append((p, f"sqlite3 打开失败: {e}"))

print("\n跳过文件数量:", len(skipped_files))
for p in skipped_files:
    print("[SKIP]", p)

print("\n可正常打开的 SQLite 文件数量:", len(ok_files))
for p in ok_files[:100]:
    print("[OK]", p)

print("\n异常文件数量:", len(bad_files))
for p, reason in bad_files[:100]:
    print("[BAD]", p, "reason =", reason)