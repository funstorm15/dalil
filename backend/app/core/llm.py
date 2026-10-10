"""LLM client for the case narrative.

The prototype ships with a local llama.cpp server serving an open-weight
instruct model — the same interface a bank runs on-prem (vLLM / TGI expose the
same OpenAI-compatible API, so production only changes LLM_BASE_URL).
If the model is unavailable the pipeline degrades to a deterministic
extractive narrative and says so — never a silent fake.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

import httpx

DEFAULT_BASE_URL = os.environ.get("LLM_BASE_URL", "http://127.0.0.1:8081/v1")
DEFAULT_MODEL = os.environ.get("LLM_MODEL", "dalil-qwen")


class LLMUnavailable(Exception):
    pass


@dataclass
class LLMStats:
    base_url: str
    model: str
    available: bool
    latency_ms: float = 0.0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    error: str = ""


class LLMClient:
    def __init__(self, base_url: str | None = None, model: str | None = None, timeout: float = 90.0):
        self.base_url = (base_url or DEFAULT_BASE_URL).rstrip("/")
        self.model = model or DEFAULT_MODEL
        self.timeout = timeout
        self.last_stats = LLMStats(base_url=self.base_url, model=self.model, available=False)

    def health(self, timeout: float = 3.0) -> LLMStats:
        try:
            r = httpx.get(f"{self.base_url}/models", timeout=timeout)
            ok = r.status_code == 200
            self.last_stats = LLMStats(base_url=self.base_url, model=self.model, available=ok,
                                        error="" if ok else f"HTTP {r.status_code}")
        except Exception as e:  # noqa: BLE001 — any transport error means unavailable
            self.last_stats = LLMStats(base_url=self.base_url, model=self.model, available=False,
                                       error=str(e)[:200])
        return self.last_stats

    def chat(self, system: str, user: str, max_tokens: int = 360, temperature: float = 0.15) -> str:
        import time

        t0 = time.time()
        payload = {
            "model": self.model,
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": user}],
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": False,
        }
        try:
            r = httpx.post(f"{self.base_url}/chat/completions", json=payload, timeout=self.timeout)
        except Exception as e:  # noqa: BLE001
            raise LLMUnavailable(str(e)[:200]) from e
        if r.status_code != 200:
            raise LLMUnavailable(f"LLM HTTP {r.status_code}: {r.text[:200]}")
        data = r.json()
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError) as e:
            raise LLMUnavailable(f"malformed LLM response: {e}") from e
        usage = data.get("usage", {})
        self.last_stats = LLMStats(
            base_url=self.base_url, model=self.model, available=True,
            latency_ms=round((time.time() - t0) * 1000, 1),
            prompt_tokens=int(usage.get("prompt_tokens", 0)),
            completion_tokens=int(usage.get("completion_tokens", 0)),
        )
        return content.strip()


SYSTEM_PROMPT = (
    "You are an AML (anti-money-laundering) case analyst at MKBANK, Tashkent. "
    "You write investigation notes for a Level-2 compliance officer. "
    "RULES: Use ONLY facts from the numbered evidence list [E1], [E2] ... "
    "Never invent amounts, dates, names, ids or counts. "
    "Every number, date, name or count you state MUST carry its evidence id in square "
    "brackets at that point in the sentence, e.g. '\"avg inflow was 155.8 mln UZS [E4]\"'. "
    "Place each [E#] next to the fact it supports; only use ids that exist in the evidence list. "
    "Do not repeat the same fact in two sections. "
    "If evidence is insufficient, say so explicitly. "
    "Answer in English. Max 220 words."
)


PROMPT_EXAMPLE = (
    "FORMAT EXAMPLE (different case — ids and facts below are NOT from your case):\n"
    "EVIDENCE LIST\n"
    "[E1] Subject: Anna Y., person, account age 90 d, declared turnover 5 mln UZS/month\n"
    "[E2] total_in_90d = 210.0 mln UZS (score impact +12.0 pp)\n"
    "[E3] tx T014 2026-03-02 in 48.9 mln UZS from cp3 via p2p, memo='qarz'\n\n"
    "EXAMPLE NOTE:\n"
    "**SUMMARY**\n"
    "Anna Y. received 210.0 mln UZS in 90 days [E2], 42x her declared turnover [E1].\n"
    "One inflow of 48.9 mln UZS sits just under the 50 mln reporting threshold [E3].\n\n"
    "**TYPOLOGY**\n"
    "Evidence supports SC-01 (structuring) [E3]. Alternative: genuine trade payments — weak, "
    "memo is a vague loan word [E3].\n\n"
    "**KEY EVIDENCE**\n"
    "- Inflow 210.0 mln UZS vs declared 5 mln/month [E1][E2]\n"
    "- Near-threshold 48.9 mln inflow [E3]\n\n"
    "**NEXT STEPS**\n"
    "- Pull sender history for cp3 [E3]\n"
    "- Request turnover declaration documents [E1]\n\n"
    "Note how every fact carries its [E#] right where it is used. Write YOUR case the same way.\n"
)


def build_user_prompt(case_brief: str, evidence_lines: list[str]) -> str:
    ev = "\n".join(evidence_lines)
    return (
        f"CASE BRIEF\n{case_brief}\n\n"
        f"EVIDENCE LIST\n{ev}\n\n"
        "Write the investigation note with exactly these 4 sections:\n"
        "1) SUMMARY — 3 sentences max.\n"
        "2) TYPOLOGY — which scenario codes (SC-01..SC-06) are supported by evidence, "
        "and which alternative explanations remain.\n"
        "3) KEY EVIDENCE — 4 to 6 bullets, each ending with [E#] citations.\n"
        "4) NEXT STEPS — 2 to 3 concrete actions for the analyst, with [E#] where applicable.\n"
        "Keep every section short. Do not repeat facts. Every number must keep its [E#].\n\n"
        + PROMPT_EXAMPLE
    )
