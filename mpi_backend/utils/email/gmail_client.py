"""
Gmail API client using Service Account with Domain-Wide Delegation.

Features:
- Service Account authentication (no browser flow)
- Domain-wide delegation to access user mailboxes
- Built-in exponential backoff via google-api-python-client
- No socket timeout issues (HTTP-based)
"""

import os
import json
import base64
import logging
from typing import List, Optional, Dict, Any

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from mpi_backend.config import (
    ENVIRONMENT,
    GOOGLE_SERVICE_ACCOUNT_B64,
    GOOGLE_SERVICE_ACCOUNT_PATH,
    GMAIL_USER_EMAIL,
)

logger = logging.getLogger(__name__)

# Read-only scope - cannot send or delete emails
SCOPES = ['https://www.googleapis.com/auth/gmail.readonly']


class GmailAPIError(Exception):
    """Raised when Gmail API operation fails"""
    pass


def _load_service_account_credentials(service_account_path: str, user_email: str,) -> service_account.Credentials:
    """Load Google service account credentials based on environment.

    Non-dev: decodes GOOGLE_SERVICE_ACCOUNT_B64 env var.
    Dev: reads from service account JSON file on disk.

    Returns a delegated Credentials instance ready for Gmail API use.
    """
    if ENVIRONMENT != "dev":
        if not GOOGLE_SERVICE_ACCOUNT_B64:
            raise GmailAPIError(f"GOOGLE_SERVICE_ACCOUNT_B64 env var is required in {ENVIRONMENT}.")
        try:
            credentials_info = json.loads(base64.b64decode(GOOGLE_SERVICE_ACCOUNT_B64))
        except (ValueError, json.JSONDecodeError) as e:
            raise GmailAPIError(
                "GOOGLE_SERVICE_ACCOUNT_B64 is not valid base64-encoded JSON. "
                "Verify the value was generated with: base64 -w 0 service-account.json"
            ) from e
        creds = service_account.Credentials.from_service_account_info(credentials_info, scopes=SCOPES)

    else:
        if not os.path.exists(service_account_path):
            raise GmailAPIError(f"service-account.json not found at {service_account_path}.")
        creds = service_account.Credentials.from_service_account_file(service_account_path, scopes=SCOPES)

    return creds.with_subject(user_email)


class GmailClient:
    """Gmail API client with Service Account authentication"""

    def __init__(
        self,
        service_account_path: Optional[str] = None,
        user_email: Optional[str] = None
    ):
        self.service_account_path: str = service_account_path or GOOGLE_SERVICE_ACCOUNT_PATH

        resolved_email = user_email or GMAIL_USER_EMAIL
        if not resolved_email:
            raise GmailAPIError(
                "GMAIL_USER_EMAIL environment variable is required. "
                "Set it to the email inbox you want to access."
            )
        self.user_email: str = resolved_email

        self.service = None
        self._creds = None

    @property
    def user_id(self) -> str:
        """Return user ID for API calls (always 'me' when using delegated credentials)"""
        return 'me'

    def authenticate(self) -> bool:
        """
        Authenticate with Gmail API using Service Account.

        No browser flow - uses service account credentials with
        domain-wide delegation to impersonate the target user.
        """
        try:
            self._creds = _load_service_account_credentials(self.service_account_path, self.user_email)
            self.service = build('gmail', 'v1', credentials=self._creds)
            logger.info("Gmail API authenticated as %s", self.user_email)
            return True

        except Exception as e:
            logger.error("Authentication failed: %s", e)
            raise GmailAPIError(f"Authentication failed: {e}")

    def search_messages(
        self,
        query: str,
        max_results: int = 500
    ) -> List[Dict[str, str]]:
        """
        Search for messages matching query.

        Args:
            query: Gmail search query (same syntax as web UI)
                   Examples:
                   - "from:billing@example.com"
                   - "after:2020/01/01 before:2025/01/01"
                   - "has:attachment filename:pdf"
            max_results: Maximum messages to return

        Returns:
            List of {"id": message_id, "threadId": thread_id}
        """
        try:
            messages = []
            page_token = None

            while len(messages) < max_results:
                result = self.service.users().messages().list(
                    userId=self.user_id,
                    q=query,
                    maxResults=min(500, max_results - len(messages)),
                    pageToken=page_token
                ).execute()

                if 'messages' in result:
                    messages.extend(result['messages'])

                page_token = result.get('nextPageToken')
                if not page_token:
                    break

            logger.debug(f"Found {len(messages)} messages matching query")
            return messages[:max_results]

        except HttpError as e:
            logger.error(f"Search failed: {e}")
            raise GmailAPIError(f"Search failed: {e}")

    def get_message_metadata(self, message_id: str) -> Dict[str, Any]:
        """
        Get message metadata (headers only, no body).

        Returns:
            {
                "id": str,
                "threadId": str,
                "labelIds": List[str],
                "headers": {"From": str, "Subject": str, "Date": str, ...}
            }
        """
        try:
            msg = self.service.users().messages().get(
                userId=self.user_id,
                id=message_id,
                format='metadata',
                metadataHeaders=['From', 'Subject', 'Date', 'Message-ID']
            ).execute()

            # Flatten headers into dict
            headers = {}
            for header in msg.get('payload', {}).get('headers', []):
                headers[header['name']] = header['value']

            return {
                'id': msg['id'],
                'threadId': msg['threadId'],
                'labelIds': msg.get('labelIds', []),
                'headers': headers
            }

        except HttpError as e:
            logger.error(f"Failed to get metadata for {message_id}: {e}")
            raise GmailAPIError(f"Failed to get metadata: {e}")

    def get_message_full(self, message_id: str) -> Dict[str, Any]:
        """
        Get full message including body and attachment info.

        Returns:
            Full message resource with payload containing parts
        """
        try:
            return self.service.users().messages().get(
                userId=self.user_id,
                id=message_id,
                format='full'
            ).execute()

        except HttpError as e:
            logger.error(f"Failed to get message {message_id}: {e}")
            raise GmailAPIError(f"Failed to get message: {e}")

    def get_attachment(self, message_id: str, attachment_id: str) -> bytes:
        """
        Download attachment by ID.

        Returns:
            Raw attachment bytes
        """
        try:
            attachment = self.service.users().messages().attachments().get(
                userId=self.user_id,
                messageId=message_id,
                id=attachment_id
            ).execute()

            # Attachment data is base64url encoded
            data = attachment['data']
            return base64.urlsafe_b64decode(data)

        except HttpError as e:
            logger.error(f"Failed to get attachment {attachment_id}: {e}")
            raise GmailAPIError(f"Failed to get attachment: {e}")

    def extract_attachments_info(self, message: Dict) -> List[Dict[str, Any]]:
        """
        Extract attachment information from message payload.

        Returns:
            List of {
                "attachment_id": str,
                "filename": str,
                "mime_type": str,
                "size": int
            }
        """
        attachments = []

        def walk_parts(parts):
            for part in parts:
                filename = part.get('filename', '')
                body = part.get('body', {})
                attachment_id = body.get('attachmentId')

                if attachment_id and filename:
                    attachments.append({
                        'attachment_id': attachment_id,
                        'filename': filename,
                        'mime_type': part.get('mimeType', ''),
                        'size': body.get('size', 0)
                    })

                # Recurse into nested parts
                if 'parts' in part:
                    walk_parts(part['parts'])

        payload = message.get('payload', {})
        if 'parts' in payload:
            walk_parts(payload['parts'])

        return attachments

    def __enter__(self):
        self.authenticate()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        # No cleanup needed - HTTP-based
        return False
