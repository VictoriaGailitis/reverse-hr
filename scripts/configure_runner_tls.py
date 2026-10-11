"""Create new local Runner mTLS credentials once; never rotate existing credentials."""

import hashlib
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID
from dotenv import dotenv_values


def save(path, data):
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb") as stream:
        stream.write(data)


def private_bytes(key):
    return key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    )


def create(root, node_id):
    now = datetime.now(UTC)
    ca_path = root / "runner-tls-ca"
    paths = [ca_path, root / "runner-tls-server", root / "runner-tls-client"]
    if any(path.exists() or path.is_symlink() for path in paths):
        raise ValueError("Existing TLS credentials require separate review; not rotating")
    for path in paths:
        path.mkdir(mode=0o700)
    key = ec.generate_private_key(ec.SECP256R1())
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Reverse HR local Runner CA")])
    ca = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(days=31))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(key.public_key()), critical=False
        )
        .add_extension(
            x509.KeyUsage(False, False, False, False, False, True, True, False, False),
            critical=True,
        )
        .sign(key, hashes.SHA256())
    )
    save(ca_path / "ca.key", private_bytes(key))
    save(ca_path / "ca.crt", ca.public_bytes(serialization.Encoding.PEM))
    pin = None
    for side, cn, usage in [
        ("server", "runner-bridge", ExtendedKeyUsageOID.SERVER_AUTH),
        ("client", str(node_id), ExtendedKeyUsageOID.CLIENT_AUTH),
    ]:
        path = root / ("runner-tls-" + side)
        private = ec.generate_private_key(ec.SECP256R1())
        builder = (
            x509.CertificateBuilder()
            .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)]))
            .issuer_name(ca.subject)
            .public_key(private.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(minutes=1))
            .not_valid_after(now + timedelta(days=30))
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .add_extension(
                x509.SubjectKeyIdentifier.from_public_key(private.public_key()), critical=False
            )
            .add_extension(
                x509.AuthorityKeyIdentifier.from_issuer_public_key(key.public_key()), critical=False
            )
            .add_extension(
                x509.KeyUsage(True, False, False, False, False, False, False, False, False),
                critical=True,
            )
            .add_extension(x509.ExtendedKeyUsage([usage]), critical=True)
        )
        if side == "server":
            builder = builder.add_extension(
                x509.SubjectAlternativeName([x509.DNSName(cn)]), critical=False
            )
        cert = builder.sign(key, hashes.SHA256())
        save(path / "ca.crt", ca.public_bytes(serialization.Encoding.PEM))
        save(path / (side + ".crt"), cert.public_bytes(serialization.Encoding.PEM))
        save(path / (side + ".key"), private_bytes(private))
        if side == "client":
            pin = hashlib.sha256(cert.public_bytes(serialization.Encoding.DER)).hexdigest()
    return pin


def main():
    import argparse
    from uuid import UUID

    parser = argparse.ArgumentParser()
    parser.add_argument("--node-id", type=UUID, required=True)
    args = parser.parse_args()
    root = Path(".secrets")
    if root.is_symlink() or not root.is_dir() or root.stat().st_mode & 0o077:
        parser.error("Private .secrets directory required")
    env = Path(".env")
    if env.is_symlink() or not env.is_file() or env.stat().st_mode & 0o077:
        parser.error("Private existing .env required")
    if dotenv_values(env).get("RUNNER_CLIENT_CERT_SHA256"):
        parser.error("Existing approved client certificate must not be replaced")
    pin = create(root, args.node_id)
    with env.open("a") as stream:
        stream.write(
            f"\nRUNNER_LOCAL_UID={os.getuid()}\nRUNNER_LOCAL_GID={os.getgid()}\n"
            f"RUNNER_CLIENT_CERT_SHA256={pin}\n"
        )
    print("Local mTLS credentials created; keys private, exact client certificate configured")


if __name__ == "__main__":
    main()
