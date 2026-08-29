"use client";

import {
  BgColorsOutlined,
  CreditCardOutlined,
  LogoutOutlined,
  SettingOutlined,
} from "@ant-design/icons";
import { Avatar, Button, Dropdown, message, type MenuProps } from "antd";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { logoutAccount, type AccountUser, userMessage } from "@/lib/auth-client";

import styles from "./account-menu.module.css";

function initialFor(nickname: string) {
  return Array.from(nickname.trim())[0] || "用";
}

export function AccountMenu({ user }: Readonly<{ user: AccountUser }>) {
  const router = useRouter();
  const [messageApi, messageHolder] = message.useMessage();
  const [loggingOut, setLoggingOut] = useState(false);

  const signOut = async () => {
    if (loggingOut) return;
    setLoggingOut(true);
    try {
      await logoutAccount();
      router.replace("/login");
      router.refresh();
    } catch (error) {
      messageApi.error(userMessage(error));
      setLoggingOut(false);
    }
  };

  const items: MenuProps["items"] = [
    {
      key: "identity",
      disabled: true,
      label: (
        <span className={styles.identity}>
          <strong>{user.nickname}</strong>
          <small>{user.phone_masked}</small>
        </span>
      ),
    },
    { type: "divider" },
    { key: "settings", icon: <SettingOutlined />, label: "账号设置" },
    { key: "appearance", icon: <BgColorsOutlined />, label: "外观设置" },
    { key: "subscription", icon: <CreditCardOutlined />, label: "套餐与额度" },
    { type: "divider" },
    {
      key: "logout",
      danger: true,
      icon: <LogoutOutlined />,
      label: loggingOut ? "正在退出…" : "退出登录",
      disabled: loggingOut,
    },
  ];

  const handleMenuClick: MenuProps["onClick"] = ({ key }) => {
    if (key === "settings") router.push("/account/settings");
    if (key === "appearance") router.push("/account/settings#appearance");
    if (key === "subscription") router.push("/subscription");
    if (key === "logout") void signOut();
  };

  return (
    <>
      {messageHolder}
      <Dropdown
        trigger={["click"]}
        placement="bottomRight"
        menu={{ items, onClick: handleMenuClick }}
      >
        <Button
          type="text"
          className={styles.trigger}
          aria-label="打开账号菜单"
          aria-haspopup="menu"
        >
          <Avatar className={styles.avatar} size={32} aria-hidden="true">
            {initialFor(user.nickname)}
          </Avatar>
          <span className={styles.nickname}>{user.nickname}</span>
        </Button>
      </Dropdown>
    </>
  );
}
