"""Back up your own Xiaohongshu notes using the creator dashboard.
Install: python3 -m pip install playwright
          python3 -m playwright install chromium
Test:     python3 xhs_backup.py --owner OWNER_ID --limit 3
Full run: python3 xhs_backup.py --owner OWNER_ID
"""
import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from time import monotonic
from urllib.parse import urlparse

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

MANAGER = "https://creator.xiaohongshu.com/new/note-manager"
ROOT = Path.home() / "Downloads" / "XHS-Code-Backup"
NOTE_PATH = re.compile(r"/(?:explore|discovery/item)/([0-9a-f]{24})/?$")
MEDIA_TYPES = {
    "image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp",
    "image/gif": ".gif", "image/avif": ".avif", "video/mp4": ".mp4",
    "video/webm": ".webm",
}


COMMENT_TIMEOUT_MS = 30_000
COMMENT_IDLE_SECONDS = 60


def retry_comment_step(step, action, retries=2):
    for attempt in range(retries + 1):
        try:
            return action()
        except PlaywrightTimeoutError:
            if attempt == retries:
                raise
            print(f"评论步骤超时：{step}，正在重试（{attempt + 1}/{retries}）", flush=True)


def backup_folder(output, note_id, published, title):
    prefix = published.replace(":", "-") if published else "发布时间未知"
    label = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", title)
    label = re.sub(r"\s+", " ", label).strip(" .")
    label = label.encode("utf-8")[:160].decode("utf-8", errors="ignore").rstrip(" .")
    target = output / f"{prefix} {label or '无标题'} [{note_id}]"
    if not target.exists():
        old = output / note_id
        candidates = [path for path in output.iterdir()
                      if path.is_dir() and path.name.endswith(f" [{note_id}]")]
        if old.is_dir():
            candidates.append(old)
        if len(candidates) == 1:
            candidates[0].rename(target)
        elif candidates:
            raise ValueError("发现多个同 ID 的备份文件夹，未自动合并")
    return target


def write_comments(target, data):
    for thread in data["threads"]:
        for comment in [thread, *thread["replies"]]:
            comment.setdefault("published_at_display", None)
            comment.setdefault("published_at", None)
    data["timestamp_schema"] = 2
    data["updated_at"] = datetime.now(timezone.utc).isoformat()
    pending = target.with_suffix(".json.part")
    pending.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    pending.replace(target)


def backup_comments(page, detail, folder, zero_comments):
    """Save the threads the logged-in account can load, including replies."""
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / "comments.json"
    previous = json.loads(target.read_text(encoding="utf-8")) if target.exists() else {}
    if zero_comments:
        threads = previous.get("threads", [])
        if not previous.get("complete") or previous.get("timestamp_schema") != 2:
            write_comments(target, {"complete": True, "threads": threads})
        return "后台显示 0 条评论，已跳过加载"
    if previous.get("complete") and previous.get("timestamp_schema") == 2:
        return "评论已有备份"

    panel = detail.locator(".comments-container, .comment-container").filter(visible=True).first
    empty = detail.get_by_text(
        re.compile(r"^(?:暂无评论|还没有评论|这是一片荒地)[。！!\s]*(?:点击评论)?$")
    ).filter(visible=True).first
    comments_ready = panel.or_(empty).first
    def thread_key(thread):
        return thread["id"] or json.dumps(
            [thread["author"], thread["text"], thread["metadata"]], ensure_ascii=False
        )

    threads = {thread_key(thread): thread for thread in previous.get("threads", [])}
    last_signature = None
    last_progress = monotonic()
    complete = False
    reply_index = 0
    scroll_next = False
    expand = re.compile(r"^(?:展开|查看)(?:全部|更多)?\s*\d*\s*(?:条)?\s*回复$|^更多回复$")
    step = "等待评论区或无评论提示"
    try:
        retry_comment_step(
            step, lambda: comments_ready.wait_for(state="visible", timeout=5000), retries=1
        )
        last_progress = monotonic()
        while monotonic() - last_progress < COMMENT_IDLE_SECONDS:
            if empty.is_visible():
                complete = True
                break
            step = "读取评论区"
            snapshot = retry_comment_step(step, lambda: panel.evaluate("""root => {
              const rows = [...root.querySelectorAll('.parent-comment')];
              const read = el => {
                const item = el.matches('.comment-item') ? el : el.querySelector('.comment-item') || el;
                const date = item.querySelector('.date, time');
                const time = date?.matches('time, [datetime]') ? date : date?.querySelector('time, [datetime]');
                const display = (date?.querySelector('span:first-child') || time || date)
                  ?.innerText.trim().split('\\n')[0] || null;
                const absoluteDisplay = display?.match(/^\\d{4}[-/.]\\d{1,2}[-/.]\\d{1,2}(?:[ T]\\d{1,2}:\\d{2}(?::\\d{2})?)?/);
                return {
                  id: item.id || item.getAttribute('data-comment-id') || '',
                  author: item.querySelector('.author-wrapper .name, a.name')?.innerText || '',
                  text: item.querySelector('.note-text, .content')?.innerText || '',
                  metadata: item.querySelector('.date')?.innerText || '',
                  published_at_display: display,
                  published_at: time?.getAttribute('datetime') || absoluteDisplay?.[0] || null
                };
              };
              const threads = rows.map(row => ({
                ...read(row),
                replies: [...row.querySelectorAll('.reply-container .comment-item')].map(read)
              }));
              return {
                threads,
                end: [...root.querySelectorAll(".end-container, .no-comments, .empty, .no-comment")].some(
                  el => /(?:THE END|没有更多评论|暂无评论|这是一片荒地)/i.test(el.innerText)
                ),
                height: root.scrollHeight
              };
            }""", timeout=COMMENT_TIMEOUT_MS))
            for thread in snapshot["threads"]:
                if not thread["text"]:
                    continue
                thread_id = thread_key(thread)
                prior = threads.get(thread_id)
                if not prior or len(thread["replies"]) >= len(prior["replies"]):
                    threads[thread_id] = thread

            more = panel.get_by_text(expand).filter(visible=True)
            more_count = more.count()
            has_more = more_count > 0
            if snapshot["end"] and not has_more:
                complete = True
                break
            signature = (
                len(threads), sum(len(t["replies"]) for t in threads.values()),
                snapshot["height"], more_count,
            )
            if signature != last_signature:
                last_progress = monotonic()
                last_signature = signature
            if has_more and not scroll_next:
                step = "展开回复"
                button = more.nth(reply_index % more_count)
                try:
                    button.click(timeout=2500)
                except PlaywrightTimeoutError:
                    print("展开回复暂未响应，继续滚动评论区。", flush=True)
                reply_index += 1
                scroll_next = True
            else:
                step = "滚动加载评论"
                retry_comment_step(step, lambda: panel.evaluate("""root => {
                  let scroller = root.querySelector('.parent-comment')?.parentElement || root;
                  const detail = root.closest('#noteContainer');
                  while (scroller && (!detail || detail.contains(scroller))) {
                    const style = getComputedStyle(scroller);
                    if (/^(auto|scroll|overlay)$/.test(style.overflowY) &&
                        scroller.scrollHeight > scroller.clientHeight + 1) {
                      scroller.scrollBy(0, Math.max(200, scroller.clientHeight * 0.8));
                      return;
                    }
                    scroller = scroller.parentElement;
                  }
                }""", timeout=COMMENT_TIMEOUT_MS))
                scroll_next = False
            page.wait_for_timeout(1000)
        else:
            print("连续 60 秒没有新增评论或回复，保留已抓取内容。", flush=True)
    except Exception as error:
        print(f"评论加载中断：{step}（{type(error).__name__}）", flush=True)

    data = {"complete": complete, "threads": list(threads.values())}
    write_comments(target, data)
    count = len(data["threads"])
    replies = sum(len(thread["replies"]) for thread in data["threads"])
    status = "已到评论末尾" if data["complete"] else "评论未确认完整"
    return f"{status}（{count} 条主评论，{replies} 条回复）"


def backup(page, context, output, card_title, published, zero_comments, owner):
    url = urlparse(page.url)
    match = NOTE_PATH.fullmatch(url.path)
    if url.hostname not in {"www.xiaohongshu.com", "xiaohongshu.com"} or not match:
        raise ValueError("未打开小红书笔记详情页")
    note_id = match[1]

    detail = page.locator("#noteContainer")
    detail.wait_for(state="visible", timeout=10000)
    if detail.locator(f'a[href*="/user/profile/{owner}"]').count() == 0:
        raise ValueError("详情区未找到你的账号，已跳过")
    desc = detail.locator("#detail-desc")
    explicit = detail.locator("#detail-title")
    body = desc.inner_text().strip() if desc.count() else ""
    title = explicit.inner_text().strip() if explicit.count() else ""
    first_line = next((line.strip() for line in body.splitlines() if line.strip()), "")
    title = title or re.split(r"(?<=[。！？!?])", first_line, maxsplit=1)[0]
    if not title:
        raise ValueError("详情区未发现可确认的标题或正文")

    normalize = lambda value: re.sub(r"[^\w]", "", value).casefold()
    expected = normalize(card_title)[:12]
    if expected and card_title != "无笔记标题" and not (
        normalize(title).startswith(expected) or normalize(body).startswith(expected)
    ):
        raise ValueError("详情正文和后台卡片不匹配，已跳过")

    folder = backup_folder(output, note_id, published, title)
    note_file = folder / "note.md"
    timestamp = f"发布时间：{published or '未知'}"
    if note_file.is_file():
        contents = note_file.read_text(encoding="utf-8")
        header, separator, rest = contents.partition("\n\n")
        if not rest.startswith(timestamp + "\n\n"):
            if rest.startswith("发布时间："):
                _, _, rest = rest.partition("\n\n")
            pending = folder / "note.md.part"
            pending.write_text(f"# {title}{separator}{timestamp}\n\n{rest}", encoding="utf-8")
            pending.replace(note_file)
        return "已有笔记，" + backup_comments(page, detail, folder, zero_comments)

    sources = detail.evaluate("""note => {
      const gallery = note.querySelector('.swiper, .media-container, .note-slider');
      const images = gallery ? [...gallery.querySelectorAll('img')] : [];
      return [...images, ...note.querySelectorAll('video, video source')]
        .map(el => el.currentSrc || el.src).filter(Boolean);
    }""")
    folder.mkdir(parents=True, exist_ok=True)
    assets = []
    seen = set()
    for src in sources:
        media = urlparse(src)
        host = media.hostname or ""
        if media.scheme != "https" or not any(
            host == domain or host.endswith("." + domain)
            for domain in ("xhscdn.com", "rednotecdn.com")
        ):
            continue
        # Carousel clones may use the same path with different query parameters.
        identity = (host, media.path)
        if identity in seen:
            continue
        seen.add(identity)
        response = context.request.get(src, timeout=20000, max_redirects=0)
        content_type = response.headers.get("content-type", "").split(";")[0]
        if not response.ok or content_type not in MEDIA_TYPES:
            raise ValueError(f"媒体下载失败（HTTP {response.status}）")
        filename = f"{len(assets) + 1:02d}{MEDIA_TYPES[content_type]}"
        (folder / filename).write_bytes(response.body())
        assets.append(filename)

    if not assets:
        raise ValueError("没有找到可直接下载的图片或视频，未标记为完成")
    links = "\n".join(
        f"![图片]({name})" if Path(name).suffix not in {".mp4", ".webm"}
        else f"[视频]({name})" for name in assets
    )
    pending = folder / "note.md.part"
    pending.write_text(
        f"# {title}\n\n{timestamp}\n\n笔记 ID：{note_id}\n\n{body}\n\n{links}\n",
        encoding="utf-8",
    )
    pending.replace(folder / "note.md")
    return "已备份，" + backup_comments(page, detail, folder, zero_comments)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=0, help="最多尝试多少篇，0 表示全部")
    parser.add_argument("--output", type=Path, default=ROOT)
    parser.add_argument("--owner", required=True, help="个人主页 URL 中的 24 位用户 ID")
    args = parser.parse_args()
    if not re.fullmatch(r"[0-9a-f]{24}", args.owner):
        parser.error("--owner 必须是 24 位小写十六进制用户 ID")
    args.output.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as pw:
        context = pw.chromium.launch_persistent_context(
            str(Path.home() / ".xhs-backup-browser"), headless=False
        )
        page = context.pages[0]
        try:
            page.goto(MANAGER, wait_until="domcontentloaded")
            input("请在浏览器登录并打开‘笔记管理’，看到列表后按回车：")
            cards = page.locator(".note-card")
            cards.first.wait_for(state="visible", timeout=15000)
            index = 0
            while not args.limit or index < args.limit:
                count = cards.count()
                if index >= count:
                    cards.last.scroll_into_view_if_needed()
                    page.mouse.move(700, 550)
                    page.mouse.wheel(0, 1100)
                    try:
                        cards.nth(index).wait_for(state="attached", timeout=7000)
                    except Exception:
                        print(f"列表未继续加载。本轮处理了 {index} 张卡片。")
                        break

                card = cards.nth(index)
                title = card.locator(".note-card__title").inner_text(timeout=4000).strip()
                print(f"{index + 1}. 开始备份 | {title}", flush=True)
                detail_page = None
                try:
                    time_row = card.locator(".note-card__row--time").first
                    time_text = (time_row if time_row.count() else card).inner_text(timeout=4000)
                    card_lines = time_text.replace("–", "-").replace("−", "-").splitlines()
                    published = next((line.strip() for line in card_lines
                                      if re.fullmatch(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}(?::\d{2})?", line.strip())), None)
                    stats = card.locator(".note-card__row--stats").first
                    numbers = stats.inner_text(timeout=2000).split() if stats.count() else []
                    # The dashboard shows views, comments, likes, saves and shares in that order.
                    zero_comments = (
                        len(numbers) == 5
                        and all(re.fullmatch(r"[0-9,.]+[万亿wWkK]?", n) for n in numbers)
                        and numbers[1] == "0"
                    )
                    with page.expect_popup(timeout=5500) as popup:
                        card.locator(".note-card__cover").click(timeout=5000)
                    detail_page = popup.value
                    detail_page.wait_for_url(
                        re.compile(r"/(?:explore|discovery/item)/[0-9a-f]{24}"), timeout=10000
                    )
                    status = backup(detail_page, context, args.output, title, published, zero_comments, args.owner)
                except Exception as error:
                    status = "未完成"
                    with (args.output / "failures.jsonl").open("a", encoding="utf-8") as log:
                        log.write(json.dumps({
                            "card": index + 1, "title": title,
                            "error": str(error).splitlines()[0].split("?")[0],
                        }, ensure_ascii=False) + "\n")
                finally:
                    if detail_page is not None and not detail_page.is_closed():
                        detail_page.close()
                print(f"{index + 1}. {status} | {title}", flush=True)
                index += 1
        finally:
            context.close()


if __name__ == "__main__":
    main()
