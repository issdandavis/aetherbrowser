"""
AetherBrowser Backend Server
==============================

FastAPI + WebSocket entry point. The Chrome extension connects here.

Start:
    python -m uvicorn src.aetherbrowser.serve:app --host 127.0.0.1 --port 8002
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from src.aetherbrowser.ws_feed import WsFeed, MsgType, Agent, Zone
from src.aetherbrowser.agents import AgentSquad, TongueRole, AgentState
from src.aetherbrowser.command_planner import CommandPlan, build_command_plan
from src.aetherbrowser.context_pool import POOL
from src.aetherbrowser.page_analyzer import PageAnalyzer
from src.aetherbrowser.provider_executor import ProviderExecutor
from src.aetherbrowser.router import OctoArmorRouter
from src.aetherbrowser.topology_engine import compute_page_topology

logger = logging.getLogger("aetherbrowser")

app = FastAPI(title="AetherBrowser", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["chrome-extension://*", "http://127.0.0.1:*", "http://localhost:*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Shared instances
feed = WsFeed()
squad = AgentSquad(feed)
analyzer = PageAnalyzer()
router = OctoArmorRouter()
executor = ProviderExecutor()
pending_zone_requests: dict[int, "PendingCommandApproval"] = {}
pending_browser_actions: list[dict[str, Any]] = []
pending_controller_events: list[dict[str, Any]] = []
MAX_PENDING_BROWSER_ACTIONS = 50
MAX_PENDING_CONTROLLER_EVENTS = 100
ALLOWED_BROWSER_ACTIONS = {"navigate", "read_page", "capture_page_context", "open_agent_spot"}
ALLOWED_CONTROLLER_EVENTS = {
    "observe",
    "move_up",
    "move_down",
    "move_left",
    "move_right",
    "back",
    "forward",
    "reload",
    "primary",
    "secondary",
    "type",
    "escape",
    "haptic",
}
STATE_CHANGING_CONTROLLER_EVENTS = {"primary", "secondary", "type"}


@dataclass
class PendingCommandApproval:
    plan: CommandPlan
    assignments: list[dict[str, Any]]


def _derive_topology_lens(
    *,
    result: dict[str, Any],
    topology: dict[str, Any],
    forms: list[dict[str, Any]],
    buttons: list[dict[str, Any]],
) -> dict[str, Any]:
    approvals = [str(item).lower() for item in result.get("required_approvals", [])]
    boundary_signals: list[str] = []

    has_password_field = any(
        any(str(field.get("type", "")).lower() == "password" for field in form.get("fields", [])) for form in forms
    )
    if has_password_field or any("authentication" in item or "credential" in item for item in approvals):
        boundary_signals.append("identity boundary present")

    if buttons or any("high-impact" in item or "payment" in item for item in approvals):
        boundary_signals.append("state-change controls exposed")

    nodes = topology.get("nodes", [])
    red_radii = [float(node.get("radius", 0.0)) for node in nodes if node.get("zone") == Zone.RED.value]
    yellow_radii = [float(node.get("radius", 0.0)) for node in nodes if node.get("zone") == Zone.YELLOW.value]

    if result.get("risk_tier") == "high" or red_radii:
        zone = Zone.RED.value
        trust_distance = max(red_radii or yellow_radii or [0.0])
    elif result.get("risk_tier") == "medium" or yellow_radii:
        zone = Zone.YELLOW.value
        trust_distance = max(yellow_radii or [0.0])
    else:
        zone = Zone.GREEN.value
        trust_distance = 0.0

    return {
        "zone": zone,
        "trust_distance": round(trust_distance, 6),
        "boundary_signals": boundary_signals,
    }


@app.get("/health")
def health():
    return {
        "status": "ok",
        "version": "0.1.0",
        # How many sidebar agent spots are live, so the UI can show occupancy.
        "connected_sidebars": POOL.connection_count,
        "agents": squad.status_snapshot(),
        "providers": router.provider_status_snapshot(),
        "executor": executor.runtime_status_snapshot(),
    }


@app.get("/context")
def context():
    """
    Shared-context snapshot for the UI / any agent that wants the pooled state
    over plain HTTP (no WebSocket required).

    Returns the live connection count plus the current user_intent, page_context,
    the last 20 findings, the last 20 decisions, and the last 30 message_log
    entries. Sync read is fine — ContextPool.snapshot() never awaits.
    """
    return POOL.snapshot()


@app.get("/headless/capabilities")
def headless_capabilities():
    """
    Machine-readable control-plane contract for desktop, mobile, and agent-only
    clients. Keep this stable so external agents do not have to scrape UI state.
    """
    return {
        "product": "AetherBrowser",
        "contract_version": "0.1",
        "surfaces": ["desktop-electron", "ios-swiftui", "headless-http", "websocket"],
        "backend": {
            "health": "/health",
            "context": "/context",
            "websocket": "/ws",
        },
        "headless": {
            "command": {
                "method": "POST",
                "path": "/headless/command",
                "body": {
                    "text": "required user/agent command",
                    "routing": "optional routing preferences",
                    "execute": "optional bool, default true",
                    "allow_approval_required": "optional bool, default false",
                    "source": "optional label for the calling agent",
                },
            },
            "page_context": {
                "method": "POST",
                "path": "/headless/page-context",
                "body": {
                    "url": "page URL",
                    "title": "page title",
                    "text": "visible text",
                    "headings": [],
                    "links": [],
                    "forms": [],
                    "buttons": [],
                    "tabs": [],
                    "selection": "",
                    "page_type": "generic",
                },
            },
            "browser_action": {
                "method": "POST",
                "path": "/headless/browser-action",
                "body": {
                    "action": "navigate | read_page | capture_page_context | open_agent_spot",
                    "url": "required for navigate",
                    "source": "optional calling agent label",
                },
            },
            "controller_event": {
                "method": "POST",
                "path": "/headless/controller-event",
                "body": {
                    "event": "observe | move_up | move_down | move_left | move_right | back | forward | reload | primary | secondary | type | escape | haptic",
                    "text": "optional text for type events",
                    "intensity": "optional haptic intensity 0.0-1.0",
                    "allow_state_change": "optional bool, default false",
                    "source": "optional calling agent label",
                },
            },
        },
        "controller": {
            "model": "webpage_as_game_state",
            "state": "/headless/controller-state",
            "events": sorted(ALLOWED_CONTROLLER_EVENTS),
            "haptics": ["selection", "impact", "success", "warning", "error"],
        },
        "guardrails": {
            "approval_required_flows": [
                "authentication",
                "credentials",
                "payment",
                "publish",
                "delete",
                "submit",
                "browser actions that are not clearly read-only",
            ],
            "default_headless_policy": "plan and answer read-only tasks; hold approval-required tasks unless explicitly allowed",
        },
        "communication_tools": {
            "status": "extension point",
            "expected_shape": "add adapters as explicit tools that call the headless contract instead of driving UI directly",
        },
    }


@app.get("/headless/browser-actions")
def headless_browser_actions():
    return {
        "ok": True,
        "pending": pending_browser_actions[-MAX_PENDING_BROWSER_ACTIONS:],
    }


@app.get("/headless/controller-state")
def headless_controller_state():
    ctx = POOL.snapshot()
    page = ctx.get("page_context") or {}
    return {
        "ok": True,
        "model": "webpage_as_game_state",
        "objective": ctx.get("user_intent", ""),
        "page": {
            "url": page.get("url", ""),
            "title": page.get("title", ""),
            "page_type": page.get("page_type", "generic"),
            "selection": page.get("selection", ""),
        },
        "controller": {
            "dpad": {
                "up": "move_up",
                "down": "move_down",
                "left": "move_left",
                "right": "move_right",
            },
            "buttons": {
                "a": "primary",
                "b": "secondary",
                "start": "observe",
                "back": "back",
                "reload": "reload",
                "escape": "escape",
            },
            "text": "type",
            "haptic": "haptic",
        },
        "guardrails": {
            "state_changing_events": sorted(STATE_CHANGING_CONTROLLER_EVENTS),
            "require_allow_state_change": True,
        },
        "pending": pending_controller_events[-MAX_PENDING_CONTROLLER_EVENTS:],
        "context": ctx,
    }


@app.post("/headless/controller-event")
async def headless_controller_event(request: dict[str, Any]):
    event = str(request.get("event", "")).strip()
    if event not in ALLOWED_CONTROLLER_EVENTS:
        return {
            "ok": False,
            "status": "error",
            "error": f"Unsupported controller event: {event}",
            "allowed": sorted(ALLOWED_CONTROLLER_EVENTS),
        }

    allow_state_change = bool(request.get("allow_state_change", False))
    if event in STATE_CHANGING_CONTROLLER_EVENTS and not allow_state_change:
        return {
            "ok": True,
            "status": "approval_required",
            "event": event,
            "required_approvals": ["Controller event may change page state"],
        }

    text = str(request.get("text", ""))
    if event == "type" and not text:
        return {"ok": False, "status": "error", "error": "type requires text"}

    intensity = _clamp_float(request.get("intensity", 0.45), 0.0, 1.0)
    payload = {
        "id": str(uuid4()),
        "event": event,
        "text": text,
        "source": str(request.get("source") or "headless-agent"),
        "haptic": _haptic_for_controller_event(event, intensity),
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    message = {
        "type": MsgType.CONTROLLER_EVENT.value,
        "agent": Agent.SYSTEM.value,
        "payload": payload,
        "ts": payload["created_at"],
    }
    pending_controller_events.append(payload)
    if len(pending_controller_events) > MAX_PENDING_CONTROLLER_EVENTS:
        del pending_controller_events[: len(pending_controller_events) - MAX_PENDING_CONTROLLER_EVENTS]
    await POOL.log_message(message)
    delivered = await POOL.broadcast(message)
    return {
        "ok": True,
        "status": "queued",
        "delivered": delivered,
        "controller_event": payload,
    }


@app.post("/headless/browser-action")
async def headless_browser_action(request: dict[str, Any]):
    action = str(request.get("action", "")).strip()
    if action not in ALLOWED_BROWSER_ACTIONS:
        return {
            "ok": False,
            "status": "error",
            "error": f"Unsupported browser action: {action}",
            "allowed": sorted(ALLOWED_BROWSER_ACTIONS),
        }

    url = str(request.get("url", "")).strip()
    if action == "navigate":
        if not (url.startswith("http://") or url.startswith("https://")):
            return {
                "ok": False,
                "status": "error",
                "error": "navigate requires an http(s) URL",
            }

    payload = {
        "id": str(uuid4()),
        "action": action,
        "url": url,
        "source": str(request.get("source") or "headless-agent"),
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    message = {
        "type": MsgType.BROWSER_ACTION.value,
        "agent": Agent.SYSTEM.value,
        "payload": payload,
        "ts": payload["created_at"],
    }
    pending_browser_actions.append(payload)
    if len(pending_browser_actions) > MAX_PENDING_BROWSER_ACTIONS:
        del pending_browser_actions[: len(pending_browser_actions) - MAX_PENDING_BROWSER_ACTIONS]
    await POOL.log_message(message)
    delivered = await POOL.broadcast(message)
    return {
        "ok": True,
        "status": "queued",
        "delivered": delivered,
        "browser_action": payload,
    }


@app.post("/headless/command")
async def headless_command(request: dict[str, Any]):
    """
    Agent-only command lane. This is the stable entry point for external agents,
    MCP tools, and future communication adapters.
    """
    text = str(request.get("text", "")).strip()
    if not text:
        return {"ok": False, "status": "error", "error": "Empty command"}

    source = str(request.get("source") or "headless-agent")
    routing = request.get("routing", {}) if isinstance(request.get("routing"), dict) else {}
    execute = bool(request.get("execute", True))
    allow_approval_required = bool(request.get("allow_approval_required", False))

    incoming = {
        "type": MsgType.COMMAND.value,
        "agent": source,
        "payload": {"text": text, "routing": routing},
    }
    await POOL.update_context("user_intent", text)
    await POOL.log_message(incoming)
    await POOL.broadcast(incoming)

    plan = _build_plan_for_payload(text=text, routing=routing)
    plan_payload = plan.to_dict()
    if not execute:
        await POOL.append_decision(f"headless plan only: {plan.intent}")
        return {
            "ok": True,
            "status": "planned",
            "plan": plan_payload,
            "context": POOL.snapshot(),
        }

    if plan.approval_required and not allow_approval_required:
        await POOL.append_decision(f"held for review: {plan.intent} risk={plan.risk_tier}")
        return {
            "ok": True,
            "status": "approval_required",
            "plan": plan_payload,
            "required_approvals": plan.required_approvals,
            "review_zone": plan.review_zone,
            "context": POOL.snapshot(),
        }

    try:
        execution = await executor.execute(plan, context_summary=POOL.get_context_summary())
    except Exception as exc:
        return {
            "ok": False,
            "status": "execution_error",
            "plan": plan_payload,
            "error": str(exc),
        }

    ko_chat = feed.chat(
        Agent.KO,
        execution.text,
        model=execution.model_id,
        payload={"execution": execution.to_dict()},
    )
    await POOL.log_message(ko_chat)
    await POOL.append_finding(execution.text)
    await POOL.append_decision(
        f"{plan.intent} -> {execution.provider}/{execution.model_id}"
        f" (headless, fallback={execution.fallback_used})"
    )
    await POOL.broadcast(ko_chat)
    return {
        "ok": True,
        "status": "completed",
        "plan": plan_payload,
        "execution": execution.to_dict(),
        "message": ko_chat,
        "context": POOL.snapshot(),
    }


@app.post("/headless/page-context")
async def headless_page_context(payload: dict[str, Any]):
    """
    Agent-only page-context ingestion. Desktop, iOS, and external agents can all
    publish the same page snapshot shape here.
    """
    analysis = await _analyze_page_payload(payload)
    ca_chat = feed.chat(
        Agent.CA,
        analysis["summary_text"],
        model="local",
        payload={"page_analysis": analysis["result"]},
    )
    await POOL.log_message(ca_chat)
    await POOL.append_finding(
        f"Page analysis: {analysis['result']['title']} ({analysis['result']['intent']}, risk={analysis['result']['risk_tier']})"
    )
    await POOL.broadcast(ca_chat)
    return {
        "ok": True,
        "status": "analyzed",
        "page_analysis": analysis["result"],
        "topology": analysis["topology"],
        "context": POOL.snapshot(),
    }


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    # Join the shared context pool so this sidebar shares ONE live context with
    # every other connected tab/window.
    await POOL.register(ws)
    try:
        while True:
            raw = await ws.receive_text()
            try:
                msg = WsFeed.parse(raw)
            except (ValueError, json.JSONDecodeError) as e:
                await ws.send_json(feed.error(str(e)))
                continue

            msg_type = msg.get("type")
            try:
                if msg_type == MsgType.COMMAND.value:
                    await _handle_command(ws, msg)
                elif msg_type == MsgType.PAGE_CONTEXT.value:
                    await _handle_page_context(ws, msg)
                elif msg_type == MsgType.ZONE_RESPONSE.value:
                    await _handle_zone_response(ws, msg)
                else:
                    await ws.send_json(feed.error(f"Unhandled message type: {msg_type}"))
            except Exception as handler_exc:
                # A4: never drop the client on handler failure — return JSON so tests/clients
                # do not block forever on receive_json waiting for a reply.
                logger.error("WebSocket handler error: %s", handler_exc, exc_info=True)
                await ws.send_json(feed.error(f"Request failed: {handler_exc}"))

    except WebSocketDisconnect:
        pending_zone_requests.clear()
        logger.info("Client disconnected")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
    finally:
        # Leave the shared context pool no matter how the connection ended.
        await POOL.unregister(ws)


def _build_plan_for_payload(*, text: str, routing: dict[str, Any]) -> CommandPlan:
    routing_preferences = routing.get("preferences") if isinstance(routing.get("preferences"), dict) else None
    auto_cascade = bool(routing.get("auto_cascade", routing.get("autoCascade", True)))
    plan = build_command_plan(
        text=text,
        squad=squad,
        router=router,
        routing_preferences=routing_preferences,
        auto_cascade=auto_cascade,
    )
    # Force RED gate on high-risk actions even if keyword heuristics missed.
    if plan.risk_tier == "high" and not plan.approval_required:
        import dataclasses

        plan = dataclasses.replace(plan, approval_required=True, review_zone="RED")
    return plan


async def _analyze_page_payload(payload: dict[str, Any]) -> dict[str, Any]:
    url = payload.get("url", "")
    title = payload.get("title", "")
    text = payload.get("text", "")
    forms = _normalize_object_list(payload.get("forms"))
    buttons = _normalize_object_list(payload.get("buttons"), default_key="text")
    links = _normalize_object_list(payload.get("links"), default_key="text")
    headings = _normalize_object_list(payload.get("headings"), default_key="text")

    await POOL.update_context(
        "page_context",
        {
            "url": url,
            "title": title,
            "page_type": payload.get("page_type", "generic"),
            "selection": payload.get("selection", ""),
        },
    )

    result = analyzer.analyze_sync(
        url=url,
        title=title,
        text=text,
        headings=headings,
        links=links,
        forms=forms,
        buttons=buttons,
        tabs=payload.get("tabs") or [],
        selection=payload.get("selection", ""),
        page_type=payload.get("page_type", "generic"),
        screenshot=payload.get("screenshot", ""),
    )
    topology = compute_page_topology(
        url=url,
        title=result["title"],
        text=text,
        links=links,
        headings=headings,
        topics=result.get("topics") or [],
        risk_tier=result.get("risk_tier", "low"),
    )
    result["topology_lens"] = _derive_topology_lens(
        result=result,
        topology=topology,
        forms=forms,
        buttons=buttons,
    )

    summary_text = (
        f"Page: {result['title']}\n"
        f"Words: {result['word_count']}\n"
        f"Topics: {', '.join(result['topics']) or 'General'}\n"
        f"Intent: {result['intent']}\n"
        f"Risk: {result['risk_tier']}\n"
        f"Type: {result['page_type']}\n"
        f"Headings: {result['heading_count']} | Links: {result['link_count']}"
        f" | Forms: {result['form_count']} | Tabs: {result['tab_count']}\n\n"
        f"{result['summary']}"
    )
    return {"result": result, "topology": topology, "summary_text": summary_text}


def _normalize_object_list(value: Any, *, default_key: str = "value") -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    normalized: list[dict[str, Any]] = []
    for item in value:
        if isinstance(item, dict):
            normalized.append(item)
        elif item not in (None, ""):
            normalized.append({default_key: str(item)})
    return normalized


def _clamp_float(value: Any, minimum: float, maximum: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = minimum
    return max(minimum, min(maximum, parsed))


def _haptic_for_controller_event(event: str, intensity: float) -> dict[str, Any]:
    if event == "haptic":
        return {"kind": "impact", "intensity": intensity}
    if event in {"move_up", "move_down", "move_left", "move_right"}:
        return {"kind": "selection", "intensity": min(0.35, intensity)}
    if event in {"observe", "reload"}:
        return {"kind": "impact", "intensity": min(0.45, intensity)}
    if event in STATE_CHANGING_CONTROLLER_EVENTS:
        return {"kind": "warning", "intensity": max(0.65, intensity)}
    if event == "escape":
        return {"kind": "impact", "intensity": 0.3}
    return {"kind": "selection", "intensity": intensity}


async def _handle_command(ws: WebSocket, msg: dict) -> None:
    payload = msg.get("payload", {})
    text = payload.get("text", "")
    if not text:
        await ws.send_json(feed.error("Empty command"))
        return

    # Shared context: record the user intent, log the event, and let every OTHER
    # sidebar see this incoming command live.
    await POOL.update_context("user_intent", text)
    await POOL.log_message(msg)
    await POOL.broadcast(msg, exclude=ws)

    routing = payload.get("routing", {}) if isinstance(payload.get("routing"), dict) else {}
    plan = _build_plan_for_payload(text=text, routing=routing)

    assignments = plan.assignments
    squad.set_state(TongueRole.KO, AgentState.WORKING, model=plan.provider)
    await ws.send_json(feed.agent_status(Agent.KO, "working", model=plan.provider))
    await ws.send_json(
        feed.chat(
            Agent.KO,
            _format_command_summary(plan),
            model=plan.provider,
            payload={"plan": plan.to_dict()},
        )
    )

    if plan.approval_required and plan.review_zone:
        squad.set_state(TongueRole.KO, AgentState.WAITING, model=plan.provider)
        await ws.send_json(feed.agent_status(Agent.KO, "waiting", model=plan.provider))
        zone_request = feed.zone_request(
            Agent.RU,
            Zone[plan.review_zone],
            url=plan.targets[0] if plan.targets else "pending://browser-action",
            action=plan.intent,
            description="; ".join(plan.required_approvals),
        )
        pending_zone_requests[zone_request["seq"]] = PendingCommandApproval(
            plan=plan,
            assignments=assignments,
        )
        await ws.send_json(zone_request)
        return

    await _complete_command_flow(ws, plan, assignments)


async def _handle_page_context(ws: WebSocket, msg: dict) -> None:
    payload = msg.get("payload", {})
    await POOL.log_message(msg)
    await POOL.broadcast(msg, exclude=ws)

    await ws.send_json(feed.agent_status(Agent.CA, "analyzing"))
    analysis = await _analyze_page_payload(payload)
    result = analysis["result"]
    topology = analysis["topology"]
    summary_text = analysis["summary_text"]
    ca_chat = feed.chat(
        Agent.CA,
        summary_text,
        model="local",
        payload={"page_analysis": result},
    )
    await ws.send_json(ca_chat)
    # Share the analysis with every other sidebar and remember it as a finding.
    await POOL.log_message(ca_chat)
    await POOL.append_finding(f"Page analysis: {result['title']} ({result['intent']}, risk={result['risk_tier']})")
    await POOL.broadcast(ca_chat, exclude=ws)
    await ws.send_json(
        feed.topology(
            Agent.CA,
            topology,
            model="local",
            zone=result["topology_lens"]["zone"],
        )
    )
    await ws.send_json(feed.agent_status(Agent.CA, "done"))

    if result["topics"]:
        next_action_labels = ", ".join(action["label"] for action in result["next_actions"]) or "none"
        await ws.send_json(
            feed.chat(
                Agent.DR,
                f"Structured topics: {json.dumps(result['topics'])}\nNext actions: {next_action_labels}",
                model="local",
                payload={"page_analysis": result},
            )
        )


async def _handle_zone_response(ws: WebSocket, msg: dict) -> None:
    payload = msg.get("payload", {})
    decision = payload.get("decision", "deny")
    request_seq = payload.get("request_seq")
    pending = pending_zone_requests.pop(request_seq, None)
    if pending is None:
        await ws.send_json(feed.error(f"Unknown zone request: {request_seq}", agent=Agent.RU))
        return

    if decision in {"allow", "allow_once", "add_yellow"}:
        await ws.send_json(
            feed.chat(
                Agent.RU,
                f"Zone decision received: {decision}. Releasing the held browser plan.",
                payload={"plan": pending.plan.to_dict()},
            )
        )
        await _complete_command_flow(ws, pending.plan, pending.assignments)
        return

    squad.set_state(TongueRole.KO, AgentState.ERROR, model=pending.plan.provider)
    await ws.send_json(
        feed.chat(
            Agent.RU,
            f"Zone decision received: {decision}. Browser plan denied.",
            payload={"plan": pending.plan.to_dict()},
        )
    )
    await ws.send_json(feed.agent_status(Agent.KO, "error", model=pending.plan.provider))


async def _complete_command_flow(
    ws: WebSocket,
    plan: CommandPlan,
    assignments: list[dict[str, Any]],
) -> None:
    for assignment in assignments:
        if assignment["role"] == TongueRole.KO:
            continue
        role_agent = Agent[assignment["role"].value]
        await ws.send_json(feed.agent_status(role_agent, "assigned"))

    # Inject the shared context so Claude answers WITH pooled awareness.
    context_summary = POOL.get_context_summary()
    try:
        execution = await executor.execute(plan, context_summary=context_summary)
    except Exception as exc:
        squad.set_state(TongueRole.KO, AgentState.ERROR, model=plan.provider)
        await ws.send_json(feed.error(f"Command execution failed: {exc}", agent=Agent.KO))
        await ws.send_json(feed.agent_status(Agent.KO, "error", model=plan.provider))
        return

    ko_chat = feed.chat(
        Agent.KO,
        execution.text,
        model=execution.model_id,
        payload={"execution": execution.to_dict()},
    )
    await ws.send_json(ko_chat)
    # Share the answer: log it, remember it as a finding/decision, and fan it out
    # to every OTHER sidebar so a second tab sees the same response live.
    await POOL.log_message(ko_chat)
    await POOL.append_finding(execution.text)
    await POOL.append_decision(
        f"{plan.intent} -> {execution.provider}/{execution.model_id}"
        f" (fallback={execution.fallback_used})"
    )
    await POOL.broadcast(ko_chat, exclude=ws)
    await ws.send_json(
        feed.chat(
            Agent.DR,
            (
                f"Execution provider={execution.provider}, model={execution.model_id}, "
                f"fallback_used={execution.fallback_used}, attempted={', '.join(execution.attempted)}."
            ),
            model="local",
            payload={"execution": execution.to_dict()},
        )
    )

    squad.set_state(TongueRole.KO, AgentState.DONE, model=execution.model_id)
    await ws.send_json(feed.agent_status(Agent.KO, "done", model=execution.model_id))


def _format_command_summary(plan: CommandPlan) -> str:
    targets = ", ".join(plan.targets) if plan.targets else "generic browser lane"
    approvals = ", ".join(plan.required_approvals) if plan.required_approvals else "none"
    next_action = plan.next_actions[0].label if plan.next_actions else "review plan"
    return (
        f"Intent: {plan.intent}\n"
        f"Task: {plan.task_type} | Complexity: {plan.complexity.value} | Risk: {plan.risk_tier}\n"
        f"Engine: {plan.preferred_engine} | Target: {targets}\n"
        f"Approvals: {approvals}\n"
        f"Lead action: {next_action}\n"
        f"Model: {plan.provider} ({plan.selection_reason}) | Auto-cascade: {plan.auto_cascade}"
    )
