from sqlalchemy.ext.asyncio import AsyncSession
from app.agents.state import NovelState
from app.agents.graph import apply_user_decision, check_revision, finalize
from app.services.chapter_service import save_chapter, save_chapter_semantic, _state_to_response
from app.models.user_preference import ModificationRecord


async def process_user_decisions(
    db: AsyncSession,
    novel_id: int,
    chapter_number: int,
    state: NovelState,
    decisions: list[dict],
) -> dict:
    state["user_decisions"] = decisions

    for decision in decisions:
        if decision.get("action") == "custom" and decision.get("original_text") and decision.get("custom_text"):
            mod_record = ModificationRecord(
                novel_id=novel_id,
                chapter_number=chapter_number,
                original_text=decision["original_text"],
                modified_text=decision["custom_text"],
                modification_type=decision.get("modification_type", "style"),
                reader_suggestion=decision.get("suggestion", ""),
                user_decision="modified",
                user_note=decision.get("note", ""),
            )
            db.add(mod_record)

        elif decision.get("action") == "accept_suggestion" and decision.get("original_text") and decision.get("suggestion"):
            mod_record = ModificationRecord(
                novel_id=novel_id,
                chapter_number=chapter_number,
                original_text=decision["original_text"],
                modified_text=decision["suggestion"],
                modification_type=decision.get("modification_type", "plot"),
                reader_suggestion=decision.get("suggestion", ""),
                user_decision="accepted",
                user_note="",
            )
            db.add(mod_record)

    await db.commit()

    state = await apply_user_decision(state)

    route = await check_revision(state)
    if route == "finalize":
        state = await finalize(state)
    elif route == "user_decision":
        pass

    if state.get("is_final", False):
        from app.agents.readers.polish_reader import polish_chapter
        polish_result = await polish_chapter(state)
        state["polished_draft"] = polish_result.get("polished_draft", "")

        final_draft = state.get("polished_draft", "") or state.get("chapter_draft", "")
        await save_chapter(
            db, novel_id, chapter_number,
            final_draft,
            state.get("chapter_title", ""),
            "final",
        )
        await save_chapter_semantic(db, novel_id, chapter_number, final_draft)

    return _state_to_response(state)


async def finalize_chapter(
    db: AsyncSession,
    novel_id: int,
    chapter_number: int,
    state: NovelState,
) -> dict:
    state["is_final"] = True
    state = await finalize(state)

    final_draft = state.get("polished_draft", "") or state.get("chapter_draft", "")
    await save_chapter(
        db, novel_id, chapter_number,
        final_draft,
        state.get("chapter_title", ""),
        "final",
    )
    await save_chapter_semantic(db, novel_id, chapter_number, final_draft)

    return _state_to_response(state)
