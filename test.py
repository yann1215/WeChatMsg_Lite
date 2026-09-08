from wxManager.decrypt import get_info_v4

infos = get_info_v4()

for info in infos:
    print(
        # info.wxid,
        # info.wx_dir,
        info.nick_name,
        # info.key,
    )