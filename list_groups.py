from wxManager import DatabaseConnection


db_dir = r"D:\2_PycharmTestData\temp\wxid_iyxaccobdc7v22\db_storage"
db_version = 4

conn = DatabaseConnection(db_dir, db_version)
database = conn.get_interface()

contacts = database.get_contacts()

print("开始列出群聊：")
print("=" * 80)

count = 0

for contact in contacts:
    username = str(getattr(contact, "username", "") or "")
    nickname = str(getattr(contact, "nickname", "") or "")
    remark = str(getattr(contact, "remark", "") or "")
    alias = str(getattr(contact, "alias", "") or "")

    if username.endswith("@chatroom"):
        count += 1
        print(f"[{count}]")
        print("username:", username)
        print("nickname:", nickname)
        print("remark  :", remark)
        print("alias   :", alias)
        print("-" * 80)

print(f"共找到群聊数量：{count}")