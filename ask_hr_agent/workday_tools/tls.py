import logging
import os
from pathlib import Path
import ssl

logger = logging.getLogger(__name__)


def _env_truthy(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in ("1", "true", "yes", "on")


def _load_env_from_file() -> None:
    env_path = Path(__file__).parent / ".env"
    if not env_path.exists():
        return

    try:
        with open(env_path, "r", encoding="utf-8") as handle:
            for line in handle:
                value = line.strip()
                if not value or value.startswith("#"):
                    continue
                if "=" not in value:
                    continue
                key, val = value.split("=", 1)
                key = key.strip()
                val = val.strip()
                if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
                    val = val[1:-1]
                os.environ.setdefault(key, val)
    except Exception:
        # Non-fatal; continue without .env
        pass


def _set_ca_bundle_env(bundle_path: Path) -> None:
    os.environ.setdefault("REQUESTS_CA_BUNDLE", str(bundle_path))
    os.environ.setdefault("SSL_CERT_FILE", str(bundle_path))
    os.environ.setdefault("GRPC_DEFAULT_SSL_ROOTS_FILE_PATH", str(bundle_path))


def _configure_ca_bundle() -> None:
    bundle_env = os.getenv("ASKHR_CA_BUNDLE")
    if bundle_env:
        bundle_path = Path(bundle_env)
        if bundle_path.exists():
            _set_ca_bundle_env(bundle_path)
            logger.info("Using CA bundle from ASKHR_CA_BUNDLE: %s", bundle_path)
        else:
            logger.warning("ASKHR_CA_BUNDLE set but file not found: %s", bundle_path)
        return

    repo_root = Path(__file__).resolve().parents[1]
    default_bundle = repo_root / "certs" / "combined-ca-bundle.pem"
    if default_bundle.exists():
        _set_ca_bundle_env(default_bundle)
        logger.info("Using default CA bundle: %s", default_bundle)


def _relax_x509_strict() -> None:
    if not _env_truthy("ASKHR_RELAX_SSL"):
        return

    strict_flag = getattr(ssl, "VERIFY_X509_STRICT", None)
    if strict_flag is None:
        return

    orig_create = ssl.create_default_context

    def _relaxed_create_default_context(*args, **kwargs):
        ctx = orig_create(*args, **kwargs)
        try:
            ctx.verify_flags &= ~strict_flag
        except Exception:
            pass
        return ctx

    ssl.create_default_context = _relaxed_create_default_context
    ssl._create_default_https_context = _relaxed_create_default_context  # type: ignore
    logger.warning("ASKHR_RELAX_SSL enabled: disabling X509 strict checks.")

    try:
        import urllib3.util.ssl_ as urllib3_ssl  # type: ignore
    except Exception:
        return

    orig_urllib3_context = urllib3_ssl.create_urllib3_context

    def _relaxed_urllib3_context(*args, **kwargs):
        ctx = orig_urllib3_context(*args, **kwargs)
        try:
            ctx.verify_flags &= ~strict_flag
        except Exception:
            pass
        return ctx

    urllib3_ssl.create_urllib3_context = _relaxed_urllib3_context
    try:
        import urllib3.connection as urllib3_conn  # type: ignore
    except Exception:
        return
    urllib3_conn.create_urllib3_context = _relaxed_urllib3_context


def configure_tls() -> None:
    _load_env_from_file()
    _configure_ca_bundle()
    _relax_x509_strict()
