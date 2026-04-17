from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Any

import pandas as pd


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@dataclass
class ActionPlan:
    id: str
    store_id: str
    week_id: str
    title: str
    detail: str
    status: str
    created_at: str
    updated_at: str


class ActionPlanStore:
    def __init__(self, path: str):
        self.path = path

    def _default_payload(self) -> dict[str, Any]:
        return {"version": 1, "saved_at": _utc_now_iso(), "items": []}

    def load_all(self) -> list[ActionPlan]:
        if not os.path.exists(self.path):
            return []
        with open(self.path, "r", encoding="utf-8") as f:
            data = json.load(f)
        items = []
        for row in data.get("items", []):
            items.append(
                ActionPlan(
                    id=str(row["id"]),
                    store_id=str(row["store_id"]),
                    week_id=str(row["week_id"]),
                    title=str(row.get("title", "")),
                    detail=str(row.get("detail", "")),
                    status=str(row.get("status", "待办")),
                    created_at=str(row.get("created_at", "")),
                    updated_at=str(row.get("updated_at", "")),
                )
            )
        return items

    def save_all(self, items: list[ActionPlan]) -> tuple[bool, str]:
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            payload = {
                "version": 1,
                "saved_at": _utc_now_iso(),
                "items": [asdict(i) for i in items],
            }
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
            return True, ""
        except Exception as exc:
            return False, str(exc)

    def upsert(
        self,
        items: list[ActionPlan],
        *,
        store_id: str,
        week_id: str,
        title: str,
        detail: str,
        status: str,
        edit_id: str | None,
    ) -> list[ActionPlan]:
        now = _utc_now_iso()
        if edit_id:
            out: list[ActionPlan] = []
            for it in items:
                if it.id == edit_id:
                    out.append(
                        ActionPlan(
                            id=it.id,
                            store_id=store_id,
                            week_id=week_id,
                            title=title.strip(),
                            detail=detail.strip(),
                            status=status.strip(),
                            created_at=it.created_at,
                            updated_at=now,
                        )
                    )
                else:
                    out.append(it)
            return out
        new = ActionPlan(
            id=str(uuid.uuid4()),
            store_id=store_id,
            week_id=week_id,
            title=title.strip(),
            detail=detail.strip(),
            status=status.strip(),
            created_at=now,
            updated_at=now,
        )
        return items + [new]

    def delete(self, items: list[ActionPlan], delete_id: str) -> list[ActionPlan]:
        return [i for i in items if i.id != delete_id]

    def to_dataframe(self, items: list[ActionPlan], store_id: str | None, week_id: str | None) -> pd.DataFrame:
        rows = [asdict(i) for i in items]
        if not rows:
            return pd.DataFrame(columns=list(ActionPlan.__dataclass_fields__.keys()))
        df = pd.DataFrame(rows)
        if store_id:
            df = df[df["store_id"] == store_id]
        if week_id:
            df = df[df["week_id"] == week_id]
        return df.sort_values("updated_at", ascending=False).reset_index(drop=True)
