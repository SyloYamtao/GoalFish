"""
Graphiti 图谱记忆更新服务。
"""

from __future__ import annotations

import threading
import time
from datetime import datetime
from queue import Empty, Queue
from typing import Any, Dict, List, Optional

from graphiti_core.nodes import EpisodeType

from ..utils.logger import get_logger
from ..utils.locale import get_locale, set_locale
from .graphiti_client import execute_graphiti, run_async
from .graphiti_metadata import load_graph_metadata
from .graphiti_ontology import build_graphiti_entity_types
from .graph_models import AgentActivity

logger = get_logger("goalfish.graphiti_memory_updater")


class GraphitiGraphMemoryUpdater:
    BATCH_SIZE = 5
    SEND_INTERVAL = 0.5
    MAX_RETRIES = 3
    RETRY_DELAY = 2
    PLATFORM_DISPLAY_NAMES = {"twitter": "世界1", "reddit": "世界2"}

    def __init__(self, graph_id: str):
        self.graph_id = graph_id
        self._activity_queue: Queue = Queue()
        self._platform_buffers: Dict[str, List[AgentActivity]] = {"twitter": [], "reddit": []}
        self._buffer_lock = threading.Lock()
        self._running = False
        self._worker_thread: Optional[threading.Thread] = None
        self._total_activities = 0
        self._total_sent = 0
        self._total_items_sent = 0
        self._failed_count = 0
        self._skipped_count = 0
        metadata = load_graph_metadata(graph_id)
        ontology = metadata.get("ontology") or {}
        self._entity_types = build_graphiti_entity_types(ontology) if ontology else None
        logger.info(f"GraphitiGraphMemoryUpdater 初始化完成: graph_id={graph_id}")

    def _get_platform_display_name(self, platform: str) -> str:
        return self.PLATFORM_DISPLAY_NAMES.get(platform.lower(), platform)

    def start(self):
        if self._running:
            return
        current_locale = get_locale()
        self._running = True
        self._worker_thread = threading.Thread(
            target=self._worker_loop,
            args=(current_locale,),
            daemon=True,
            name=f"GraphitiMemoryUpdater-{self.graph_id[:8]}",
        )
        self._worker_thread.start()

    def stop(self):
        self._running = False
        self._flush_remaining()
        if self._worker_thread and self._worker_thread.is_alive():
            self._worker_thread.join(timeout=10)

    def add_activity(self, activity: AgentActivity):
        if activity.action_type == "DO_NOTHING":
            self._skipped_count += 1
            return
        self._activity_queue.put(activity)
        self._total_activities += 1

    def add_activity_from_dict(self, data: Dict[str, Any], platform: str):
        if "event_type" in data:
            return
        self.add_activity(
            AgentActivity(
                platform=platform,
                agent_id=data.get("agent_id", 0),
                agent_name=data.get("agent_name", ""),
                action_type=data.get("action_type", ""),
                action_args=data.get("action_args", {}),
                round_num=data.get("round", 0),
                timestamp=data.get("timestamp", datetime.now().isoformat()),
            )
        )

    def _worker_loop(self, locale: str = "zh"):
        set_locale(locale)
        while self._running or not self._activity_queue.empty():
            try:
                try:
                    activity = self._activity_queue.get(timeout=1)
                    platform = activity.platform.lower()
                    with self._buffer_lock:
                        self._platform_buffers.setdefault(platform, []).append(activity)
                        if len(self._platform_buffers[platform]) >= self.BATCH_SIZE:
                            batch = self._platform_buffers[platform][: self.BATCH_SIZE]
                            self._platform_buffers[platform] = self._platform_buffers[platform][self.BATCH_SIZE :]
                            self._send_batch_activities(batch, platform)
                            time.sleep(self.SEND_INTERVAL)
                except Empty:
                    pass
            except Exception as e:
                logger.error(f"Graphiti 工作循环异常: {e}")
                time.sleep(1)

    def _send_batch_activities(self, activities: List[AgentActivity], platform: str):
        if not activities:
            return
        combined_text = "\n".join(activity.to_episode_text() for activity in activities)

        for attempt in range(self.MAX_RETRIES):
            try:
                async def _add(graphiti):
                    await graphiti.add_episode(
                        name=f"{self.graph_id}_{platform}_{datetime.now().timestamp()}",
                        episode_body=combined_text,
                        source_description=f"GoalFish {platform} simulation activity",
                        reference_time=datetime.now(),
                        source=EpisodeType.text,
                        group_id=self.graph_id,
                        entity_types=self._entity_types,
                    )

                run_async(execute_graphiti(_add))
                self._total_sent += 1
                self._total_items_sent += len(activities)
                logger.info(f"成功批量发送 {len(activities)} 条{self._get_platform_display_name(platform)}活动到 Graphiti {self.graph_id}")
                return
            except Exception as e:
                if attempt < self.MAX_RETRIES - 1:
                    logger.warning(f"批量发送到Graphiti失败 (尝试 {attempt + 1}/{self.MAX_RETRIES}): {e}")
                    time.sleep(self.RETRY_DELAY * (attempt + 1))
                else:
                    logger.error(f"批量发送到Graphiti失败，已重试{self.MAX_RETRIES}次: {e}")
                    self._failed_count += 1

    def _flush_remaining(self):
        while not self._activity_queue.empty():
            try:
                activity = self._activity_queue.get_nowait()
                self._platform_buffers.setdefault(activity.platform.lower(), []).append(activity)
            except Empty:
                break

        with self._buffer_lock:
            for platform, buffer in self._platform_buffers.items():
                if buffer:
                    self._send_batch_activities(buffer, platform)
            for platform in self._platform_buffers:
                self._platform_buffers[platform] = []

    def get_stats(self) -> Dict[str, Any]:
        with self._buffer_lock:
            buffer_sizes = {platform: len(buffer) for platform, buffer in self._platform_buffers.items()}
        return {
            "graph_id": self.graph_id,
            "batch_size": self.BATCH_SIZE,
            "total_activities": self._total_activities,
            "batches_sent": self._total_sent,
            "items_sent": self._total_items_sent,
            "failed_count": self._failed_count,
            "skipped_count": self._skipped_count,
            "queue_size": self._activity_queue.qsize(),
            "buffer_sizes": buffer_sizes,
            "running": self._running,
        }


class GraphitiGraphMemoryManager:
    _updaters: Dict[str, GraphitiGraphMemoryUpdater] = {}
    _lock = threading.Lock()
    _stop_all_done = False

    @classmethod
    def create_updater(cls, simulation_id: str, graph_id: str) -> GraphitiGraphMemoryUpdater:
        with cls._lock:
            if simulation_id in cls._updaters:
                cls._updaters[simulation_id].stop()
            updater = GraphitiGraphMemoryUpdater(graph_id)
            updater.start()
            cls._updaters[simulation_id] = updater
            return updater

    @classmethod
    def get_updater(cls, simulation_id: str) -> Optional[GraphitiGraphMemoryUpdater]:
        return cls._updaters.get(simulation_id)

    @classmethod
    def stop_updater(cls, simulation_id: str):
        with cls._lock:
            if simulation_id in cls._updaters:
                cls._updaters[simulation_id].stop()
                del cls._updaters[simulation_id]

    @classmethod
    def stop_all(cls):
        if cls._stop_all_done:
            return
        cls._stop_all_done = True
        with cls._lock:
            for simulation_id, updater in list(cls._updaters.items()):
                try:
                    updater.stop()
                except Exception as e:
                    logger.error(f"停止Graphiti图谱记忆更新器失败: {simulation_id}, {e}")
            cls._updaters.clear()
