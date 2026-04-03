"""
upload_queue.py — 업로드 대기/재시도 큐 (JSONL 기반 영속 저장)

각 항목 구조:
    {"id": "<uuid>", "status": "pending|done|failed",
     "queued_at": "<ISO8601>", "record": {<posture record>}}

• pending  : 업로드 미완료 (초기값 + 재시도 대상)
• done     : 업로드 성공
• failed   : 업로드 실패 (retry_failed() 로 pending 으로 되돌릴 수 있음)
"""
import json
import os
import uuid
from datetime import datetime


class UploadQueue:
    def __init__(self, queue_path: str):
        os.makedirs(os.path.dirname(queue_path), exist_ok=True)
        self.queue_path = queue_path

    # ── 쓰기 ──────────────────────────────────────────────────────────────────

    def enqueue(self, record: dict):
        """레코드를 pending 상태로 큐 파일에 append."""
        entry = {
            "id": str(uuid.uuid4()),
            "status": "pending",
            "queued_at": datetime.now().isoformat(),
            "record": record,
        }
        try:
            with open(self.queue_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception as e:
            print(f"[Queue] enqueue 실패: {e}")

    # ── 읽기 ──────────────────────────────────────────────────────────────────

    def get_pending(self) -> list[dict]:
        """status == 'pending' 인 항목 목록 반환."""
        return [e for e in self._read_all() if e.get("status") == "pending"]

    # ── 상태 업데이트 ─────────────────────────────────────────────────────────

    def mark_done(self, entry_ids: list[str]):
        """지정된 id 들의 status 를 'done' 으로 갱신."""
        self._update_status(set(entry_ids), "done")

    def mark_failed(self, entry_ids: list[str]):
        """지정된 id 들의 status 를 'failed' 로 갱신."""
        self._update_status(set(entry_ids), "failed")

    def retry_failed(self):
        """'failed' 항목을 'pending' 으로 되돌려 재시도 대상에 포함."""
        if not os.path.exists(self.queue_path):
            return
        entries = self._read_all()
        changed = False
        for e in entries:
            if e.get("status") == "failed":
                e["status"] = "pending"
                changed = True
        if changed:
            self._write_all(entries)

    # ── 내부 헬퍼 ─────────────────────────────────────────────────────────────

    def _read_all(self) -> list[dict]:
        if not os.path.exists(self.queue_path):
            return []
        entries = []
        with open(self.queue_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return entries

    def _write_all(self, entries: list[dict]):
        try:
            lines = [json.dumps(e, ensure_ascii=False) for e in entries]
            with open(self.queue_path, "w", encoding="utf-8") as f:
                f.write("\n".join(lines) + ("\n" if lines else ""))
        except Exception as e:
            print(f"[Queue] 파일 쓰기 실패: {e}")

    def _update_status(self, id_set: set[str], new_status: str):
        entries = self._read_all()
        changed = False
        for e in entries:
            if e.get("id") in id_set:
                e["status"] = new_status
                changed = True
        if changed:
            self._write_all(entries)
