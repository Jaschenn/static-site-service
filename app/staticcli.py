#!/usr/bin/env python3
"""staticcli — static.jaschen.life CLI 工具

用法:
  staticcli set-key <key>         配置 API Key
  staticcli set-email <email>     配置邮箱（管理用）
  staticcli config                查看当前配置
  staticcli publish <file>        发布 HTML 文件
  staticcli publish --html "..."  直接发布 HTML
  staticcli publish <file> --password <pwd>  发布并设置密码保护
  staticcli list                  列出我的站点
  staticcli delete <shortcode>    删除站点
"""

import json
import os
import sys
import urllib.error
import urllib.request

CONFIG_DIR = os.path.expanduser("~/.staticcli")
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")
API_BASE = os.environ.get("STATIC_API", "https://static.jaschen.life")


def load_config():
    """加载配置"""
    if not os.path.exists(CONFIG_FILE):
        return {}
    with open(CONFIG_FILE) as f:
        return json.load(f)


def save_config(cfg):
    """保存配置"""
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(CONFIG_FILE, "w") as f:
        json.dump(cfg, f, indent=2)


def api_request(method, path, headers=None, body=None):
    """发送 API 请求"""
    url = f"{API_BASE}{path}"
    data = body.encode("utf-8") if body else None
    req = urllib.request.Request(url, data=data, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        err_body = e.read().decode()
        try:
            err_json = json.loads(err_body)
            msg = err_json.get("detail", err_body)
        except Exception:
            msg = err_body
        die(f"HTTP {e.code}: {msg}")


def die(msg):
    """错误退出"""
    print(f"❌ {msg}", file=sys.stderr)
    sys.exit(1)


def cmd_set_key(args):
    """配置 API Key"""
    key = args[0]
    cfg = load_config()
    cfg["key"] = key
    save_config(cfg)
    print("✅ API Key 已保存")


def cmd_set_email(args):
    """配置邮箱"""
    email = args[0]
    cfg = load_config()
    cfg["email"] = email
    save_config(cfg)
    print("✅ 邮箱已保存")


def cmd_config(args):
    """查看配置"""
    cfg = load_config()
    if not cfg:
        print("未配置。请先运行 staticcli set-key <key>")
        return
    print("当前配置：")
    print(f"  API Key: {cfg.get('key', '(未设置)')[:12]}...")
    print(f"  邮箱:    {cfg.get('email', '(未设置)')}")


def cmd_publish(args):
    """发布 HTML"""
    cfg = load_config()
    key = cfg.get("key")
    if not key:
        die("请先配置 API Key: staticcli set-key <key>")

    # 解析 --password flag
    password = None
    filtered_args = []
    skip_next = False
    for i, a in enumerate(args):
        if skip_next:
            skip_next = False
            continue
        if a == "--password":
            if i + 1 >= len(args):
                die("--password 需要提供密码值")
            password = args[i + 1]
            skip_next = True
        else:
            filtered_args.append(a)
    args = filtered_args

    if len(args) >= 2 and args[0] == "--html":
        html = args[1]
    elif len(args) >= 1:
        filepath = args[0]
        if not os.path.exists(filepath):
            die(f"文件不存在: {filepath}")
        if os.path.getsize(filepath) > 4 * 1024 * 1024:
            die("文件超过 4MB 限制")
        with open(filepath, encoding="utf-8") as f:
            html = f.read()
    elif not sys.stdin.isatty():
        html = sys.stdin.read()
    else:
        die('用法: staticcli publish <file> 或 staticcli publish --html "..." 或 cat file.html | staticcli publish')

    print(f"📤 正在发布... ({len(html.encode('utf-8')) / 1024:.1f} KB)")

    headers = {
        "X-API-Key": key,
        "Content-Type": "text/html; charset=utf-8",
    }
    if password:
        headers["X-Site-Password"] = password

    result = api_request(
        "POST",
        "/api/sites",
        headers=headers,
        body=html,
    )

    print("✅ 发布成功！")
    print(f"   URL:    {result['url']}")
    print(f"   短码:   {result['shortcode']}")
    if result.get("title"):
        print(f"   标题:   {result['title']}")
    if result.get("has_password"):
        print("   🔒 密码保护已启用")


def cmd_list(args):
    """列出站点"""
    cfg = load_config()
    key = cfg.get("key")
    email = cfg.get("email")
    if not key or not email:
        die("请先配置: staticcli set-key <key> && staticcli set-email <email>")

    result = api_request(
        "GET",
        "/api/sites",
        headers={
            "X-API-Key": key,
            "X-Email": email,
        },
    )

    sites = result.get("sites", [])
    if not sites:
        print("还没有发布任何站点")
        return

    print(f"我的站点（共 {len(sites)} 个）：")
    print("─" * 60)
    for s in sites:
        title = s["title"] or "无标题"
        size = f"{s['size_bytes'] / 1024:.1f} KB"
        lock = " 🔒" if s.get("has_password") else ""
        print(f"  [{s['shortcode']}]{lock} {title}")
        print(f"  → {s['url']}  ({size})  {s['created_at']}")
        print()


def cmd_delete(args):
    """删除站点"""
    if not args:
        die("用法: staticcli delete <shortcode>")

    shortcode = args[0]
    cfg = load_config()
    key = cfg.get("key")
    email = cfg.get("email")
    if not key or not email:
        die("请先配置: staticcli set-key <key> && staticcli set-email <email>")

    print(f"🗑️  正在删除 {shortcode}...")

    result = api_request(
        "DELETE",
        f"/api/sites/{shortcode}",
        headers={
            "X-API-Key": key,
            "X-Email": email,
        },
    )

    print(f"✅ {result['message']}")


COMMANDS = {
    "set-key": cmd_set_key,
    "set-email": cmd_set_email,
    "config": cmd_config,
    "publish": cmd_publish,
    "list": cmd_list,
    "delete": cmd_delete,
}

HELP_TEXT = """staticcli — static.jaschen.life CLI

命令:
  set-key <key>          配置 API Key
  set-email <email>      配置邮箱（用于 list/delete 管理操作）
  config                 查看当前配置
  publish <file>         发布 HTML 文件
  publish --html "..."   直接发布 HTML 字符串
  publish <file> --password <pwd>  发布并设置密码保护
  list                   列出所有已发布站点
  delete <shortcode>     删除站点

示例:
  staticcli set-key sk_abc123...
  staticcli set-email me@example.com
  staticcli publish index.html
  staticcli list
  staticcli delete aBcDeFgH

也可用 stdin:
  cat page.html | staticcli publish
"""


def main():
    args = sys.argv[1:]

    if not args or args[0] in ("help", "--help", "-h"):
        print(HELP_TEXT)
        return

    cmd = args[0]
    cmd_args = args[1:]

    if cmd not in COMMANDS:
        die(f"未知命令: {cmd}\n运行 staticcli help 查看帮助")

    COMMANDS[cmd](cmd_args)


if __name__ == "__main__":
    main()
