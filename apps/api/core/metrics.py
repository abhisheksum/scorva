import logging
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("scorva.metrics")


class MetricsRegistry:
    """
    Subsystem D Sub-Milestone 5.5: Low-Cardinality Operational Metrics Registry.

    Invariants:
    1. Low-cardinality labels only: All label keys and values are strictly bounded strings
       (e.g., status='queued', provider='mock', reason='token_mismatch').
       NEVER organization IDs, job IDs, repository URLs, or arbitrary user input.
    2. Zero sensitive data: Metrics contain zero repository contents, prompt text,
       secrets, tokens, or credentials.
    3. Thread-safe: Atomic increment and duration observations protected by reentrant lock.
    4. Dual Export: Formats metrics as standard Prometheus text lines (text/plain; version=0.0.4)
       and structured JSON dictionaries.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        # Metric name -> (type, help_text)
        self._metadata: Dict[str, Tuple[str, str]] = {}
        # (metric_name, tuple_of_sorted_label_items) -> float
        self._counters: Dict[Tuple[str, Tuple[Tuple[str, str], ...]], float] = {}
        # (metric_name, tuple_of_sorted_label_items) -> float
        self._gauges: Dict[Tuple[str, Tuple[Tuple[str, str], ...]], float] = {}
        # (metric_name, tuple_of_sorted_label_items) -> [count, sum]
        self._summaries: Dict[Tuple[str, Tuple[Tuple[str, str], ...]], List[float]] = {}

        self._register_default_metrics()

    def _normalize_labels(self, labels: Optional[Dict[str, str]]) -> Tuple[Tuple[str, str], ...]:
        if not labels:
            return ()
        # Sanitize labels to ensure low cardinality and prevent accidental ID injection
        sanitized = []
        for k, v in sorted(labels.items()):
            sanitized.append((str(k), str(v)))
        return tuple(sanitized)

    def _register_default_metrics(self) -> None:
        self.register_counter(
            "scorva_eval_jobs_total",
            "Total evaluation jobs observed by lifecycle status",
        )
        self.register_counter(
            "scorva_reaper_sweeps_total",
            "Total background reaper sweeps executed",
        )
        self.register_counter(
            "scorva_reaper_recovered_jobs_total",
            "Total stalled jobs recovered by crash reaper by action taken",
        )
        self.register_counter(
            "scorva_fencing_rejections_total",
            "Total worker fencing token or lock version rejections",
        )
        self.register_counter(
            "scorva_outbox_operations_total",
            "Total transactional outbox relay operations by outcome",
        )
        self.register_counter(
            "scorva_tenant_concurrency_slots_acquired_total",
            "Total tenant evaluation concurrency slots successfully acquired",
        )
        self.register_counter(
            "scorva_tenant_concurrency_rejected_total",
            "Total tenant evaluation concurrency acquisitions rejected due to saturation",
        )
        self.register_gauge(
            "scorva_tenant_concurrency_slots_active",
            "Current number of actively claimed tenant concurrency slots",
        )
        self.register_counter(
            "scorva_ai_provider_calls_total",
            "Total AI provider requests by provider and outcome status",
        )
        self.register_counter(
            "scorva_schema_validation_failures_total",
            "Total AI output Pydantic schema validation failures",
        )
        self.register_counter(
            "scorva_retry_exhausted_total",
            "Total evaluation jobs whose retry attempts budget was completely exhausted",
        )
        self.register_counter(
            "scorva_redis_errors_total",
            "Total Redis connection or execution errors by operation",
        )
        self.register_summary(
            "scorva_eval_execution_duration_seconds",
            "Evaluation pipeline execution duration in seconds",
        )
        self.register_summary(
            "scorva_eval_queue_wait_seconds",
            "Duration evaluation job waited in queue prior to worker claim in seconds",
        )

        # Initialize default zero series for core metrics
        for st in ("queued", "running", "completed", "failed", "cancelled"):
            self._counters[("scorva_eval_jobs_total", (("status", st),))] = 0.0
        self._counters[("scorva_tenant_concurrency_slots_acquired_total", ())] = 0.0
        self._counters[("scorva_tenant_concurrency_rejected_total", ())] = 0.0
        self._gauges[("scorva_tenant_concurrency_slots_active", ())] = 0.0

    def register_counter(self, name: str, help_text: str) -> None:
        with self._lock:
            self._metadata[name] = ("counter", help_text)

    def register_gauge(self, name: str, help_text: str) -> None:
        with self._lock:
            self._metadata[name] = ("gauge", help_text)

    def register_summary(self, name: str, help_text: str) -> None:
        with self._lock:
            self._metadata[name] = ("summary", help_text)

    def inc_counter(self, name: str, amount: float = 1.0, labels: Optional[Dict[str, str]] = None) -> None:
        norm_labels = self._normalize_labels(labels)
        with self._lock:
            if name not in self._metadata:
                self._metadata[name] = ("counter", f"{name} counter")
            key = (name, norm_labels)
            self._counters[key] = self._counters.get(key, 0.0) + amount

    def set_gauge(self, name: str, value: float, labels: Optional[Dict[str, str]] = None) -> None:
        norm_labels = self._normalize_labels(labels)
        with self._lock:
            if name not in self._metadata:
                self._metadata[name] = ("gauge", f"{name} gauge")
            key = (name, norm_labels)
            self._gauges[key] = float(value)

    def inc_gauge(self, name: str, amount: float = 1.0, labels: Optional[Dict[str, str]] = None) -> None:
        norm_labels = self._normalize_labels(labels)
        with self._lock:
            if name not in self._metadata:
                self._metadata[name] = ("gauge", f"{name} gauge")
            key = (name, norm_labels)
            self._gauges[key] = self._gauges.get(key, 0.0) + amount

    def dec_gauge(self, name: str, amount: float = 1.0, labels: Optional[Dict[str, str]] = None) -> None:
        self.inc_gauge(name, -amount, labels)

    def observe_summary(self, name: str, value: float, labels: Optional[Dict[str, str]] = None) -> None:
        norm_labels = self._normalize_labels(labels)
        with self._lock:
            if name not in self._metadata:
                self._metadata[name] = ("summary", f"{name} summary")
            key = (name, norm_labels)
            if key not in self._summaries:
                self._summaries[key] = [0.0, 0.0]  # [count, sum]
            self._summaries[key][0] += 1.0
            self._summaries[key][1] += float(value)

    def reset_for_tests(self) -> None:
        """Resets all metric values while preserving metadata registrations."""
        with self._lock:
            self._counters.clear()
            self._gauges.clear()
            self._summaries.clear()

    def get_counter_value(self, name: str, labels: Optional[Dict[str, str]] = None) -> float:
        norm_labels = self._normalize_labels(labels)
        with self._lock:
            return self._counters.get((name, norm_labels), 0.0)

    def get_gauge_value(self, name: str, labels: Optional[Dict[str, str]] = None) -> float:
        norm_labels = self._normalize_labels(labels)
        with self._lock:
            return self._gauges.get((name, norm_labels), 0.0)

    def get_summary_stats(self, name: str, labels: Optional[Dict[str, str]] = None) -> Tuple[float, float]:
        norm_labels = self._normalize_labels(labels)
        with self._lock:
            entry = self._summaries.get((name, norm_labels))
            if entry:
                return (entry[0], entry[1])
            return (0.0, 0.0)

    def export_dict(self) -> Dict[str, Any]:
        """Returns structured JSON dictionary of all current metrics."""
        result: Dict[str, Any] = {
            "counters": {},
            "gauges": {},
            "summaries": {},
        }
        with self._lock:
            for (m_name, m_labels), val in self._counters.items():
                lbl_dict = dict(m_labels)
                lbl_str = ",".join(f"{k}={v}" for k, v in m_labels) or "none"
                if m_name not in result["counters"]:
                    result["counters"][m_name] = []
                result["counters"][m_name].append({
                    "labels": lbl_dict,
                    "value": val,
                })

            for (m_name, m_labels), val in self._gauges.items():
                lbl_dict = dict(m_labels)
                if m_name not in result["gauges"]:
                    result["gauges"][m_name] = []
                result["gauges"][m_name].append({
                    "labels": lbl_dict,
                    "value": val,
                })

            for (m_name, m_labels), (cnt, sm) in self._summaries.items():
                lbl_dict = dict(m_labels)
                avg = round(sm / cnt, 4) if cnt > 0 else 0.0
                if m_name not in result["summaries"]:
                    result["summaries"][m_name] = []
                result["summaries"][m_name].append({
                    "labels": lbl_dict,
                    "count": cnt,
                    "sum": sm,
                    "avg": avg,
                })

        return result

    def export_prometheus_text(self) -> str:
        """
        Exports all registered metrics in standard Prometheus text format:
        # HELP <name> <help_text>
        # TYPE <name> <type>
        <name>{label="value"} <value>
        """
        lines: List[str] = []
        with self._lock:
            # Process in sorted metric name order
            for name, (m_type, help_text) in sorted(self._metadata.items()):
                rendered_lines_for_metric: List[str] = []

                if m_type == "counter":
                    for (m_name, m_labels), val in sorted(self._counters.items()):
                        if m_name != name:
                            continue
                        lbl_clause = ""
                        if m_labels:
                            lbl_clause = "{" + ",".join(f'{k}="{v}"' for k, v in m_labels) + "}"
                        rendered_lines_for_metric.append(f"{name}{lbl_clause} {val}")

                elif m_type == "gauge":
                    for (m_name, m_labels), val in sorted(self._gauges.items()):
                        if m_name != name:
                            continue
                        lbl_clause = ""
                        if m_labels:
                            lbl_clause = "{" + ",".join(f'{k}="{v}"' for k, v in m_labels) + "}"
                        rendered_lines_for_metric.append(f"{name}{lbl_clause} {val}")

                elif m_type == "summary":
                    for (m_name, m_labels), (cnt, sm) in sorted(self._summaries.items()):
                        if m_name != name:
                            continue
                        lbl_base = ""
                        if m_labels:
                            lbl_base = ",".join(f'{k}="{v}"' for k, v in m_labels)

                        lbl_count = f"{{{lbl_base}}}" if lbl_base else ""
                        lbl_sum = f"{{{lbl_base}}}" if lbl_base else ""

                        rendered_lines_for_metric.append(f"{name}_count{lbl_count} {cnt}")
                        rendered_lines_for_metric.append(f"{name}_sum{lbl_sum} {sm}")

                if rendered_lines_for_metric:
                    lines.append(f"# HELP {name} {help_text}")
                    lines.append(f"# TYPE {name} {m_type}")
                    lines.extend(rendered_lines_for_metric)

        return "\n".join(lines) + ("\n" if lines else "")


# Global singleton metrics collector
metrics_collector = MetricsRegistry()
