"""
Metrics and Monitoring for DeepanCode.
Collects performance metrics, error rates, and system health data.
"""

import os
import time
import json
import logging
import threading
import platform
from pathlib import Path
from typing import Dict, Any, List, Optional
from collections import defaultdict
from datetime import datetime, timedelta

logger = logging.getLogger("deepans_code.metrics")

METRICS_DIR = Path.home() / ".deepans-code" / "metrics"
METRICS_DIR.mkdir(parents=True, exist_ok=True)


class MetricsCollector:
    """Collects and stores application metrics."""

    def __init__(self):
        self._lock = threading.Lock()
        self._counters = defaultdict(int)
        self._gauges = {}
        self._histories = defaultdict(list)
        self._start_time = time.time()
        self._request_count = 0
        self._error_count = 0
        self._total_latency = 0.0
        self._tool_calls = defaultdict(lambda: {"count": 0, "errors": 0, "total_time": 0.0})
        self._provider_stats = defaultdict(lambda: {"requests": 0, "errors": 0, "latency": 0.0})
        self._session_start = datetime.now()

    def _histogram_unlocked(self, name: str, value: float):
        self._histories[name].append(value)
        if len(self._histories[name]) > 1000:
            self._histories[name] = self._histories[name][-500:]

    def increment(self, name: str, value: int = 1):
        with self._lock:
            self._counters[name] += value

    def gauge(self, name: str, value: Any):
        with self._lock:
            self._gauges[name] = value

    def histogram(self, name: str, value: float):
        with self._lock:
            self._histogram_unlocked(name, value)

    def record_request(self, provider: str, latency: float, success: bool, tokens: int = 0):
        with self._lock:
            self._request_count += 1
            self._total_latency += latency
            if not success:
                self._error_count += 1
            self._provider_stats[provider]["requests"] += 1
            self._provider_stats[provider]["latency"] += latency
            if not success:
                self._provider_stats[provider]["errors"] += 1
            self._histogram_unlocked("request_latency", latency)
            self._histogram_unlocked("tokens_per_request", tokens)

    def record_tool_call(self, tool_name: str, latency: float, success: bool):
        with self._lock:
            self._tool_calls[tool_name]["count"] += 1
            self._tool_calls[tool_name]["total_time"] += latency
            if not success:
                self._tool_calls[tool_name]["errors"] += 1
            self._histogram_unlocked(f"tool_{tool_name}_latency", latency)

    def get_summary(self) -> Dict[str, Any]:
        with self._lock:
            uptime = time.time() - self._start_time
            avg_latency = self._total_latency / max(self._request_count, 1)
            error_rate = self._error_count / max(self._request_count, 1)

            return {
                "uptime_seconds": round(uptime, 1),
                "uptime_human": str(timedelta(seconds=int(uptime))),
                "session_start": self._session_start.isoformat(),
                "total_requests": self._request_count,
                "total_errors": self._error_count,
                "error_rate": round(error_rate, 4),
                "avg_latency_ms": round(avg_latency * 1000, 1),
                "total_latency_ms": round(self._total_latency * 1000, 1),
                "tool_calls": dict(self._tool_calls),
                "provider_stats": dict(self._provider_stats),
                "counters": dict(self._counters),
                "gauges": dict(self._gauges),
            }

    def get_health(self) -> Dict[str, Any]:
        try:
            import psutil
            cpu = psutil.cpu_percent(interval=0.1)
            memory = psutil.virtual_memory()
            disk = psutil.disk_usage("/")
            return {
                "status": "healthy",
                "cpu_percent": cpu,
                "memory_percent": memory.percent,
                "memory_used_mb": round(memory.used / (1024 * 1024), 1),
                "memory_total_mb": round(memory.total / (1024 * 1024), 1),
                "disk_percent": disk.percent,
                "disk_used_gb": round(disk.used / (1024 ** 3), 2),
                "disk_total_gb": round(disk.total / (1024 ** 3), 2),
                "platform": platform.system(),
                "python_version": platform.python_version(),
            }
        except ImportError:
            return {
                "status": "healthy",
                "platform": platform.system(),
                "python_version": platform.python_version(),
                "cpu_count": os.cpu_count(),
            }

    def save_snapshot(self):
        try:
            snapshot = self.get_summary()
            snapshot["timestamp"] = datetime.now().isoformat()
            filename = METRICS_DIR / f"snapshot_{int(time.time())}.json"
            with open(filename, "w", encoding="utf-8") as f:
                json.dump(snapshot, f, indent=2, default=str)
            self._cleanup_old_snapshots()
        except Exception as e:
            logger.error(f"Failed to save metrics snapshot: {e}")

    def _cleanup_old_snapshots(self, keep: int = 24):
        files = sorted(METRICS_DIR.glob("snapshot_*.json"), key=lambda f: f.stat().st_mtime)
        for f in files[:-keep]:
            f.unlink(missing_ok=True)

    def format_dashboard(self) -> str:
        summary = self.get_summary()
        health = self.get_health()

        lines = [
            "=" * 60,
            "  DeepanCode Metrics Dashboard",
            "=" * 60,
            "",
            f"  Uptime:      {summary['uptime_human']}",
            f"  Requests:    {summary['total_requests']}",
            f"  Errors:      {summary['total_errors']} ({summary['error_rate']*100:.1f}%)",
            f"  Avg Latency: {summary['avg_latency_ms']:.0f}ms",
            "",
            "  Provider Stats:",
        ]
        for prov, stats in summary.get("provider_stats", {}).items():
            avg = stats["latency"] / max(stats["requests"], 1) * 1000
            lines.append(f"    {prov}: {stats['requests']} reqs, {stats['errors']} errors, {avg:.0f}ms avg")

        lines.append("")
        lines.append("  Tool Usage:")
        for tool, stats in sorted(summary.get("tool_calls", {}).items(), key=lambda x: x[1]["count"], reverse=True)[:10]:
            avg = stats["total_time"] / max(stats["count"], 1) * 1000
            lines.append(f"    {tool}: {stats['count']} calls, {stats['errors']} errors, {avg:.0f}ms avg")

        if health.get("cpu_percent") is not None:
            lines.extend([
                "",
                "  System Health:",
                f"    CPU:     {health['cpu_percent']:.1f}%",
                f"    Memory:  {health.get('memory_used_mb', '?')}/{health.get('memory_total_mb', '?')} MB ({health.get('memory_percent', '?')}%)",
                f"    Disk:    {health.get('disk_used_gb', '?')}/{health.get('disk_total_gb', '?')} GB ({health.get('disk_percent', '?')}%)",
            ])

        lines.extend(["", "=" * 60])
        return "\n".join(lines)


metrics = MetricsCollector()
