from __future__ import annotations

import os
import warnings
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict

import yaml

APPDATA = Path(os.getenv("APPDATA", Path.home() / "AppData" / "Roaming"))
LOCALAPPDATA = Path(os.getenv("LOCALAPPDATA", APPDATA.parent / "Local"))
PROGRAMDATA = Path(os.getenv("PROGRAMDATA", "C:/ProgramData"))
CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "config.yaml"


def _expand_path(value: str) -> Path:
    expanded = value.replace("%AppData%", str(APPDATA))
    expanded = os.path.expandvars(expanded)
    return Path(expanded).expanduser()


@dataclass
class PathsConfig:
    data_root: Path
    templates_root: Path
    pricebooks_root: Path
    work_root: Path
    database: Path
    vector_store: Path


@dataclass
class LoggingConfig:
    level: str
    file: Path


@dataclass
class ServerConfig:
    host: str
    port: int
    reload: bool
    workers: int


@dataclass
class IngestConfig:
    chunk_size: int
    chunk_overlap: int
    chunk_min_chars: int
    chunk_max_chars: int
    redact_sensitive: bool
    use_ocr: bool
    vector_backend: str
    default_collection: str
    ruleset: str
    tesseract_cmd: str | None
    telemetry_enabled: bool
    telemetry_log_path: Path


@dataclass
class ScopeConfig:
    csi_mapping: Path
    default_disciplines: list[str]
    llm_provider: str | None
    rule_sets: list[Path]


@dataclass
class MarginBreakdown:
    labor: float
    equipment: float
    subcontractor: float
    freight: float
    fuel: float
    contingency: float


@dataclass
class EstimationConfig:
    default_margin: MarginBreakdown
    price_providers: list[Dict[str, Any]]
    currency: str


@dataclass
class EngineerConfig:
    pump_curves_csv: Path
    hazen_williams_c: int


@dataclass
class ComplianceConfig:
    templates: Dict[str, Path]
    jurisdictions_dir: Path


@dataclass
class BidConfig:
    proposal_template: Path
    output_dir: Path


@dataclass
class CRMConfig:
    reminder_days: int


@dataclass
class ContractConfig:
    registers_dir: Path


@dataclass
class PMConfig:
    reports_dir: Path


@dataclass
class TokenConfig:
    provider: str
    keyring_service: str


@dataclass
class LLMConfig:
    provider: str | None
    timeout_seconds: int
    max_tokens: int




@dataclass
class SettingsConfig:
    llm_provider: str
    telemetry_opt_in: bool
    show_tour_on_start: bool


@dataclass
class MetricsEndpoints:
    summary: str = ""
    scope: str = ""
    estimate: str = ""
    compliance: str = ""
    bid: str = ""
    crm: str = ""
    activity: str = ""
    pm: str = ""


@dataclass
class MetricsRefreshIntervals:
    summary: int = 0
    scope: int = 0
    estimate: int = 0
    compliance: int = 0
    bid: int = 0
    crm: int = 0
    activity: int = 0
    pm: int = 0


@dataclass
class MetricsFeatureFlags:
    allow_offline_fallback: bool = True
    audit_refresh: bool = False


@dataclass
class MetricsConfig:
    enabled: bool
    cache_ttl_seconds: int
    request_timeout_seconds: float
    max_retries: int
    retry_backoff_seconds: float
    endpoints: MetricsEndpoints
    refresh_intervals: MetricsRefreshIntervals
    feature_flags: MetricsFeatureFlags


@dataclass
class CopilotConfig:
    enabled: bool
    provider: str
    timeout_seconds: int
    prompt_packs_root: Path
    offline_allowed: bool


@dataclass
class WorkspaceConfig:
    root: Path
    concurrency_limit: int
    first_run_flag: Path


@dataclass
class ThemeConfig:
    default_mode: str
    allow_dark_mode: bool
    animation_ms: int
    loader_asset: Path


@dataclass
class AuthConfig:
    db_path: Path
    audit_log_dir: Path
    session_timeout_minutes: int

@dataclass
class AppConfig:
    paths: PathsConfig
    logging: LoggingConfig
    server: ServerConfig
    ingest: IngestConfig
    scope: ScopeConfig
    estimation: EstimationConfig
    engineer: EngineerConfig
    compliance: ComplianceConfig
    bid: BidConfig
    crm: CRMConfig
    contract: ContractConfig
    pm: PMConfig
    tokens: TokenConfig
    llm: LLMConfig
    metrics: MetricsConfig
    copilot: CopilotConfig
    workspace: WorkspaceConfig
    theme: ThemeConfig
    auth: AuthConfig
    settings: SettingsConfig


def _load_yaml(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def _apply_overrides(config: Dict[str, Any]) -> Dict[str, Any]:
    env_prefix = "SA_CMS_PRO_"
    overrides: Dict[str, Any] = {}
    for key, value in os.environ.items():
        if key.startswith(env_prefix):
            _, *parts = key.split("_")
            parts = [part.lower() for part in parts if part]
            target: Dict[str, Any] = overrides
            for part in parts[:-1]:
                target = target.setdefault(part, {})  # type: ignore[assignment]
            target[parts[-1]] = value
    return _merge_dicts(config, overrides)


def _merge_dicts(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    result = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _merge_dicts(result[key], value)
        else:
            result[key] = value
    return result


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _normalize_path(path: Any, default: str | None = None) -> Path:
    if path is None and default is None:
        raise ValueError("Path value cannot be None")
    target = path if path is not None else default
    return _expand_path(str(target))


def _ensure_paths(paths: PathsConfig, bid: BidConfig, contract: ContractConfig, pm: PMConfig) -> None:
    allowed_roots: list[Path] = []
    for root in (paths.work_root, APPDATA, LOCALAPPDATA, PROGRAMDATA, Path.home()):
        if not root:
            continue
        root_path = root if isinstance(root, Path) else Path(root)
        if not root_path.is_absolute():
            continue
        try:
            allowed_roots.append(root_path.resolve())
        except OSError:
            allowed_roots.append(root_path)

    def _is_within(candidate: Path) -> bool:
        for base in allowed_roots:
            try:
                candidate.relative_to(base)
                return True
            except ValueError:
                continue
        return False

    def _mkdir_if_absolute(target: Path) -> None:
        if not isinstance(target, Path):
            target = Path(target)
        if not target.is_absolute():
            return
        try:
            resolved = target.resolve()
        except OSError:
            resolved = target
        if allowed_roots and not _is_within(resolved):
            return
        try:
            target.mkdir(parents=True, exist_ok=True)
        except PermissionError as exc:
            warnings.warn(f"Skipping creation of {target}: {exc}", RuntimeWarning)
        except OSError as exc:
            warnings.warn(f"Skipping creation of {target}: {exc}", RuntimeWarning)

    _mkdir_if_absolute(paths.work_root)
    _mkdir_if_absolute(paths.vector_store)
    _mkdir_if_absolute(paths.database.parent)
    _mkdir_if_absolute(bid.output_dir)
    _mkdir_if_absolute(contract.registers_dir)
    _mkdir_if_absolute(pm.reports_dir)
    log_dir = Path(paths.work_root) / "logs"
    _mkdir_if_absolute(log_dir)


def _deserialize(config: Dict[str, Any]) -> AppConfig:
    paths = config.get("paths", {})
    paths_cfg = PathsConfig(
        data_root=_normalize_path(paths.get("data_root", "data")),
        templates_root=_normalize_path(paths.get("templates_root", "data/templates")),
        pricebooks_root=_normalize_path(paths.get("pricebooks_root", "data/pricebooks")),
        work_root=_normalize_path(paths.get("work_root", "%AppData%/SA-CMS-Pro")),
        database=_normalize_path(paths.get("database", "%AppData%/SA-CMS-Pro/sa_cms_pro.db")),
        vector_store=_normalize_path(paths.get("vector_store", "%AppData%/SA-CMS-Pro/vectors")),
    )

    logging_cfg = LoggingConfig(
        level=str(config.get("logging", {}).get("level", "INFO")),
        file=_normalize_path(config.get("logging", {}).get("file", "%AppData%/SA-CMS-Pro/logs/sa_cms_pro.log")),
    )

    server_cfg = ServerConfig(
        host=config.get("server", {}).get("host", "127.0.0.1"),
        port=int(config.get("server", {}).get("port", 8765)),
        reload=bool(config.get("server", {}).get("reload", False)),
        workers=int(config.get("server", {}).get("workers", 1)),
    )

    ingest_section = config.get("ingest", {}) or {}
    telemetry_section = ingest_section.get("telemetry", {}) or {}
    log_path_value = telemetry_section.get("log_path")
    if not log_path_value:
        log_dict = telemetry_section.get("log")
        if isinstance(log_dict, dict):
            log_path_value = log_dict.get("path")
    telemetry_log_path = _normalize_path(log_path_value or "output/logs/ingest_events.jsonl")
    chunk_size_value = int(ingest_section.get("chunk_size", 1800))
    chunk_min_chars = int(ingest_section.get("chunk_min_chars", 1500 if chunk_size_value >= 1500 else 1500))
    chunk_max_chars = int(ingest_section.get("chunk_max_chars", 2000 if chunk_size_value <= 2000 else chunk_size_value))
    redact_sensitive = bool(ingest_section.get("redact_sensitive", False))
    ingest_cfg = IngestConfig(
        chunk_size=chunk_size_value,
        chunk_overlap=int(ingest_section.get("chunk_overlap", 60)),
        chunk_min_chars=chunk_min_chars,
        chunk_max_chars=chunk_max_chars,
        redact_sensitive=redact_sensitive,
        use_ocr=bool(ingest_section.get("use_ocr", True)),
        vector_backend=str(ingest_section.get("vector_backend", "memory")),
        default_collection=str(ingest_section.get("default_collection", "project_docs")),
        ruleset=str(ingest_section.get("ruleset", "rules/base_rules.yaml")),
        tesseract_cmd=ingest_section.get("tesseract_cmd"),
        telemetry_enabled=bool(telemetry_section.get("enabled", True)),
        telemetry_log_path=telemetry_log_path,
    )

    scope_cfg = ScopeConfig(
        csi_mapping=_normalize_path(config.get("scope", {}).get("csi_mapping", "config/providers.yaml")),
        default_disciplines=list(config.get("scope", {}).get("default_disciplines", ["CIV", "STR", "ARC", "MEP", "EL"])),
        llm_provider=config.get("scope", {}).get("llm_provider"),
        rule_sets=[_normalize_path(path) for path in config.get("scope", {}).get("rule_sets", [])],
    )

    margin = config.get("estimation", {}).get("default_margin", {})
    margin_cfg = MarginBreakdown(
        labor=_as_float(margin.get("labor", 0.18)),
        equipment=_as_float(margin.get("equipment", 0.12)),
        subcontractor=_as_float(margin.get("subcontractor", 0.08)),
        freight=_as_float(margin.get("freight", 0.05)),
        fuel=_as_float(margin.get("fuel", 0.04)),
        contingency=_as_float(margin.get("contingency", 0.03)),
    )

    estimation_cfg = EstimationConfig(
        default_margin=margin_cfg,
        price_providers=list(config.get("estimation", {}).get("price_providers", [])),
        currency=str(config.get("estimation", {}).get("currency", "USD")),
    )

    engineer_cfg = EngineerConfig(
        pump_curves_csv=_normalize_path(config.get("engineer", {}).get("pump_curves_csv", "data/templates/Submittal/pump_curves.csv")),
        hazen_williams_c=int(config.get("engineer", {}).get("hazen_williams_c", 120)),
    )

    compliance_cfg = ComplianceConfig(
        templates={k: _normalize_path(v) for k, v in config.get("compliance", {}).get("templates", {}).items()},
        jurisdictions_dir=_normalize_path(config.get("compliance", {}).get("jurisdictions_dir", "config/jurisdictions")),
    )

    bid_cfg = BidConfig(
        proposal_template=_normalize_path(config.get("bid", {}).get("proposal_template", "app/bid/templates/proposal.docx")),
        output_dir=_normalize_path(config.get("bid", {}).get("output_dir", "%AppData%/SA-CMS-Pro/bid")),
    )

    crm_cfg = CRMConfig(reminder_days=int(config.get("crm", {}).get("reminder_days", 3)))
    contract_cfg = ContractConfig(registers_dir=_normalize_path(config.get("contract", {}).get("registers_dir", "%AppData%/SA-CMS-Pro/registers")))
    pm_cfg = PMConfig(reports_dir=_normalize_path(config.get("pm", {}).get("reports_dir", "%AppData%/SA-CMS-Pro/pm")))

    token_defaults = {"provider": "dpapi", "keyring_service": "SA-CMS-Pro"}
    token_defaults.update(config.get("tokens", {}))
    token_cfg = TokenConfig(provider=str(token_defaults["provider"]), keyring_service=str(token_defaults["keyring_service"]))

    llm_section = config.get("llm", {})
    llm_cfg = LLMConfig(
        provider=llm_section.get("provider"),
        timeout_seconds=int(llm_section.get("timeout_seconds", 30)),
        max_tokens=int(llm_section.get("max_tokens", 512)),
    )

    metrics_section = config.get("metrics", {}) or {}
    endpoints_section = metrics_section.get("endpoints", {}) or {}
    refresh_section = metrics_section.get("refresh_intervals", {}) or {}
    flags_section = metrics_section.get("feature_flags", {}) or {}
    retry_section = metrics_section.get("retry", {}) or {}

    request_timeout = metrics_section.get("request_timeout_seconds", retry_section.get("timeout_seconds", 5))
    max_retries = metrics_section.get("max_retries", retry_section.get("attempts", 3))
    retry_backoff = metrics_section.get("retry_backoff_seconds", retry_section.get("backoff_seconds", 0.5))

    metrics_cfg = MetricsConfig(
        enabled=bool(metrics_section.get("enabled", True)),
        cache_ttl_seconds=int(metrics_section.get("cache_ttl_seconds", 180)),
        request_timeout_seconds=float(request_timeout),
        max_retries=int(max_retries),
        retry_backoff_seconds=float(retry_backoff),
        endpoints=MetricsEndpoints(
            summary=str(endpoints_section.get("summary", "")),
            scope=str(endpoints_section.get("scope", "")),
            estimate=str(endpoints_section.get("estimate", "")),
            compliance=str(endpoints_section.get("compliance", "")),
            bid=str(endpoints_section.get("bid", "")),
            crm=str(endpoints_section.get("crm", "")),
            activity=str(endpoints_section.get("activity", "")),
            pm=str(endpoints_section.get("pm", "")),
        ),
        refresh_intervals=MetricsRefreshIntervals(
            summary=int(refresh_section.get("summary", 300)),
            scope=int(refresh_section.get("scope", 180)),
            estimate=int(refresh_section.get("estimate", 240)),
            compliance=int(refresh_section.get("compliance", 300)),
            bid=int(refresh_section.get("bid", 240)),
            crm=int(refresh_section.get("crm", 240)),
            activity=int(refresh_section.get("activity", 300)),
            pm=int(refresh_section.get("pm", 300)),
        ),
        feature_flags=MetricsFeatureFlags(
            allow_offline_fallback=bool(flags_section.get("allow_offline_fallback", True)),
            audit_refresh=bool(flags_section.get("audit_refresh", False)),
        ),
    )

    copilot_section = config.get("copilot", {}) or {}
    copilot_cfg = CopilotConfig(
        enabled=bool(copilot_section.get("enabled", True)),
        provider=str(copilot_section.get("provider", "auto")),
        timeout_seconds=int(copilot_section.get("timeout_seconds", 45)),
        prompt_packs_root=_normalize_path(copilot_section.get("prompt_packs_root", "data/copilot")),
        offline_allowed=bool(copilot_section.get("offline_allowed", True)),
    )

    _ensure_paths(paths_cfg, bid_cfg, contract_cfg, pm_cfg)

    workspace_cfg = WorkspaceConfig(
        root=_normalize_path(config.get("workspace", {}).get("root", "%ProgramData%/SA-CMS-Pro/projects")),
        concurrency_limit=int(config.get("workspace", {}).get("concurrency_limit", 4)),
        first_run_flag=_normalize_path(config.get("workspace", {}).get("first_run_flag", "%AppData%/SA-CMS-Pro/state/first_run.json")),
    )

    theme_cfg = ThemeConfig(
        default_mode=str(config.get("theme", {}).get("default_mode", "light")),
        allow_dark_mode=bool(config.get("theme", {}).get("allow_dark_mode", True)),
        animation_ms=int(config.get("theme", {}).get("animation_ms", 250)),
        loader_asset=_normalize_path(config.get("theme", {}).get("loader_asset", "data/branding/logo_primary.png")),
    )

    auth_cfg = AuthConfig(
        db_path=_normalize_path(config.get("auth", {}).get("db_path", "%AppData%/SA-CMS-Pro/auth/users.db")),
        audit_log_dir=_normalize_path(config.get("auth", {}).get("audit_log_dir", "%ProgramData%/SA-CMS-Pro/logs")),
        session_timeout_minutes=int(config.get("auth", {}).get("session_timeout_minutes", 60)),
    )

    settings_cfg = SettingsConfig(
        llm_provider=str(config.get("settings", {}).get("llm_provider", "none")),
        telemetry_opt_in=bool(config.get("settings", {}).get("telemetry_opt_in", False)),
        show_tour_on_start=bool(config.get("settings", {}).get("show_tour_on_start", True)),
    )

    return AppConfig(
        paths=paths_cfg,
        logging=logging_cfg,
        server=server_cfg,
        ingest=ingest_cfg,
        scope=scope_cfg,
        estimation=estimation_cfg,
        engineer=engineer_cfg,
        compliance=compliance_cfg,
        bid=bid_cfg,
        crm=crm_cfg,
        contract=contract_cfg,
        pm=pm_cfg,
        tokens=token_cfg,
        llm=llm_cfg,
        metrics=metrics_cfg,
        copilot=copilot_cfg,
        workspace=workspace_cfg,
        theme=theme_cfg,
        auth=auth_cfg,
        settings=settings_cfg,
    )


@lru_cache(maxsize=1)

@lru_cache(maxsize=1)
def load_config() -> AppConfig:
    data = _load_yaml(CONFIG_PATH)
    merged = _apply_overrides(data)
    return _deserialize(merged)
