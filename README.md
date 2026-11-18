# 小红书笔记备份

[简体中文](README.md) · [English](README.en.md)

备份你自己的小红书笔记、可下载的图片和视频，以及网页能加载的评论和回复。

## 交给 AI 使用

笔记列表入口在[小红书创作服务平台 · 笔记管理](https://creator.xiaohongshu.com/new/note-manager)。

**把这个仓库链接发给有终端和浏览器能力的 AI 助手即可。你无需自己安装依赖或输入命令。** 可以直接发这句话：

> 请读取这个仓库的 README，用它备份我的小红书笔记。先试跑前三篇并核对结果，再运行全量备份。需要登录时告诉我扫码。

AI 助手应克隆仓库，在可启动图形浏览器的本地环境中创建虚拟环境、安装依赖并执行下面的命令。通过用户提供的个人主页链接确认用户 ID，取主页 URL 中 `/user/profile/` 后的 24 位 ID。浏览器要求登录时，由用户在打开的小红书页面扫码。看到创作后台笔记列表后，在脚本的终端输入回车继续。若环境无法启动浏览器或没有本地写入权限，应说明具体限制。

## 命令

在仓库目录运行。前四行只需配置一次。将 `OWNER_ID` 替换为你自己的用户 ID。

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m playwright install chromium
python xhs_backup.py --owner OWNER_ID --limit 3
```

确认试跑结果后，将最后一行换成 `python xhs_backup.py --owner OWNER_ID` 即可全量备份。默认保存到 `~/Downloads/XHS-Code-Backup`，可用 `--output` 修改。每篇有独立目录，包含 `note.md`、媒体文件和 `comments.json`。评论未读完会保留已抓取内容，下次运行会尝试补抓。检查终端输出和 `failures.jsonl`，确认是否有遗漏。

## 实现机制

脚本用 Playwright 打开小红书网页，通过 **DOM** 定位标题、正文、评论和交互控件。点击笔记和展开回复后，小红书网页自己的 JavaScript 会继续请求数据并更新 DOM，脚本再读取这些节点。脚本从详情区取得媒体 URL，再用 HTTP 下载文件。

这里的浏览器自动化是 DOM 级的。定位元素依据网页结构，整个流程无需传统 GUI 的屏幕坐标点击、截图识别或 OCR。脚本也不直接调用小红书的笔记或评论 API。页面未加载出来的数据可能无法备份。
