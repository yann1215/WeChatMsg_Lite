from wxManager import DatabaseConnection

db_dir = r"D:\2_PycharmTestData\temp\wxid_iyxaccobdc7v22\db_storage"
db_version = 4

conn = DatabaseConnection(db_dir, db_version)
database = conn.get_interface()

contacts = database.get_contacts()

print("联系人总数:", len(contacts))
print("=" * 100)

for i, contact in enumerate(contacts[:30], start=1):
    print(f"[{i}] type={type(contact)}")
    print(contact)
    print("__dict__:", getattr(contact, "__dict__", None))
    print("-" * 100)