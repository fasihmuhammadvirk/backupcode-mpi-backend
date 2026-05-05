"""
GPG encryption utilities for database backup security.

Provides symmetric encryption/decryption using GPG for database backups.
Uses AES256 cipher for strong encryption.
"""
import os
import subprocess
import shutil
import logging
from pathlib import Path
from typing import Tuple

logger = logging.getLogger(__name__)


class GPGEncryptionError(Exception):
    """Custom exception for GPG encryption/decryption errors."""
    pass


def is_gpg_available() -> Tuple[bool, str]:
    """
    Check if GPG is available on the system.

    Returns:
        Tuple of (is_available, error_message)
    """
    if not shutil.which('gpg'):
        return False, "GPG (gnupg) is not installed. Install it with: sudo apt-get install gnupg"

    # Test GPG is working
    try:
        result = subprocess.run(
            ['gpg', '--version'],
            capture_output=True,
            text=True,
            timeout=5,
            check=True
        )
        return True, ""
    except subprocess.TimeoutExpired:
        return False, "GPG command timed out"
    except subprocess.CalledProcessError as e:
        return False, f"GPG command failed: {e}"
    except Exception as e:
        return False, f"Unexpected error checking GPG: {e}"


def validate_passphrase_strength(passphrase: str) -> Tuple[bool, str]:
    """
    Validate passphrase meets minimum security requirements.

    Args:
        passphrase: The passphrase to validate

    Returns:
        Tuple of (is_valid, error_message)
    """
    if not passphrase:
        return False, "Passphrase cannot be empty"

    if len(passphrase) < 12:
        return False, "Passphrase must be at least 12 characters long"

    # Check for common weak words in passphrase
    weak_words = ['password', 'passphrase', 'admin', '123456', 'qwerty']
    passphrase_lower = passphrase.lower()
    for weak_word in weak_words:
        if weak_word in passphrase_lower:
            return False, f"Passphrase contains common weak word: '{weak_word}'"

    return True, ""


def encrypt_file(input_path: Path, output_path: Path, passphrase: str, timeout: int = 1800) -> None:
    """
    Encrypt a file using GPG symmetric encryption (AES256).

    Args:
        input_path: Path to file to encrypt
        output_path: Path for encrypted output file
        passphrase: Encryption passphrase
        timeout: Maximum time in seconds for encryption (default: 1800 = 30 minutes)

    Raises:
        GPGEncryptionError: If encryption fails
        FileNotFoundError: If input file doesn't exist
    """
    # Validate inputs
    if not input_path.exists():
        raise FileNotFoundError(f"Input file not found: {input_path}")

    if not input_path.is_file():
        raise GPGEncryptionError(f"Input path is not a file: {input_path}")

    # Validate passphrase
    is_valid, error_msg = validate_passphrase_strength(passphrase)
    if not is_valid:
        raise GPGEncryptionError(f"Weak passphrase: {error_msg}")

    # Check GPG is available
    gpg_available, error_msg = is_gpg_available()
    if not gpg_available:
        raise GPGEncryptionError(f"GPG not available: {error_msg}")

    logger.info(f"Encrypting file: {input_path.name} → {output_path.name}")

    try:
        # Build GPG encryption command
        # --symmetric: Use symmetric encryption (password-based)
        # --cipher-algo AES256: Use AES256 cipher
        # --batch: Non-interactive mode
        # --yes: Overwrite existing files without prompting
        # --passphrase-fd 0: Read passphrase from stdin
        cmd = [
            'gpg',
            '--symmetric',
            '--cipher-algo', 'AES256',
            '--batch',
            '--yes',
            '--pinentry-mode', 'loopback',
            '--passphrase-fd', '0',
            '-o', str(output_path),
            str(input_path)
        ]

        # Execute encryption with passphrase via stdin (secure)
        process = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        try:
            stdout, stderr = process.communicate(input=passphrase, timeout=timeout)
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate()  # Drain pipes and reap child
            if output_path.exists():
                output_path.unlink()
            raise GPGEncryptionError(f"GPG encryption timed out after {timeout} seconds ({timeout/60:.0f} minutes)")
        finally:
            # Close pipe FDs promptly to avoid FD exhaustion in constrained pods
            for pipe in (process.stdout, process.stderr, process.stdin):
                if pipe:
                    try:
                        pipe.close()
                    except OSError:
                        pass

        if process.returncode != 0:
            # Remove partial output file if it exists
            if output_path.exists():
                output_path.unlink()

            # Parse error message
            error_detail = stderr.strip() if stderr else "Unknown error"
            raise GPGEncryptionError(
                f"GPG encryption failed (exit code {process.returncode}): {error_detail}"
            )

        # Verify output file was created
        if not output_path.exists():
            raise GPGEncryptionError("Encryption appeared to succeed but output file not found")

        if output_path.stat().st_size == 0:
            output_path.unlink()
            raise GPGEncryptionError("Encryption produced empty output file")

        logger.info(f"Encryption successful: {output_path.stat().st_size} bytes")
    except GPGEncryptionError:
        raise  # Re-raise our custom errors
    except Exception as e:
        if output_path.exists():
            output_path.unlink()
        raise GPGEncryptionError(f"Unexpected encryption error: {e}")


def decrypt_file(input_path: Path, output_path: Path, passphrase: str, timeout: int = 1800) -> None:
    """
    Decrypt a GPG-encrypted file.

    Args:
        input_path: Path to encrypted file (.gpg)
        output_path: Path for decrypted output file
        passphrase: Decryption passphrase
        timeout: Maximum time in seconds for decryption (default: 1800 = 30 minutes)

    Raises:
        GPGEncryptionError: If decryption fails
        FileNotFoundError: If input file doesn't exist
    """
    # Validate inputs
    if not input_path.exists():
        raise FileNotFoundError(f"Encrypted file not found: {input_path}")

    if not input_path.is_file():
        raise GPGEncryptionError(f"Input path is not a file: {input_path}")

    if not passphrase:
        raise GPGEncryptionError("Passphrase is required for decryption")

    # Check GPG is available
    gpg_available, error_msg = is_gpg_available()
    if not gpg_available:
        raise GPGEncryptionError(f"GPG not available: {error_msg}")

    logger.info(f"Decrypting file: {input_path.name} → {output_path.name}")

    try:
        # Build GPG decryption command
        # --decrypt: Decrypt the file
        # --batch: Non-interactive mode
        # --yes: Overwrite existing files without prompting
        # --passphrase-fd 0: Read passphrase from stdin
        cmd = [
            'gpg',
            '--decrypt',
            '--batch',
            '--yes',
            '--pinentry-mode', 'loopback',
            '--passphrase-fd', '0',
            '-o', str(output_path),
            str(input_path)
        ]

        # Do NOT use a context manager here. Popen.__exit__ calls wait()
        # unconditionally, which would block forever if communicate() raises
        # TimeoutExpired on a still-running child. Instead, manage the
        # subprocess lifecycle manually so timeout cleanup always runs.
        process = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        try:
            stdout, stderr = process.communicate(input=passphrase, timeout=timeout)
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate()  # Drain pipes and reap child
            if output_path.exists():
                output_path.unlink()
            raise GPGEncryptionError(f"GPG decryption timed out after {timeout} seconds ({timeout/60:.0f} minutes)")
        finally:
            # Close pipe FDs promptly to avoid FD exhaustion in constrained pods
            for pipe in (process.stdout, process.stderr, process.stdin):
                if pipe:
                    try:
                        pipe.close()
                    except OSError:
                        pass

        if process.returncode != 0:
            # Remove partial output file if it exists
            if output_path.exists():
                output_path.unlink()

            # Parse error message for common issues
            error_detail = stderr.strip() if stderr else "Unknown error"

            if 'Bad session key' in stderr or 'decryption failed' in stderr.lower():
                raise GPGEncryptionError(
                    "Decryption failed: Incorrect passphrase or corrupted file"
                )
            elif 'No such file' in stderr:
                raise GPGEncryptionError(f"File not found: {input_path}")
            else:
                raise GPGEncryptionError(
                    f"GPG decryption failed (exit code {process.returncode}): {error_detail}"
                )

        # Verify output file was created
        if not output_path.exists():
            raise GPGEncryptionError("Decryption appeared to succeed but output file not found")

        if output_path.stat().st_size == 0:
            output_path.unlink()
            raise GPGEncryptionError("Decryption produced empty output file")

        logger.info(f"Decryption successful: {output_path.stat().st_size} bytes")
    except GPGEncryptionError:
        raise  # Re-raise our custom errors
    except Exception as e:
        if output_path.exists():
            output_path.unlink()
        raise GPGEncryptionError(f"Unexpected decryption error: {e}")


def secure_delete(file_path: Path) -> None:
    """
    Securely delete a file by overwriting it before removal.

    This prevents recovery of sensitive data (like decrypted backups).

    Args:
        file_path: Path to file to securely delete
    """
    if not file_path.exists():
        return

    try:
        # Get file size
        file_size = file_path.stat().st_size

        if file_size > 0:
            # Overwrite with zeros (simple but effective for most cases)
            # For very large files, only overwrite first 1MB to avoid performance issues
            overwrite_size = min(file_size, 1024 * 1024)

            with open(file_path, 'r+b') as f:
                f.write(b'\x00' * overwrite_size)
                f.flush()
                os.fsync(f.fileno())

        # Now delete the file
        file_path.unlink()
        logger.debug(f"Securely deleted: {file_path}")

    except Exception as e:
        logger.warning(f"Secure delete failed for {file_path}: {e}")
        # Try regular delete as fallback
        try:
            file_path.unlink()
        except:
            pass


def is_file_encrypted(file_path: Path) -> bool:
    """
    Check if a file appears to be GPG encrypted.

    Args:
        file_path: Path to file to check

    Returns:
        True if file appears to be GPG encrypted, False otherwise
    """
    if not file_path.exists():
        return False

    # Check file extension
    if file_path.suffix == '.gpg':
        return True

    # Could also check file magic bytes, but extension is sufficient for our use case
    return False
