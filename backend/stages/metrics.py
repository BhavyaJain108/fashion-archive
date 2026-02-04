"""
Metrics Module
==============

Tabular metrics tracking for LLM costs and latency across pipeline phases.
Generates human-readable metrics.txt files per brand.
"""

from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any
import json

# Claude Sonnet 4 pricing (per 1M tokens)
INPUT_COST_PER_M = 3.0   # $3 per 1M input tokens
OUTPUT_COST_PER_M = 15.0  # $15 per 1M output tokens


def calculate_cost(input_tokens: int, output_tokens: int) -> float:
    """Calculate cost in USD from token counts."""
    input_cost = (input_tokens / 1_000_000) * INPUT_COST_PER_M
    output_cost = (output_tokens / 1_000_000) * OUTPUT_COST_PER_M
    return input_cost + output_cost


class LLMOperationTracker:
    """
    Tracks LLM operations with named operation types.

    Usage:
        tracker = LLMOperationTracker()

        # Before LLM call
        snapshot = tracker.snapshot()

        # ... make LLM call ...

        # After LLM call (with usage from response)
        tracker.record_operation("lineage_filtering", usage={
            "input_tokens": 1500,
            "output_tokens": 400
        })
    """

    def __init__(self):
        self.operations: List[Dict] = []
        self._current_snapshot = None

    def snapshot(self) -> Dict:
        """Capture current state (for delta tracking with LLMHandler)."""
        try:
            # Try to import LLMHandler for snapshot
            import sys
            sys.path.insert(0, str(Path(__file__).parent.parent / "scraper"))
            from llm_handler import LLMHandler
            return LLMHandler.get_snapshot()
        except ImportError:
            return {"input_tokens": 0, "output_tokens": 0, "call_count": 0}

    def record_operation(self, name: str, usage: Optional[Dict] = None,
                        snapshot_before: Optional[Dict] = None,
                        snapshot_after: Optional[Dict] = None):
        """
        Record an LLM operation.

        Args:
            name: Operation name (e.g., "lineage_filtering", "pagination_detection")
            usage: Direct usage dict with input_tokens, output_tokens
            snapshot_before: Snapshot taken before operation (for delta calc)
            snapshot_after: Snapshot taken after operation (for delta calc)
        """
        if usage:
            # Direct usage provided
            input_tokens = usage.get("input_tokens", 0)
            output_tokens = usage.get("output_tokens", 0)
        elif snapshot_before and snapshot_after:
            # Calculate delta from snapshots
            input_tokens = snapshot_after.get("input_tokens", 0) - snapshot_before.get("input_tokens", 0)
            output_tokens = snapshot_after.get("output_tokens", 0) - snapshot_before.get("output_tokens", 0)
        else:
            input_tokens = 0
            output_tokens = 0

        cost = calculate_cost(input_tokens, output_tokens)

        # Find existing operation or create new
        existing = next((op for op in self.operations if op["name"] == name), None)
        if existing:
            existing["calls"] += 1
            existing["input_tokens"] += input_tokens
            existing["output_tokens"] += output_tokens
            existing["cost"] += cost
        else:
            self.operations.append({
                "name": name,
                "calls": 1,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "cost": cost
            })

    def get_operations(self) -> List[Dict]:
        """Get all recorded operations."""
        return self.operations

    def get_summary(self) -> Dict:
        """Get totals across all operations."""
        total_calls = sum(op["calls"] for op in self.operations)
        total_input = sum(op["input_tokens"] for op in self.operations)
        total_output = sum(op["output_tokens"] for op in self.operations)
        total_cost = sum(op["cost"] for op in self.operations)

        return {
            "calls": total_calls,
            "input_tokens": total_input,
            "output_tokens": total_output,
            "cost": total_cost
        }


def format_llm_table(operations: List[Dict]) -> str:
    """Format LLM operations as a table."""
    lines = []
    lines.append("LLM OPERATIONS:")
    lines.append("  Operation                  Calls   Input Tok   Output Tok   Cost USD")
    lines.append("  -------------------------  ------  ----------  -----------  ---------")

    for op in operations:
        name = op["name"][:25].ljust(25)
        calls = str(op["calls"]).rjust(6)
        input_tok = str(op["input_tokens"]).rjust(10)
        output_tok = str(op["output_tokens"]).rjust(11)
        cost = f"${op['cost']:.4f}".rjust(9)
        lines.append(f"  {name}  {calls}  {input_tok}  {output_tok}  {cost}")

    # Add totals row
    lines.append("  -------------------------  ------  ----------  -----------  ---------")
    total_calls = sum(op["calls"] for op in operations)
    total_input = sum(op["input_tokens"] for op in operations)
    total_output = sum(op["output_tokens"] for op in operations)
    total_cost = sum(op["cost"] for op in operations)

    lines.append(f"  {'TOTAL'.ljust(25)}  {str(total_calls).rjust(6)}  {str(total_input).rjust(10)}  {str(total_output).rjust(11)}  ${total_cost:.4f}".rjust(9))

    return "\n".join(lines)


def format_category_table(categories: List[Dict]) -> str:
    """Format per-category breakdown as a table."""
    lines = []
    lines.append("")
    lines.append("PER-CATEGORY BREAKDOWN:")
    lines.append("  Category                         Duration   Products   LLM Calls   LLM Cost")
    lines.append("  -------------------------------  ---------  ---------  ----------  ---------")

    for cat in categories:
        name = cat["name"][:31].ljust(31)
        duration = f"{cat['duration']:.1f}s".rjust(9)
        products = str(cat["products"]).rjust(9)
        llm_calls = str(cat["llm_calls"]).rjust(10)
        llm_cost = f"${cat['llm_cost']:.4f}".rjust(9)
        lines.append(f"  {name}  {duration}  {products}  {llm_calls}  {llm_cost}")

    return "\n".join(lines)


def format_stage_section(stage_num: int, stage_name: str, data: Dict) -> str:
    """
    Format a complete stage section.

    Args:
        stage_num: Stage number (1, 2, or 3)
        stage_name: Stage name (e.g., "NAVIGATION", "URL EXTRACTION")
        data: Stage data including:
            - run_time: datetime
            - duration: float (seconds)
            - extra_fields: dict of additional header fields
            - operations: list of LLM operations
            - categories: optional list of per-category data (Stage 2)
            - latency_breakdown: optional dict for Stage 3
    """
    lines = []
    lines.append("=" * 80)
    lines.append("")
    lines.append(f"STAGE {stage_num}: {stage_name}")
    lines.append("-" * 80)

    # Header fields
    run_time = data.get("run_time", datetime.now())
    if isinstance(run_time, str):
        lines.append(f"Run Time:        {run_time}")
    else:
        lines.append(f"Run Time:        {run_time.strftime('%Y-%m-%d %H:%M:%S')}")

    duration = data.get("duration", 0)
    lines.append(f"Duration:        {duration:.1f}s")

    # Extra fields (method, categories, products, etc.)
    for key, value in data.get("extra_fields", {}).items():
        lines.append(f"{key + ':':17}{value}")

    lines.append("")

    # LLM operations table
    operations = data.get("operations", [])
    if operations:
        lines.append(format_llm_table(operations))
    else:
        lines.append("LLM OPERATIONS: None")

    # Per-category breakdown (Stage 2)
    categories = data.get("categories", [])
    if categories:
        lines.append(format_category_table(categories))

    # Latency breakdown (Stage 3)
    latency = data.get("latency_breakdown", {})
    if latency:
        lines.append("")
        lines.append("LATENCY BREAKDOWN:")
        lines.append("  Phase                      Duration")
        lines.append("  -------------------------  ---------")
        for phase, dur in latency.items():
            lines.append(f"  {phase.ljust(25)}  {dur:.1f}s".rjust(9))

    lines.append("")
    return "\n".join(lines)


def format_totals(stages: Dict[str, Dict]) -> str:
    """Format the totals section from all stages."""
    lines = []
    lines.append("=" * 80)
    lines.append("")
    lines.append("TOTALS")
    lines.append("-" * 80)

    total_duration = 0
    total_calls = 0
    total_input = 0
    total_output = 0
    total_cost = 0
    total_products = 0

    for stage_data in stages.values():
        total_duration += stage_data.get("duration", 0)
        summary = stage_data.get("summary", {})
        total_calls += summary.get("calls", 0)
        total_input += summary.get("input_tokens", 0)
        total_output += summary.get("output_tokens", 0)
        total_cost += summary.get("cost", 0)
        total_products = max(total_products, stage_data.get("products", 0))

    minutes = total_duration / 60
    cost_per_product = total_cost / total_products if total_products > 0 else 0

    lines.append("  Metric                           Value")
    lines.append("  -------------------------------  ------------------")
    lines.append(f"  {'Total Duration'.ljust(31)}  {total_duration:.1f}s ({minutes:.1f} min)")
    lines.append(f"  {'Total LLM Calls'.ljust(31)}  {total_calls}")
    lines.append(f"  {'Total Input Tokens'.ljust(31)}  {total_input:,}")
    lines.append(f"  {'Total Output Tokens'.ljust(31)}  {total_output:,}")
    lines.append(f"  {'Total LLM Cost'.ljust(31)}  ${total_cost:.4f}")
    lines.append(f"  {'Cost per Product'.ljust(31)}  ${cost_per_product:.4f}")
    lines.append("=" * 80)

    return "\n".join(lines)


def format_metrics_file(domain: str, stages: Dict[str, Dict]) -> str:
    """
    Format complete metrics file content.

    Args:
        domain: Brand domain
        stages: Dict mapping stage names to stage data
    """
    lines = []
    lines.append("=" * 80)
    lines.append(f"PIPELINE METRICS: {domain}")
    lines.append(f"Last Updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    # Add each stage section
    stage_order = [
        ("stage_1", 1, "NAVIGATION"),
        ("stage_2", 2, "URL EXTRACTION"),
        ("stage_3", 3, "PRODUCT EXTRACTION")
    ]

    for key, num, name in stage_order:
        if key in stages:
            lines.append(format_stage_section(num, name, stages[key]))

    # Add totals
    lines.append(format_totals(stages))

    return "\n".join(lines)


def load_metrics(domain: str) -> Dict:
    """
    Load existing metrics data for a domain.

    Returns parsed metrics as a dict, or empty dict if no file exists.
    """
    from stages.storage import ensure_domain_dir

    metrics_file = ensure_domain_dir(domain) / "metrics.json"
    if metrics_file.exists():
        try:
            with open(metrics_file, 'r') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return {}
    return {}


def save_metrics(domain: str, stages: Dict[str, Dict]):
    """
    Save metrics to both .txt (human readable) and .json (machine readable).
    """
    from stages.storage import ensure_domain_dir

    domain_dir = ensure_domain_dir(domain)

    # Save human-readable .txt
    txt_content = format_metrics_file(domain.replace('_', '.'), stages)
    txt_file = domain_dir / "metrics.txt"
    with open(txt_file, 'w') as f:
        f.write(txt_content)

    # Save machine-readable .json (for loading/updating)
    json_file = domain_dir / "metrics.json"
    with open(json_file, 'w') as f:
        json.dump(stages, f, indent=2, default=str)

    return txt_file, json_file


def update_stage_metrics(domain: str, stage_key: str, stage_data: Dict):
    """
    Update metrics for a specific stage, preserving other stages.

    Args:
        domain: Brand domain
        stage_key: Stage key (e.g., "stage_1", "stage_2", "stage_3")
        stage_data: Data for this stage
    """
    # Load existing metrics
    metrics = load_metrics(domain)

    # Update this stage
    metrics[stage_key] = stage_data

    # Save updated metrics
    txt_file, json_file = save_metrics(domain, metrics)

    return txt_file


def get_stage_metrics_from_tracker(stage: str) -> Dict:
    """
    Get metrics for a stage from the centralized LLMUsageTracker.

    Args:
        stage: Stage name (e.g., "navigation", "urls", "products")

    Returns:
        Dict with 'operations' and 'summary' keys
    """
    try:
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "scraper"))
        from llm_handler import LLMUsageTracker
        return LLMUsageTracker.get_stage_summary(stage)
    except ImportError:
        return {"operations": [], "summary": {"calls": 0, "input_tokens": 0, "output_tokens": 0, "cost": 0.0}}


def set_current_stage(stage: str):
    """
    Set the current stage for LLM tracking.

    Call this at the start of each pipeline stage.

    Args:
        stage: Stage name (e.g., "navigation", "urls", "products")
    """
    try:
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "scraper"))
        from llm_handler import LLMUsageTracker
        LLMUsageTracker.set_stage(stage)
    except ImportError:
        pass


def reset_all_tracking():
    """Reset all LLM tracking data. Call at the start of a new pipeline run."""
    try:
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "scraper"))
        from llm_handler import LLMUsageTracker
        LLMUsageTracker.reset_all()
    except ImportError:
        pass
