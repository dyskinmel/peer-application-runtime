from __future__ import annotations
import hashlib
import json
import re
import subprocess
import zipfile
from pathlib import Path

from .public_alpha import PROFILE_RELATIVE_PATH, load_public_alpha_profile, validate_public_alpha_profile
from .snapshot import snapshot

_TOKEN_RE = re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{20,}\b")
_SECRET_ASSIGNMENT_RE = re.compile(r"(?i)\b(?:api[_-]?key|access[_-]?token|auth[_-]?token|password|passwd|secret|credential)\b\s*[:=]\s*([\"\'])([A-Za-z0-9_./+=:@-]{8,})\1")
_EMAIL_RE = re.compile(r"(?<![A-Za-z0-9._%+-])[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}(?![A-Za-z0-9.-])")
_WINDOWS_USER_PATH_RE = re.compile(r"(?i)\b[A-Z]:\\Users\\[^\\\s]+")
_PRIVATE_GIT_REMOTE_RE = re.compile(r"(?i)(?:git@[^\s:]+:[^\s\"\']+|ssh://[^\s\"\']+)")
_INTERNAL_HOST_RE = re.compile(r"(?i)https?://[A-Za-z0-9.-]+\.(?:internal|corp|lan)(?=[:/\s]|$)")
_PRIVATE_KEY_RE = re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|BEGIN PRIVATE KEY")
_FIXED_ZIP_TIME = (1980, 1, 1, 0, 0, 0)
_PUBLIC_CLASSES = {"PUBLIC", "PUBLIC_DEVELOPMENT"}
_REQUIRED_CLASSES = {"PUBLIC", "PUBLIC_DEVELOPMENT", "INTERNAL_ONLY", "GENERATED_EXCLUDE"}
_GENERATED_ARCHIVE_FILES = {"PUBLIC_SOURCE_MANIFEST.json", "PUBLIC_PREVIEW_STATUS.json", "SHA256SUMS"}


def classify_public_path(rel: Path, policy: dict) -> str | None:
    rel = Path(rel)
    s = rel.as_posix()
    rules = policy.get("classifications")
    if not isinstance(rules, dict):
        return "PUBLIC" if _included_legacy(rel, policy) else "INTERNAL_ONLY"
    if set(rules) != _REQUIRED_CLASSES:
        return None
    precedence = policy.get("classification_precedence", ["GENERATED_EXCLUDE", "INTERNAL_ONLY", "PUBLIC_DEVELOPMENT", "PUBLIC"])
    for classification in precedence:
        rule = rules.get(classification, {})
        if s in set(rule.get("exact", [])):
            return classification
        if any(s.startswith(prefix) for prefix in rule.get("prefixes", [])):
            return classification
        if any(part in set(rule.get("components", [])) for part in rel.parts):
            return classification
        if any(s.endswith(suffix) for suffix in rule.get("suffixes", [])):
            return classification
        if rel.parts and rel.parts[0] in set(rule.get("roots", [])):
            return classification
    return None


def _included_legacy(rel: Path, policy: dict) -> bool:
    s = rel.as_posix()
    if rel.parts and rel.parts[0] in set(policy.get("excluded_roots", [])):
        return False
    if any(part in set(policy.get("excluded_path_components", [])) for part in rel.parts):
        return False
    if any(s.endswith(suffix) for suffix in policy.get("excluded_suffixes", [])):
        return False
    if any(s.startswith(prefix) for prefix in policy.get("excluded_prefixes", [])):
        return False
    if len(rel.parts) == 1 and s in set(policy.get("included_top_level_files", [])):
        return True
    return bool(rel.parts and rel.parts[0] in set(policy.get("included_roots", [])))


def _tracked_paths(root: Path) -> list[Path] | None:
    try:
        cp = subprocess.run(["git", "-C", str(root), "ls-files", "-z"], check=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    except (OSError, subprocess.CalledProcessError):
        return None
    return [Path(raw.decode("utf-8", "surrogateescape")) for raw in cp.stdout.split(b"\0") if raw]


def _git_value(root: Path, *args: str) -> str | None:
    try:
        cp = subprocess.run(["git", "-C", str(root), *args], check=True, text=True, capture_output=True)
    except (OSError, subprocess.CalledProcessError):
        return None
    return cp.stdout.strip()


def source_identity(root: Path) -> dict:
    head = _git_value(root, "rev-parse", "HEAD")
    tree = _git_value(root, "rev-parse", "HEAD^{tree}")
    branch = _git_value(root, "branch", "--show-current")
    commit_time = _git_value(root, "show", "-s", "--format=%cI", "HEAD")
    tags_raw = _git_value(root, "tag", "--points-at", "HEAD") or ""
    return {
        "head": head,
        "tree": tree,
        "branch": branch,
        "source_digest": snapshot(root)["digest"] if head else None,
        "checkpoint_tags": sorted(x for x in tags_raw.splitlines() if x),
        "commit_time": commit_time,
    }


def audit_tracked_classification(root: Path, policy: dict) -> dict:
    root = Path(root)
    paths = _tracked_paths(root)
    if paths is None:
        paths = [p.relative_to(root) for p in root.rglob("*") if p.is_file() or p.is_symlink()]
    counts = {name: 0 for name in sorted(_REQUIRED_CLASSES)}
    unclassified = []
    for rel in sorted(paths, key=lambda x: x.as_posix()):
        classification = classify_public_path(rel, policy)
        if classification is None:
            unclassified.append(rel.as_posix())
        else:
            counts[classification] += 1
    return {"pass": not unclassified, "tracked_files": len(paths), "classification_counts": counts, "unclassified": unclassified}


def public_files(root: Path, policy: dict) -> list[Path]:
    root = Path(root)
    tracked = _tracked_paths(root) if policy.get("classifications") else None
    candidates = tracked if tracked is not None else [p.relative_to(root) for p in root.rglob("*") if p.is_file() or p.is_symlink()]
    out = []
    for rel in sorted(candidates, key=lambda x: x.as_posix()):
        p = root / rel
        classification = classify_public_path(rel, policy)
        if p.is_symlink():
            if classification in _PUBLIC_CLASSES:
                raise ValueError("PUBLIC_PREVIEW_SYMLINK:" + rel.as_posix())
            continue
        if p.is_file() and classification in _PUBLIC_CLASSES:
            out.append(p)
    return out


def _candidate_rows(root: Path, policy: dict) -> list[dict]:
    aliases = dict(policy.get("public_aliases", {}))
    rows = []
    seen = set()
    for p in public_files(root, policy):
        source_rel = p.relative_to(root).as_posix()
        dest = aliases.get(source_rel, source_rel)
        if dest in seen:
            raise ValueError("PUBLIC_SOURCE_DUPLICATE_DESTINATION:" + dest)
        seen.add(dest)
        data = p.read_bytes()
        rows.append({
            "path": dest,
            "source_path": source_rel,
            "size_bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
            "classification": classify_public_path(Path(source_rel), policy),
        })
    return sorted(rows, key=lambda x: x["path"])


def build_public_manifest(root: Path, policy: dict) -> dict:
    root = Path(root)
    profile = load_public_alpha_profile(root)
    profile_errors = validate_public_alpha_profile(root, profile)
    if profile_errors:
        raise ValueError("PUBLIC_ALPHA_PROFILE_INVALID:" + json.dumps(profile_errors, sort_keys=True))
    if policy.get("release_profile") != PROFILE_RELATIVE_PATH.as_posix():
        raise ValueError("PUBLIC_ALPHA_PROFILE_PATH_MISMATCH")
    prerequisites = profile["external_publish_prerequisites"]
    if policy.get("unresolved_gates") != [row["id"] for row in prerequisites]:
        raise ValueError("PUBLIC_ALPHA_PREREQUISITES_MISMATCH")
    audit = audit_tracked_classification(root, policy) if policy.get("classifications") else {"pass": True, "unclassified": [], "classification_counts": {}}
    if not audit["pass"]:
        raise ValueError("PUBLIC_SOURCE_UNCLASSIFIED:" + ",".join(audit["unclassified"][:20]))
    rows = _candidate_rows(root, policy)
    body = {
        "schema_version": 3 if policy.get("classifications") else 1,
        "classification": policy.get("classification", "OSS_DEVELOPER_PREVIEW_CANDIDATE_NOT_RELEASE_AUTHORIZATION"),
        "publishable": False,
        "release_authorized": False,
        "product_qualified": False,
        "release_profile": PROFILE_RELATIVE_PATH.as_posix(),
        "external_publish_prerequisites": prerequisites,
        "source": source_identity(root),
        "unresolved_gates": list(policy.get("unresolved_gates", [])),
        "classification_audit": audit,
        "excluded_categories": dict(audit.get("classification_counts", {})),
        "public_file_count": len(rows),
        "total_bytes": sum(x["size_bytes"] for x in rows),
        "files": rows,
    }
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    body["manifest_sha256"] = hashlib.sha256(canonical).hexdigest()
    return body


def _zip_write(z: zipfile.ZipFile, name: str, data: bytes, mode: int = 0o644):
    info = zipfile.ZipInfo(name, _FIXED_ZIP_TIME)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.create_system = 3
    info.external_attr = (mode & 0xFFFF) << 16
    z.writestr(info, data)


def build_preview_archive(root: Path, policy: dict, output: Path) -> dict:
    root = Path(root)
    output = Path(output)
    manifest = build_public_manifest(root, policy)
    status = {
        "schema_version": 3 if policy.get("classifications") else 1,
        "publishable": False,
        "release_authorized": False,
        "classification": policy.get("classification"),
        "display_name": policy.get("display_name"),
        "unresolved_gates": list(policy.get("unresolved_gates", [])),
        "release_profile": manifest["release_profile"],
        "external_publish_prerequisites": manifest["external_publish_prerequisites"],
        "product_qualified": False,
        "manifest_sha256": manifest["manifest_sha256"],
        "source": manifest.get("source"),
    }
    manifest_bytes = (json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode()
    status_bytes = (json.dumps(status, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode()
    sums = []
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for row in manifest["files"]:
            p = root / row["source_path"]
            mode = 0o755 if (p.stat().st_mode & 0o111) else 0o644
            data = p.read_bytes()
            _zip_write(z, row["path"], data, mode)
            sums.append((row["path"], hashlib.sha256(data).hexdigest()))
        _zip_write(z, "PUBLIC_SOURCE_MANIFEST.json", manifest_bytes)
        _zip_write(z, "PUBLIC_PREVIEW_STATUS.json", status_bytes)
        sums.extend([
            ("PUBLIC_PREVIEW_STATUS.json", hashlib.sha256(status_bytes).hexdigest()),
            ("PUBLIC_SOURCE_MANIFEST.json", hashlib.sha256(manifest_bytes).hexdigest()),
        ])
        sums_bytes = "".join(f"{digest}  {name}\n" for name, digest in sorted(sums)).encode()
        _zip_write(z, "SHA256SUMS", sums_bytes)
    data = output.read_bytes()
    return {
        "result": "PASS",
        "file": output.name,
        "size_bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "source_files": len(manifest["files"]),
        "publishable": False,
        "unresolved_gates": status["unresolved_gates"],
        "manifest_sha256": manifest["manifest_sha256"],
        "source": manifest.get("source"),
    }


def write_outer_sha256(archive: Path, output: Path | None = None) -> Path:
    archive = Path(archive)
    output = Path(output) if output else archive.with_name(archive.name + ".sha256")
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    output.write_text(f"{digest}  {archive.name}\n", encoding="utf-8")
    return output


def _load_scan_allowlist(root: Path, policy: dict) -> tuple[list[dict], list[dict]]:
    rel = policy.get("scan", {}).get("allowlist_file")
    if not rel:
        return [], []
    path = root / rel
    if not path.exists():
        return [], [{"path": rel, "kind": "SCAN_ALLOWLIST_MISSING"}]
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return [], [{"path": rel, "kind": "SCAN_ALLOWLIST_INVALID"}]
    entries = data.get("entries", []) if isinstance(data, dict) else []
    errors = []
    valid = []
    for i, entry in enumerate(entries):
        if not isinstance(entry, dict) or not entry.get("path") or not entry.get("kind") or not str(entry.get("reason", "")).strip():
            errors.append({"path": rel, "kind": "SCAN_ALLOWLIST_INVALID_ENTRY", "index": i})
        else:
            valid.append(entry)
    return valid, errors


def _is_allowlisted(finding: dict, entries: list[dict]) -> bool:
    for entry in entries:
        if entry["path"] != finding.get("path") or entry["kind"] != finding.get("kind"):
            continue
        expected = entry.get("match")
        if expected is None or expected == finding.get("match"):
            return True
    return False


def _scan_paths(root: Path, policy: dict, rel_paths: list[Path], *, audit_classification: bool) -> dict:
    findings: list[dict] = []
    scanned: list[str] = []
    scan_policy = policy.get("scan", {})
    max_text_bytes = int(scan_policy.get("max_text_bytes", 2097152))
    max_public_file_bytes = int(scan_policy.get("max_public_file_bytes", 10485760))
    secret_literals = scan_policy.get("secret_patterns", [])
    path_prefixes = scan_policy.get("local_path_prefixes", [])
    allowed_binary_suffixes = set(scan_policy.get("allowed_binary_suffixes", []))
    exempt = set(policy.get("scan_exempt_paths", {}))
    allowlist, allowlist_errors = _load_scan_allowlist(root, policy)
    findings.extend(allowlist_errors)
    if audit_classification and policy.get("classifications"):
        audit = audit_tracked_classification(root, policy)
        for path in audit["unclassified"]:
            findings.append({"path": path, "kind": "UNCLASSIFIED_TRACKED_PATH"})
    for rel in sorted(rel_paths, key=lambda x: x.as_posix()):
        p = root / rel
        rels = rel.as_posix()
        if rels in exempt or rels in _GENERATED_ARCHIVE_FILES:
            continue
        try:
            size = p.stat().st_size
            data = p.read_bytes()
        except OSError:
            findings.append({"path": rels, "kind": "PUBLIC_FILE_UNREADABLE"})
            continue
        if size > max_public_file_bytes:
            findings.append({"path": rels, "kind": "OVERSIZED_PUBLIC_FILE", "size_bytes": size})
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            if p.suffix.lower() not in allowed_binary_suffixes:
                findings.append({"path": rels, "kind": "UNEXPECTED_BINARY", "size_bytes": size, "suffix": p.suffix.lower()})
            continue
        if size > max_text_bytes:
            continue
        scanned.append(rels)
        if _TOKEN_RE.search(text): findings.append({"path": rels, "kind": "SECRET_TOKEN"})
        if _SECRET_ASSIGNMENT_RE.search(text): findings.append({"path": rels, "kind": "SECRET_ASSIGNMENT"})
        if _PRIVATE_KEY_RE.search(text): findings.append({"path": rels, "kind": "PRIVATE_KEY_MATERIAL"})
        for literal in secret_literals:
            if literal in text: findings.append({"path": rels, "kind": "SECRET_LITERAL", "match": literal})
        for prefix in path_prefixes:
            if prefix in text: findings.append({"path": rels, "kind": "LOCAL_ABSOLUTE_PATH", "match": prefix})
        if _WINDOWS_USER_PATH_RE.search(text): findings.append({"path": rels, "kind": "WINDOWS_USER_PATH"})
        for match in sorted(set(_EMAIL_RE.findall(text))): findings.append({"path": rels, "kind": "EMAIL_ADDRESS", "match": match})
        if _PRIVATE_GIT_REMOTE_RE.search(text): findings.append({"path": rels, "kind": "PRIVATE_GIT_REMOTE"})
        if _INTERNAL_HOST_RE.search(text): findings.append({"path": rels, "kind": "INTERNAL_HOSTNAME"})
    effective, allowlisted = [], []
    for finding in findings:
        if _is_allowlisted(finding, allowlist):
            allowed = dict(finding)
            allowed["reason"] = next(entry["reason"] for entry in allowlist if entry["path"] == finding.get("path") and entry["kind"] == finding.get("kind") and (entry.get("match") is None or entry.get("match") == finding.get("match")))
            allowlisted.append(allowed)
        else:
            effective.append(finding)
    return {"pass": not effective, "publishable": False, "scanned_files": len(scanned), "findings": effective, "allowlisted_findings": allowlisted, "unresolved_gates": list(policy.get("unresolved_gates", []))}


def scan_public_surface(root: Path, policy: dict, explicit_paths: list[Path] | None = None) -> dict:
    root = Path(root)
    if explicit_paths is None:
        paths = [p.relative_to(root) for p in public_files(root, policy)]
        return _scan_paths(root, policy, paths, audit_classification=True)
    return _scan_paths(root, policy, [Path(x) for x in explicit_paths], audit_classification=False)
