"""
AetherBrowser Backend Server v0.3
==================================

FastAPI + WebSocket entry point. The Chrome extension connects here.

Merged from Claude v0.2 (model bridge + streaming) + Codex lane
(research routing + PollyVision + reconnect indicator).

v0.3 adds:
- HydraHand browser research via BrowserBridge (graceful fallback)
- ResearchFunnel persistence to local JSONL / Notion / HuggingFace
- PollyVision-style structured page metadata
- Safe WebSocket sends that handle mid-stream disconnects
- Squad state reset on disconnect

Start:
    python -m uvicorn src.aetherbrowser.serve:app --host 127.0.0.1 --port 8002
"""
from __future__ import annotations

import json
import logging
from typing import Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from starlette.websockets import WebSocketState

from src.aetherbrowser.ws_feed import WsFeed, MsgType, Agent
from src.aetherbrowser.agents import AgentSquad, TongueRole, AgentState
from src.aetherbrowser.page_analyzer import PageAnalyzer
from src.aetherbrowser.router import OctoArmorRouter
from src.aetherbrowser.model_bridge import ModelBridge
from src.aetherbrowser.hyperlane_py import HyperLanePy, Decision as HLDecision
from src.aetherbrowser.browser_bridge import BrowserBridge

logger = logging.getLogger("aetherbrowser")

app = FastAPI(title="AetherBrowser", version="0.3.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Shared instances
feed = WsFeed()
squad = AgentSquad(feed)
analyzer = PageAnalyzer()
router = OctoArmorRouter()
bridge = ModelBridge()
hyperlane = HyperLanePy()
browser_bridge = BrowserBridge(persist=True)

# System prompt for AetherBrowser agents
_AETHER_SYSTEM = (
    "You are an AetherBrowser AI agent — part of a 6-agent Sacred Tongue squad. "
    "Be concise, helpful, and actionable. When researching, cite sources. "
    "When analyzing pages, extract key points. Format with markdown."
)


@app.get("/health")
def health():
    return {
        "status": "ok",
        "version": "0.3.0",
        "agents": squad.status_snapshot(),
        "providers": bridge.available_providers(),
        "browser_available": browser_bridge.is_available(),
    }


async def _safe_send(ws: WebSocket, data: dict) -> bool:
    """Send JSON to WebSocket, return False if connection is closed."""
    try:
        if ws.client_state == WebSocketState.CONNECTED:
            await ws.send_json(data)
            return True
    except Exception:
        pass
    return False


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    try:
        while True:
            raw = await ws.receive_text()
            try:
                msg = WsFeed.parse(raw)
            except (ValueError, json.JSONDecodeError) as e:
                await _safe_send(ws, feed.error(str(e)))
                continue

            msg_type = msg.get("type")

            if msg_type == MsgType.COMMAND.value:
                await _handle_command(ws, msg)
            elif msg_type == MsgType.PAGE_CONTEXT.value:
                await _handle_page_context(ws, msg)
            elif msg_type == MsgType.ZONE_RESPONSE.value:
                await _handle_zone_response(ws, msg)
            else:
                await _safe_send(ws, feed.error(f"Unhandled message type: {msg_type}"))

    except WebSocketDisconnect:
        logger.info("Client disconnected")
        _reset_squad()
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        _reset_squad()


def _reset_squad():
    """Reset all agents to idle on disconnect."""
    for role in TongueRole:
        squad.set_state(role, AgentState.IDLE)


# ── Research query detection (from Codex lane) ──────────────────────


def _extract_research_query(text: str) -> Optional[str]:
    """Parse research-prefixed commands. Returns query string or None."""
    stripped = (text or "").strip()
    if not stripped:
        return None
    lowered = stripped.lower()
    if lowered.startswith("[research]"):
        return stripped[len("[research]"):].strip() or None
    if lowered.startswith("research:"):
        return stripped.split(":", 1)[1].strip() or None
    if lowered.startswith("research "):
        return stripped[len("research "):].strip() or None
    return None


# ── Command handler ──────────────────────────────────────────────────


async def _handle_command(ws: WebSocket, msg: dict) -> None:
    text = msg.get("payload", {}).get("text", "")
    if not text:
        await _safe_send(ws, feed.error("Empty command"))
        return

    # Check if this is a research command
    research_query = _extract_research_query(text)
    if research_query and browser_bridge.is_available():
        await _handle_research_command(ws, research_query)
        return

    # Decompose task into agent assignments
    assignments = squad.decompose(text)

    # Score complexity and pick model for KO (lead agent)
    complexity = router.score_complexity(text)
    model = router.select_model(complexity, role="KO")
    model_name = model.provider.value

    # Set KO to working
    squad.set_state(TongueRole.KO, AgentState.WORKING, model=model_name)
    await _safe_send(ws, feed.agent_status(Agent.KO, "working", model=model_name))

    # Assign other agents
    for a in assignments:
        if a["role"] != TongueRole.KO:
            role_agent = Agent[a["role"].value]
            await _safe_send(ws, feed.agent_status(role_agent, "assigned"))

    # Stream real LLM response from KO
    prompt = _build_prompt(text, assignments)
    accumulated = await _stream_llm(ws, model, model_name, prompt)

    # DR structures the findings for complex tasks
    full_response = "".join(accumulated)
    if full_response and len(assignments) > 2:
        squad.set_state(TongueRole.DR, AgentState.WORKING, model="local")
        await _safe_send(ws, feed.agent_status(Agent.DR, "working", model="local"))
        summary = _extract_summary(full_response)
        await _safe_send(ws, feed.chat(Agent.DR, summary, model="local"))
        squad.set_state(TongueRole.DR, AgentState.DONE)
        await _safe_send(ws, feed.agent_status(Agent.DR, "done"))

    # Mark agents done
    squad.set_state(TongueRole.KO, AgentState.DONE)
    await _safe_send(ws, feed.agent_status(Agent.KO, "done"))
    for a in assignments:
        if a["role"] != TongueRole.KO:
            role_agent = Agent[a["role"].value]
            await _safe_send(ws, feed.agent_status(role_agent, "done"))


# ── Research command (HydraHand + Funnel) ────────────────────────────


async def _handle_research_command(ws: WebSocket, query: str) -> None:
    """Full browser research pipeline via BrowserBridge."""
    await _safe_send(ws, feed.chat(
        Agent.KO,
        f"Research pipeline starting: **{query}**",
        model="hydra-hand",
    ))
    await _safe_send(ws, feed.progress(Agent.KO, current=1, total=4, label="HydraHand boot"))

    # AV scouting
    squad.set_state(TongueRole.AV, AgentState.WORKING, model="playwright")
    await _safe_send(ws, feed.agent_status(Agent.AV, "scouting", model="playwright"))

    report = await browser_bridge.research(query, max_urls=5)

    await _safe_send(ws, feed.progress(Agent.KO, current=2, total=4, label="Research complete"))

    if report.error:
        await _safe_send(ws, feed.error(f"Research pipeline failed: {report.error}"))
        squad.set_state(TongueRole.AV, AgentState.DONE)
        await _safe_send(ws, feed.agent_status(Agent.AV, "done"))
        return

    # Report discoveries
    squad.set_state(TongueRole.AV, AgentState.DONE)
    await _safe_send(ws, feed.chat(
        Agent.AV,
        f"Discovered {report.urls_discovered} URLs, "
        f"{report.urls_safe} safe, {report.urls_blocked} blocked",
        model="playwright",
    ))

    # CA extraction report
    if report.extractions:
        squad.set_state(TongueRole.CA, AgentState.WORKING, model="playwright")
        await _safe_send(ws, feed.chat(
            Agent.CA,
            f"Extracted content from {len(report.extractions)} pages",
            model="playwright",
        ))
        squad.set_state(TongueRole.CA, AgentState.DONE)

    await _safe_send(ws, feed.progress(Agent.KO, current=3, total=4, label="Structured synthesis"))

    # DR structures + funnel receipt
    summary_lines = [f"Research complete for: **{query}**"]
    summary_lines.append(f"- Sources extracted: {len(report.extractions)}")

    if report.funnel_receipt:
        receipt = report.funnel_receipt
        summary_lines.append(f"- Local JSONL: {receipt.get('local_path') or 'n/a'}")
        summary_lines.append(f"- HuggingFace committed: {receipt.get('hf_committed')}")
        if receipt.get("notion_url"):
            summary_lines.append(f"- Notion page: {receipt['notion_url']}")
        if receipt.get("errors"):
            summary_lines.append(f"- Pipeline warnings: {', '.join(receipt['errors'])}")

    await _safe_send(ws, feed.chat(
        Agent.DR,
        "\n".join(summary_lines),
        model="hydra-funnel",
    ))
    await _safe_send(ws, feed.progress(Agent.KO, current=4, total=4, label="Done"))

    # Mark all done
    for role in TongueRole:
        squad.set_state(role, AgentState.DONE)
        await _safe_send(ws, feed.agent_status(Agent[role.value], "done"))


# ── LLM streaming helper ────────────────────────────────────────────


async def _stream_llm(
    ws: WebSocket, model, model_name: str, prompt: str
) -> list[str]:
    """Stream LLM response, return accumulated chunks. Cascades on failure."""
    accumulated = []
    try:
        async for chunk in bridge.stream(model.provider, prompt, system=_AETHER_SYSTEM):
            accumulated.append(chunk)
            if not await _safe_send(ws, feed.stream_chunk(Agent.KO, chunk, done=False, model=model_name)):
                break  # Client disconnected mid-stream

        await _safe_send(ws, feed.stream_chunk(Agent.KO, "", done=True, model=model_name))

    except Exception as e:
        logger.error(f"LLM call failed: {e}")
        router.mark_rate_limited(model.provider)
        await _safe_send(ws, feed.chat(
            Agent.KO,
            f"Model {model_name} failed ({type(e).__name__}). Cascading.",
            model=model_name,
        ))

        # Cascade to next available model
        try:
            complexity = router.score_complexity(prompt[:200])
            fallback = router.select_model(complexity, role="KO")
            fallback_name = fallback.provider.value
            squad.set_state(TongueRole.KO, AgentState.WORKING, model=fallback_name)
            await _safe_send(ws, feed.agent_status(Agent.KO, "working", model=fallback_name))

            response = await bridge.complete(fallback.provider, prompt, system=_AETHER_SYSTEM)
            await _safe_send(ws, feed.chat(Agent.KO, response.text, model=fallback_name))
            accumulated = [response.text]
        except Exception as e2:
            logger.error(f"Cascade also failed: {e2}")
            await _safe_send(ws, feed.error(f"All models failed: {e2}"))

    return accumulated


# ── Page context handler ─────────────────────────────────────────────


async def _handle_page_context(ws: WebSocket, msg: dict) -> None:
    payload = msg.get("payload", {})
    url = payload.get("url", "")
    title = payload.get("title", "")
    text = payload.get("text", "")

    # HyperLane governance check on the URL
    if url:
        lane_result = hyperlane.evaluate(url, action="read", agent_id="CA")
        if lane_result.decision == HLDecision.QUARANTINE:
            from src.aetherbrowser.ws_feed import Zone as WsZone
            await _safe_send(ws, feed.zone_request(
                Agent.RU, WsZone(lane_result.zone.value),
                url=url, action="analyze",
                description=f"Page analysis requested for {lane_result.zone.value} zone URL",
            ))

    # CA does local analysis first
    squad.set_state(TongueRole.CA, AgentState.WORKING, model="local")
    await _safe_send(ws, feed.agent_status(Agent.CA, "analyzing"))

    result = analyzer.analyze_sync(url=url, title=title, text=text)

    # Build PollyVision-style metadata without Playwright dependency
    page_meta = _build_page_metadata(url, title, text, result)

    local_summary = (
        f"**{result['title']}**\n"
        f"Words: {result['word_count']} | "
        f"Topics: {', '.join(result['topics']) or 'General'}\n"
        f"Reading time: ~{page_meta['reading_time_min']}min | "
        f"Links: {page_meta['link_count']} | "
        f"Token est: ~{page_meta['token_estimate']} | "
        f"Zone: {page_meta['zone']}\n\n"
        f"{result['summary']}"
    )
    await _safe_send(ws, feed.chat(Agent.CA, local_summary, model="local"))
    squad.set_state(TongueRole.CA, AgentState.DONE)
    await _safe_send(ws, feed.agent_status(Agent.CA, "done"))

    # If there's enough content, have KO do an AI-enriched analysis
    if result["word_count"] > 100:
        complexity = router.score_complexity(text[:200])
        model = router.select_model(complexity, role="KO")
        model_name = model.provider.value
        squad.set_state(TongueRole.KO, AgentState.WORKING, model=model_name)
        await _safe_send(ws, feed.agent_status(Agent.KO, "working", model=model_name))

        enrich_prompt = (
            f"Analyze this web page and provide key insights:\n\n"
            f"Title: {title}\nURL: {url}\n"
            f"Topics: {', '.join(result['topics'])}\n"
            f"Word count: {result['word_count']}\n\n"
            f"Content (first 3000 chars):\n{text[:3000]}\n\n"
            f"Provide: 1) Main thesis, 2) Key points (bullet list), "
            f"3) Actionable takeaways"
        )

        try:
            async for chunk in bridge.stream(model.provider, enrich_prompt, system=_AETHER_SYSTEM, max_tokens=1024):
                if not await _safe_send(ws, feed.stream_chunk(Agent.KO, chunk, done=False, model=model_name)):
                    break
            await _safe_send(ws, feed.stream_chunk(Agent.KO, "", done=True, model=model_name))
        except Exception as e:
            logger.warning(f"AI enrichment failed: {e}")
            await _safe_send(ws, feed.chat(
                Agent.KO, f"AI enrichment skipped: {type(e).__name__}", model=model_name
            ))

        squad.set_state(TongueRole.KO, AgentState.DONE)
        await _safe_send(ws, feed.agent_status(Agent.KO, "done"))

    # Persist page analysis to funnel if substantial
    if result["word_count"] > 200 and url:
        receipt = await browser_bridge.persist_extractions(
            [{"url": url, "title": title, "text": text[:2000]}],
            query=f"page:{title[:50]}",
        )
        if receipt and receipt.get("local_path"):
            await _safe_send(ws, feed.chat(
                Agent.DR,
                f"Page data persisted: {receipt['records_written']} record(s)",
                model="local",
            ))

    # DR structures topics
    if result["topics"]:
        await _safe_send(ws, feed.chat(
            Agent.DR,
            f"Structured topics: {json.dumps(result['topics'])}",
            model="local",
        ))


async def _handle_zone_response(ws: WebSocket, msg: dict) -> None:
    payload = msg.get("payload", {})
    decision = payload.get("decision", "deny")
    await _safe_send(ws, feed.chat(
        Agent.RU,
        f"Zone decision received: {decision}",
    ))


# ── Utility functions ────────────────────────────────────────────────


def _build_prompt(text: str, assignments: list[dict]) -> str:
    """Build a prompt that includes the agent squad context."""
    agent_context = ", ".join(
        f"{a['role'].value}: {a['task']}" for a in assignments
    )
    return (
        f"User request: {text}\n\n"
        f"You are KO, the lead agent. Your squad:\n{agent_context}\n\n"
        f"Respond to the user's request directly and helpfully."
    )


def _extract_summary(text: str) -> str:
    """Extract a brief summary from a longer response."""
    sentences = text.replace("\n", " ").split(". ")
    if len(sentences) <= 3:
        return f"Summary: {text[:500]}"
    key_sentences = sentences[:3]
    return f"Key findings: {'. '.join(key_sentences)}."


def _build_page_metadata(url: str, title: str, text: str, analysis: dict) -> dict:
    """Build PollyVision-style structured metadata without Playwright."""
    import re
    word_count = analysis.get("word_count", 0)
    link_count = len(re.findall(r'https?://\S+', text))
    zone = hyperlane.classify_zone(url).value if url else "UNKNOWN"
    # Token estimate: ~0.75 tokens per word for English text
    token_estimate = int(word_count * 0.75)

    return {
        "word_count": word_count,
        "reading_time_min": max(1, word_count // 250),
        "link_count": link_count,
        "zone": zone,
        "token_estimate": token_estimate,
        "topics": analysis.get("topics", []),
        "has_code": bool(re.search(r'```|def |function |class |import ', text)),
        "has_headings": bool(re.search(r'^#{1,6}\s', text, re.MULTILINE)),
    }
