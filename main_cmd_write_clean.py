def cmd_write(memory, continuity, foreshadow, rag, project_name, chapter=None):
    """生成章节（含审校自动修改循环）"""
    outline_path = Path(config.DATA_DIR) / "outline.json"
    if not outline_path.exists():
        print("❌ 未找到大纲文件，请先运行：python main.py new")
        return

    with open(outline_path, "r", encoding="utf-8") as f:
        outline = json.load(f)

    chapter_plan = outline.get("chapter_plan", [])
    if not chapter_plan:
        print("❌ 大纲中没有章节计划")
        return

    if chapter is None:
        import glob
        existing = glob.glob(str(Path(config.OUTPUT_DIR) / "chapters" / "chapter_*.md"))
        chapter = len(existing) + 1

    ch_data = next((c for c in chapter_plan if c["chapter"] == chapter), None)
    if ch_data is None:
        print(f"❌ 大纲中没有第 {chapter} 章的计划")
        return

    check_api_key()

    title = ch_data.get("title", "")
    summary = ch_data.get("summary", "")
    time_tag = ch_data.get("time_tag", "")
    location = ch_data.get("location", "")
    characters = ch_data.get("characters", [])

    print()
    print(f"=== 生成第 {chapter} 章：{title} ===")
    print(f"摘要：{summary}")
    print(f"时间：{time_tag}")
    print(f"地点：{location}")
    print("人物：" + ", ".join(characters))
    print()
    print("🤖 正在生成，请稍候（约1-3分钟）...")
    print()

    writer = WriterAgent(
        memory, continuity, foreshadow, rag,
        genre=outline.get("genre", "玄幻"),
        style=outline.get("style", "热血"),
    )
    reviewer = ReviewerAgent(memory, continuity, foreshadow)

    try:
        # 1. 生成章节
        content = writer.write_chapter(
            chapter=chapter,
            title=title,
            summary=summary,
            time_tag=time_tag,
            location=location,
            characters=characters,
        )
        writer.save_chapter(chapter, title, content)

        # 2. 审校 + 自动修改循环
        max_revisions = 3
        for rev in range(max_revisions + 1):
            report = reviewer.review_chapter(chapter, title, content)
            print()
            print(f"📋 审校报告（第{rev+1}次）：")
            raw = report["raw_text"]
            print(raw[:2000])
            v = report["verdict"]
            s = report["overall_score"]
            print()
            print(f"结论：{v} | 总分：{s}")

            if report["passed"]:
                print()
                print("✅ 审校通过！")
                break

            if rev >= max_revisions:
                print()
                print(f"⚠️ 已达最大修订次数（{max_revisions}），接受当前版本")
                break

            # 自动修改
            print()
            print(f"🔧 根据审校意见自动修改（第{rev+1}次修订）...")
            content = writer.revise_chapter(
                chapter=chapter,
                title=title,
                original_content=content,
                review_report=report["raw_text"],
                summary=summary,
                time_tag=time_tag,
                location=location,
                characters=characters,
            )
            writer.save_chapter(chapter, title, content)
            print("  修订完成，重新审校...")

        # 3. 更新项目进度
        update_project_progress(project_name, chapters_written=chapter)

        # 4. 重新生成 novel.md
        rebuild_novel_md(config.OUTPUT_DIR)

        print()
        print(f"✅ 第 {chapter} 章完成！")
        print(f"  字数：约 {len(content)} 字")
        print(f"  保存至：{config.OUTPUT_DIR}/chapters/chapter_{chapter:03d}.md")

        # 伏笔
        pending = foreshadow.get_pending()
        new_fs = [fs for fs in pending if fs.chapter_planted == chapter]
        if new_fs:
            print()
            print("📌 本章提取的伏笔：")
            for fs in new_fs:
                print(f"  - [{fs.id}] {fs.content[:50]}...")
        else:
            print()
            print("📌 本章无新伏笔")

        print()
        print("--- 正文预览（前300字）---")
        print(content[:300])
        print("...")

        next_ch = chapter + 1
        if next_ch <= len(chapter_plan):
            print()
            print(f"💡 下一步：python main.py write  # 生成第{next_ch}章")
        else:
            print()
            print("💡 大纲章节已全部生成！")
    except Exception as e:
        print(f"❌ 生成失败：{e}")
        import traceback
        traceback.print_exc()

